from dataclasses import dataclass

from database import (
    AddressConfirmationInvalidError,
    issue_family_address_confirmation,
    AuthUserAlreadyMappedError,
    AuthUserIdentityNotFoundError,
    FamilyAlreadyExistsAtLocationError,
    FamilyCodeTakenError,
    create_family_with_first_user,
    get_family_by_location,
    get_user_by_auth_user_id,
)
from geocoding_service import geocode_address
from geocoding_capacity import GeocodingAdmissionError, geocode_with_capacity
from onboarding_rules import (
    HUMAN_NAME_MAX_LENGTH,
    normalize_human_name,
    parse_home_address,
)


ERROR_MESSAGES = {
    "INVALID_FAMILY_NAME": "שם המשפחה יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.",
    "INVALID_ADDRESS_FORMAT": "יש לכתוב כתובת בפורמט: עיר, רחוב, מספר בית.",
    "ADDRESS_TOO_LONG": "הכתובת ארוכה מדי. ניתן להזין עד 200 תווים.",
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
    "GEOCODING_RATE_LIMITED": "בוצעו יותר מדי בדיקות כתובת. נסו שוב מאוחר יותר.",
    "GEOCODING_USER_BUSY": "בדיקת כתובת אחרת עדיין מתבצעת. נסו שוב בעוד רגע.",
    "GEOCODING_CAPACITY_FULL": "שירות בדיקת הכתובות עמוס כרגע. נסו שוב בעוד רגע.",
}


class FamilyCreationError(Exception):
    def __init__(self, code, status_code, retry_after_seconds=None):
        super().__init__(ERROR_MESSAGES[code])
        self.code = code
        self.status_code = status_code
        self.message = ERROR_MESSAGES[code]
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ResolvedAddress:
    normalized_address: str
    display_address: str
    latitude: float
    longitude: float
    resolution_token: str | None = None


def _required_text(value, error_code):
    if not isinstance(value, str) or len(value) > HUMAN_NAME_MAX_LENGTH:
        raise FamilyCreationError(error_code, 400)
    normalized = normalize_human_name(value)
    if normalized is None:
        raise FamilyCreationError(error_code, 400)
    return normalized


def _ensure_auth_user_is_unmapped(auth_user_id):
    if get_user_by_auth_user_id(auth_user_id) is not None:
        raise FamilyCreationError("AUTH_USER_ALREADY_MAPPED", 409)


def _resolve_address(auth_user_id, home_address):
    if len(home_address) > 200:
        raise FamilyCreationError("ADDRESS_TOO_LONG", 400)
    parsed_address = parse_home_address(home_address)
    if not parsed_address:
        raise FamilyCreationError("INVALID_ADDRESS_FORMAT", 400)

    city, street, house_number = parsed_address
    normalized_address = f"{city}, {street}, {house_number}"

    try:
        location = geocode_with_capacity(
            auth_user_id,
            geocode_address,
            city=city, street=street, house_number=house_number,
        )
    except GeocodingAdmissionError as exc:
        raise FamilyCreationError(
            exc.code, exc.status_code, exc.retry_after_seconds
        ) from exc
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
    resolved = _resolve_address(auth_user_id, home_address)
    # The identity may have been mapped while the provider call was in flight.
    _ensure_auth_user_is_unmapped(auth_user_id)
    try:
        token = issue_family_address_confirmation(
            auth_user_id, resolved.normalized_address, resolved.display_address,
            resolved.latitude, resolved.longitude,
        )
    except AuthUserAlreadyMappedError as exc:
        raise FamilyCreationError("AUTH_USER_ALREADY_MAPPED", 409) from exc
    except AuthUserIdentityNotFoundError as exc:
        raise FamilyCreationError("AUTH_SESSION_INVALID", 401) from exc
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
    address_resolution_token,
    user_name,
):
    normalized_family_name = _required_text(family_name, "INVALID_FAMILY_NAME")
    normalized_user_name = _required_text(user_name, "INVALID_USER_NAME")
    _ensure_auth_user_is_unmapped(auth_user_id)
    if not isinstance(address_resolution_token, str) or not address_resolution_token:
        raise FamilyCreationError("ADDRESS_RESOLUTION_EXPIRED", 409)

    try:
        create_family_with_first_user(
            name=normalized_family_name,
            home_address=None,
            user_name=normalized_user_name,
            auth_user_id=auth_user_id,
            resolution_token=address_resolution_token,
        )
    except AddressConfirmationInvalidError as exc:
        raise FamilyCreationError("ADDRESS_RESOLUTION_EXPIRED", 409) from exc
    except FamilyCodeTakenError as exc:
        raise FamilyCreationError("SERVER_ERROR", 503) from exc
    except AuthUserAlreadyMappedError as exc:
        raise FamilyCreationError("AUTH_USER_ALREADY_MAPPED", 409) from exc
    except AuthUserIdentityNotFoundError as exc:
        raise FamilyCreationError("AUTH_SESSION_INVALID", 401) from exc
    except FamilyAlreadyExistsAtLocationError as exc:
        raise FamilyCreationError("FAMILY_ALREADY_EXISTS_AT_ADDRESS", 409) from exc

    return {"created": True}
