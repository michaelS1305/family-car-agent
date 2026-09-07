from dataclasses import dataclass
import secrets
import threading
import time

from database import (
    get_family_by_location,
    get_family_profile,
    update_family_address,
    update_family_member_role,
)
from geocoding_service import geocode_address
from identity import CurrentUser
from onboarding_rules import parse_home_address


class FamilyProfileError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyMember:
    member_ref: str
    name: str
    role: str | None
    is_family_admin: bool


@dataclass(frozen=True)
class StoredFamilyAddressResolution:
    user_id: int
    family_id: int
    normalized_address: str
    display_address: str
    latitude: float
    longitude: float
    expires_at: float


FAMILY_ADDRESS_RESOLUTION_TTL_SECONDS = 15 * 60
_address_resolution_lock = threading.Lock()
_address_resolutions = {}


def _require_family(current_user: CurrentUser):
    if current_user.family_id is None:
        raise FamilyProfileError(
            "FAMILY_ACCESS_DENIED",
            "לא ניתן לגשת לפרטי המשפחה.",
            403,
        )


def _profile_member_response(row, creator_user_id):
    return FamilyMember(
        member_ref=row[0],
        name=row[1],
        role=row[2],
        is_family_admin=row[3] == creator_user_id,
    )


def _updated_member_response(row):
    return FamilyMember(
        member_ref=row[0],
        name=row[1],
        role=row[2],
        is_family_admin=bool(row[3]),
    )


def get_family_for_current_user(current_user: CurrentUser):
    _require_family(current_user)
    profile = get_family_profile(current_user.family_id)
    if profile is None:
        raise FamilyProfileError(
            "FAMILY_NOT_FOUND",
            "לא הצלחנו למצוא את המשפחה.",
            404,
        )

    family, member_rows = profile
    name, home_address, family_code, creator_user_id = family
    if creator_user_id is None:
        raise FamilyProfileError(
            "FAMILY_CREATOR_NOT_CONFIGURED",
            "פרטי ניהול המשפחה עדיין אינם זמינים.",
            503,
        )

    return {
        "name": name,
        "home_address": home_address,
        "family_code": family_code,
        "can_edit_roles": creator_user_id == current_user.user_id,
        "members": [
            _profile_member_response(row, creator_user_id)
            for row in member_rows
        ],
    }


def set_family_member_role(current_user: CurrentUser, member_ref, role):
    profile = get_family_for_current_user(current_user)
    if not profile["can_edit_roles"]:
        raise FamilyProfileError(
            "FAMILY_ROLE_FORBIDDEN",
            "רק מנהל המשפחה יכול לעדכן תפקידים.",
            403,
        )

    updated = update_family_member_role(
        current_user.user_id,
        current_user.family_id,
        member_ref,
        role,
    )
    if updated is None:
        # Foreign and nonexistent public references deliberately share one response.
        raise FamilyProfileError(
            "FAMILY_MEMBER_NOT_FOUND",
            "לא הצלחנו למצוא את בן המשפחה.",
            404,
        )

    return _updated_member_response(updated)


def _require_family_creator(current_user: CurrentUser):
    profile = get_family_for_current_user(current_user)
    if not profile["can_edit_roles"]:
        raise FamilyProfileError(
            "FAMILY_ADDRESS_FORBIDDEN",
            "רק מנהל המשפחה יכול לשנות את כתובת המשפחה.",
            403,
        )


def resolve_family_address_for_current_user(current_user: CurrentUser, home_address):
    _require_family_creator(current_user)
    parsed = parse_home_address(home_address)
    if not parsed:
        raise FamilyProfileError(
            "INVALID_ADDRESS_FORMAT",
            "יש לכתוב כתובת בפורמט: עיר, רחוב, מספר בית.",
            400,
        )

    city, street, house_number = parsed
    normalized_address = f"{city}, {street}, {house_number}"
    try:
        location = geocode_address(city=city, street=street, house_number=house_number)
    except Exception as exc:
        raise FamilyProfileError(
            "ADDRESS_SERVICE_UNAVAILABLE",
            "לא הצלחנו לבדוק את הכתובת כרגע. נסו שוב.",
            503,
        ) from exc
    if not location:
        raise FamilyProfileError(
            "ADDRESS_NOT_FOUND",
            "לא הצלחנו למצוא את הכתובת. בדקו את הפרטים ונסו שוב.",
            422,
        )

    existing = get_family_by_location(location["latitude"], location["longitude"])
    if existing is not None and existing[0] != current_user.family_id:
        raise FamilyProfileError(
            "FAMILY_ALREADY_EXISTS_AT_ADDRESS",
            "כבר קיימת משפחה אחרת בכתובת הזו.",
            409,
        )

    token = secrets.token_urlsafe(32)
    stored = StoredFamilyAddressResolution(
        user_id=current_user.user_id,
        family_id=current_user.family_id,
        normalized_address=normalized_address,
        display_address=location["address"],
        latitude=location["latitude"],
        longitude=location["longitude"],
        expires_at=time.monotonic() + FAMILY_ADDRESS_RESOLUTION_TTL_SECONDS,
    )
    with _address_resolution_lock:
        stale_tokens = [
            item_token
            for item_token, item in _address_resolutions.items()
            if item.user_id == current_user.user_id
        ]
        for stale_token in stale_tokens:
            _address_resolutions.pop(stale_token, None)
        _address_resolutions[token] = stored

    return {
        "normalized_address": normalized_address,
        "display_address": location["address"],
        "resolution_token": token,
    }


def update_family_address_for_current_user(current_user: CurrentUser, resolution_token):
    _require_family_creator(current_user)
    with _address_resolution_lock:
        stored = _address_resolutions.get(resolution_token)
        if (
            stored is None
            or stored.user_id != current_user.user_id
            or stored.family_id != current_user.family_id
            or stored.expires_at <= time.monotonic()
        ):
            _address_resolutions.pop(resolution_token, None)
            raise FamilyProfileError(
                "ADDRESS_RESOLUTION_EXPIRED",
                "תוקף בדיקת הכתובת פג. יש לבדוק אותה מחדש.",
                409,
            )
        _address_resolutions.pop(resolution_token, None)

    updated = update_family_address(
        current_user.user_id,
        current_user.family_id,
        stored.normalized_address,
        stored.latitude,
        stored.longitude,
    )
    if updated is None:
        raise FamilyProfileError(
            "FAMILY_ADDRESS_FORBIDDEN",
            "רק מנהל המשפחה יכול לשנות את כתובת המשפחה.",
            403,
        )

    return {"home_address": updated[0]}
