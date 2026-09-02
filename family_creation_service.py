from dataclasses import dataclass
import secrets
import threading
import time

from database import (
    AuthUserAlreadyMappedError,
    AuthUserIdentityNotFoundError,
    FamilyAlreadyExistsAtLocationError,
    FamilyCodeTakenError,
    create_family_with_first_user,
    get_family_by_code,
    get_family_by_location,
    get_user_by_auth_user_id,
)
from geocoding_service import geocode_address
from onboarding_rules import (
    is_valid_family_code,
    normalize_human_name,
    parse_home_address,
)


ERROR_MESSAGES = {
    "INVALID_FAMILY_NAME": "שם המשפחה יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.",
    "INVALID_FAMILY_CODE": "קוד המשפחה חייב להכיל בדיוק 6 ספרות.",
    "FAMILY_CODE_TAKEN": "קוד המשפחה הזה כבר תפוס. בחרו קוד אחר.",
    "INVALID_ADDRESS_FORMAT": "יש לכתוב כתובת בפורמט: עיר, רחוב, מספר בית.",
    "ADDRESS_NOT_FOUND": "לא הצלחנו למצוא את הכתובת. בדקו את הפרטים ונסו שוב.",
    "ADDRESS_RESOLUTION_EXPIRED": "תוקף אימות הכתובת פג. יש לבדוק ולאשר אותה מחדש.",
    "FAMILY_ALREADY_EXISTS_AT_ADDRESS": (
        "כבר קיימת משפחה בכתובת הזו. אם זו המשפחה שלך, "
        "בחר הצטרפות למשפחה."
    ),
    "INVALID_USER_NAME": "השם הפרטי יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.",
    "AUTH_USER_ALREADY_MAPPED": "החשבון כבר משויך למשתמש במערכת.",
    "AUTH_SESSION_INVALID": "ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.",
    "SERVER_ERROR": "לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.",
}


class FamilyCreationError(Exception):
    def __init__(self, code, status_code):
        super().__init__(ERROR_MESSAGES[code])
        self.code = code
        self.status_code = status_code
        self.message = ERROR_MESSAGES[code]


@dataclass(frozen=True)
class ResolvedAddress:
    normalized_address: str
    display_address: str
    latitude: float
    longitude: float
    resolution_token: str | None = None


@dataclass(frozen=True)
class StoredAddressResolution:
    auth_user_id: str
    address: ResolvedAddress
    expires_at: float


ADDRESS_RESOLUTION_TTL_SECONDS = 15 * 60
_resolution_lock = threading.Lock()
_address_resolutions = {}
_auth_resolution_tokens = {}


def _store_address_resolution(auth_user_id, resolved):
    token = secrets.token_urlsafe(32)
    stored = StoredAddressResolution(
        auth_user_id=auth_user_id,
        address=resolved,
        expires_at=time.monotonic() + ADDRESS_RESOLUTION_TTL_SECONDS,
    )
    with _resolution_lock:
        previous_token = _auth_resolution_tokens.get(auth_user_id)
        if previous_token:
            _address_resolutions.pop(previous_token, None)
        _address_resolutions[token] = stored
        _auth_resolution_tokens[auth_user_id] = token
    return token


def _get_address_resolution(auth_user_id, token):
    if not isinstance(token, str) or not token:
        raise FamilyCreationError("ADDRESS_RESOLUTION_EXPIRED", 409)
    with _resolution_lock:
        stored = _address_resolutions.get(token)
        if stored is None or stored.auth_user_id != auth_user_id:
            raise FamilyCreationError("ADDRESS_RESOLUTION_EXPIRED", 409)
        if stored.expires_at <= time.monotonic():
            _address_resolutions.pop(token, None)
            if _auth_resolution_tokens.get(auth_user_id) == token:
                _auth_resolution_tokens.pop(auth_user_id, None)
            raise FamilyCreationError("ADDRESS_RESOLUTION_EXPIRED", 409)
        return stored.address


def _discard_address_resolution(auth_user_id, token):
    with _resolution_lock:
        stored = _address_resolutions.get(token)
        if stored and stored.auth_user_id == auth_user_id:
            _address_resolutions.pop(token, None)
        if _auth_resolution_tokens.get(auth_user_id) == token:
            _auth_resolution_tokens.pop(auth_user_id, None)


def _required_text(value, error_code):
    normalized = normalize_human_name(value)
    if normalized is None:
        raise FamilyCreationError(error_code, 400)
    return normalized


def _ensure_auth_user_is_unmapped(auth_user_id):
    if get_user_by_auth_user_id(auth_user_id) is not None:
        raise FamilyCreationError("AUTH_USER_ALREADY_MAPPED", 409)


def _resolve_address(home_address):
    parsed_address = parse_home_address(home_address)
    if not parsed_address:
        raise FamilyCreationError("INVALID_ADDRESS_FORMAT", 400)

    city, street, house_number = parsed_address
    normalized_address = f"{city}, {street}, {house_number}"

    try:
        location = geocode_address(
            city=city,
            street=street,
            house_number=house_number,
        )
    except Exception as exc:
        raise FamilyCreationError("SERVER_ERROR", 503) from exc

    if not location:
        raise FamilyCreationError("ADDRESS_NOT_FOUND", 422)

    resolved = ResolvedAddress(
        normalized_address=normalized_address,
        display_address=location["address"],
        latitude=location["latitude"],
        longitude=location["longitude"],
    )

    if get_family_by_location(resolved.latitude, resolved.longitude):
        raise FamilyCreationError("FAMILY_ALREADY_EXISTS_AT_ADDRESS", 409)

    return resolved


def resolve_create_family_address(auth_user_id, home_address):
    _ensure_auth_user_is_unmapped(auth_user_id)
    resolved = _resolve_address(home_address)
    token = _store_address_resolution(auth_user_id, resolved)
    return ResolvedAddress(
        normalized_address=resolved.normalized_address,
        display_address=resolved.display_address,
        latitude=resolved.latitude,
        longitude=resolved.longitude,
        resolution_token=token,
    )


def create_family_for_auth_user(
    auth_user_id,
    family_name,
    family_code,
    address_resolution_token,
    user_name,
):
    _ensure_auth_user_is_unmapped(auth_user_id)
    normalized_family_name = _required_text(family_name, "INVALID_FAMILY_NAME")
    normalized_user_name = _required_text(user_name, "INVALID_USER_NAME")
    normalized_family_code = family_code.strip()

    if not is_valid_family_code(normalized_family_code):
        raise FamilyCreationError("INVALID_FAMILY_CODE", 400)

    if get_family_by_code(normalized_family_code):
        raise FamilyCreationError("FAMILY_CODE_TAKEN", 409)

    resolved_address = _get_address_resolution(
        auth_user_id,
        address_resolution_token,
    )

    try:
        create_family_with_first_user(
            name=normalized_family_name,
            family_code=normalized_family_code,
            home_address=resolved_address.normalized_address,
            user_name=normalized_user_name,
            home_latitude=resolved_address.latitude,
            home_longitude=resolved_address.longitude,
            auth_user_id=auth_user_id,
            prevent_duplicate_location=True,
        )
    except FamilyCodeTakenError as exc:
        raise FamilyCreationError("FAMILY_CODE_TAKEN", 409) from exc
    except AuthUserAlreadyMappedError as exc:
        raise FamilyCreationError("AUTH_USER_ALREADY_MAPPED", 409) from exc
    except AuthUserIdentityNotFoundError as exc:
        raise FamilyCreationError("AUTH_SESSION_INVALID", 401) from exc
    except FamilyAlreadyExistsAtLocationError as exc:
        raise FamilyCreationError("FAMILY_ALREADY_EXISTS_AT_ADDRESS", 409) from exc

    _discard_address_resolution(auth_user_id, address_resolution_token)
    return {"created": True}
