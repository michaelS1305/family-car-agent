from dataclasses import dataclass

from database import get_family_profile, update_family_member_role
from identity import CurrentUser


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
