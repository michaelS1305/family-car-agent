from dataclasses import dataclass

from database import (
    AddressConfirmationInvalidError,
    FamilyAddressForbiddenError,
    AuthUserIdentityNotFoundError,
    FamilyAlreadyExistsAtLocationError,
    issue_family_address_confirmation,
    FamilyCodeTakenError,
    regenerate_family_code,
    get_family_by_location,
    get_family_profile,
    update_family_address,
    update_family_member_role,
)
from geocoding_service import geocode_address
from geocoding_capacity import GeocodingAdmissionError, geocode_with_capacity
from identity import CurrentUser
from onboarding_rules import parse_home_address


class FamilyProfileError(Exception):
    def __init__(self, code, message, status_code, retry_after_seconds=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class FamilyMember:
    member_ref: str
    name: str
    role: str | None
    is_family_admin: bool


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


def regenerate_code_for_current_user(current_user: CurrentUser):
    _require_family(current_user)
    try:
        code = regenerate_family_code(current_user.user_id, current_user.family_id)
    except FamilyCodeTakenError as exc:
        raise FamilyProfileError(
            "FAMILY_CODE_UNAVAILABLE", "לא הצלחנו ליצור קוד חדש כרגע. נסו שוב.", 503,
        ) from exc
    if code is None:
        raise FamilyProfileError(
            "FAMILY_CODE_FORBIDDEN", "רק מנהל המשפחה יכול ליצור קוד חדש.", 403,
        )
    return {"family_code": code}


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
    if len(home_address) > 200:
        raise FamilyProfileError(
            "ADDRESS_TOO_LONG", "הכתובת ארוכה מדי. ניתן להזין עד 200 תווים.", 400
        )
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
        location = geocode_with_capacity(
            current_user.auth_user_id,
            geocode_address,
            city=city, street=street, house_number=house_number,
        )
    except GeocodingAdmissionError as exc:
        messages = {
            "GEOCODING_RATE_LIMITED": "בוצעו יותר מדי בדיקות כתובת. נסו שוב מאוחר יותר.",
            "GEOCODING_USER_BUSY": "בדיקת כתובת אחרת עדיין מתבצעת. נסו שוב בעוד רגע.",
            "GEOCODING_CAPACITY_FULL": "שירות בדיקת הכתובות עמוס כרגע. נסו שוב בעוד רגע.",
        }
        raise FamilyProfileError(
            exc.code, messages[exc.code], exc.status_code, exc.retry_after_seconds
        ) from exc
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

    # Recheck creator/family authorization after the unlocked provider wait.
    _require_family_creator(current_user)

    existing = get_family_by_location(
        location["latitude"], location["longitude"], exclude_family_id=current_user.family_id,
    )
    if existing is not None:
        raise FamilyProfileError(
            "FAMILY_ALREADY_EXISTS_AT_ADDRESS",
            "כבר קיימת משפחה אחרת בכתובת הזו.",
            409,
        )

    try:
        token = issue_family_address_confirmation(
            current_user.auth_user_id, normalized_address, location["address"],
            location["latitude"], location["longitude"],
            user_id=current_user.user_id, family_id=current_user.family_id,
        )
    except (FamilyAddressForbiddenError, AuthUserIdentityNotFoundError) as exc:
        raise FamilyProfileError(
            "FAMILY_ADDRESS_FORBIDDEN", "רק מנהל המשפחה יכול לשנות את כתובת המשפחה.", 403,
        ) from exc

    return {
        "normalized_address": normalized_address,
        "display_address": location["address"],
        "resolution_token": token,
    }


def update_family_address_for_current_user(current_user: CurrentUser, resolution_token):
    _require_family_creator(current_user)
    try:
        updated = update_family_address(
            current_user.user_id, current_user.family_id,
            current_user.auth_user_id, resolution_token,
        )
    except AddressConfirmationInvalidError as exc:
        raise FamilyProfileError(
            "ADDRESS_RESOLUTION_EXPIRED", "תוקף בדיקת הכתובת פג. יש לבדוק אותה מחדש.", 409,
        ) from exc
    except FamilyAlreadyExistsAtLocationError as exc:
        raise FamilyProfileError(
            "FAMILY_ALREADY_EXISTS_AT_ADDRESS", "כבר קיימת משפחה אחרת בכתובת הזו.", 409,
        ) from exc
    except FamilyAddressForbiddenError as exc:
        raise FamilyProfileError(
            "FAMILY_ADDRESS_FORBIDDEN",
            "רק מנהל המשפחה יכול לשנות את כתובת המשפחה.",
            403,
        ) from exc

    return {"home_address": updated[0]}
