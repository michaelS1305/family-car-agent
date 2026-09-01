from database import (
    AuthUserAlreadyMappedError,
    InvalidJoinStepError,
    JoinSessionLockedError,
    complete_pwa_join,
    confirm_pwa_join_address,
    record_pwa_join_failure,
    start_pwa_join_session,
    submit_pwa_join_address,
    submit_pwa_join_family_name,
    verify_pwa_join_family_code,
)
from geocoding_service import geocode_address
from onboarding_rules import (
    is_valid_family_code,
    normalize_human_name,
    parse_home_address,
)


ERROR_MESSAGES = {
    "JOIN_FAMILY_NAME_NOT_FOUND": (
        "לא מצאנו משפחה בשם הזה. בדוק את האיות ונסה שוב."
    ),
    "INVALID_FAMILY_NAME": (
        "שם המשפחה יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות."
    ),
    "INVALID_ADDRESS_FORMAT": (
        "הכתובת לא נראית מלאה. יש לכתוב: עיר, רחוב, מספר בית."
    ),
    "JOIN_FAMILY_ADDRESS_NOT_FOUND": (
        "לא מצאנו משפחה בכתובת הזו. בדוק את האיות ואת מספר הבית ונסה שוב."
    ),
    "INVALID_FAMILY_CODE": "קוד המשפחה אינו נכון.",
    "INVALID_USER_NAME": "השם הפרטי יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.",
    "AUTH_USER_ALREADY_MAPPED": "החשבון כבר משויך למשתמש במערכת.",
    "JOIN_LOCKED": "תהליך ההצטרפות נעול זמנית לאחר שלושה ניסיונות.",
    "INVALID_JOIN_STEP": "תהליך ההצטרפות אינו מסונכרן. התחילו אותו מחדש.",
    "SERVER_ERROR": "לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.",
}


class JoinFamilyError(Exception):
    def __init__(
        self,
        code,
        status_code,
        message=None,
        attempts_remaining=None,
        locked_until=None,
    ):
        resolved_message = message or ERROR_MESSAGES[code]
        super().__init__(resolved_message)
        self.code = code
        self.status_code = status_code
        self.message = resolved_message
        self.attempts_remaining = attempts_remaining
        self.locked_until = locked_until

    def detail(self):
        detail = {"code": self.code, "message": self.message}
        if self.attempts_remaining is not None:
            detail["attempts_remaining"] = self.attempts_remaining
        if self.locked_until is not None:
            detail["locked_until"] = _serialize_datetime(self.locked_until)
        return detail


def _serialize_datetime(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _call_database(function, *args):
    try:
        return function(*args)
    except JoinSessionLockedError as exc:
        raise JoinFamilyError(
            "JOIN_LOCKED",
            429,
            message=(
                "תהליך ההצטרפות נעול ל-15 דקות לאחר שלושה ניסיונות. "
                "בדקו את הפרטים עם בן המשפחה שיצר את המשפחה ונסו שוב לאחר תום הנעילה."
            ),
            attempts_remaining=0,
            locked_until=exc.locked_until,
        ) from exc
    except AuthUserAlreadyMappedError as exc:
        raise JoinFamilyError("AUTH_USER_ALREADY_MAPPED", 409) from exc
    except InvalidJoinStepError as exc:
        raise JoinFamilyError("INVALID_JOIN_STEP", 409) from exc


def _public_session(session):
    return {
        "step": session["step"],
        "family_name": session["family_name"],
        "normalized_address": session["normalized_address"],
        "resolved_address": session["resolved_address"],
        "attempts_remaining": {
            "family_name": 3 - session["family_name_attempts"],
            "address": 3 - session["address_attempts"],
            "family_code": 3 - session["family_code_attempts"],
        },
        "reset": session.get("was_reset", False),
    }


def _failure_message(base_message, attempts_remaining):
    if attempts_remaining == 2:
        return f"{base_message} נותרו 2 ניסיונות."
    if attempts_remaining == 1:
        return (
            f"{base_message} נותר ניסיון אחרון. "
            "אין לנחש; מומלץ לבדוק את הפרטים מול בן המשפחה שיצר את המשפחה."
        )
    return (
        f"{base_message} תהליך ההצטרפות ננעל ל-15 דקות. "
        "בדקו את הפרטים מול בן המשפחה שיצר את המשפחה לפני ניסיון נוסף."
    )


def _raise_attempt_failure(result, code):
    attempts_remaining = result["attempts_remaining"]
    locked_until = result.get("locked_until")
    if attempts_remaining == 0:
        raise JoinFamilyError(
            "JOIN_LOCKED",
            429,
            message=_failure_message(ERROR_MESSAGES[code], 0),
            attempts_remaining=0,
            locked_until=locked_until,
        )
    raise JoinFamilyError(
        code,
        400 if code.startswith("INVALID_") else 404,
        message=_failure_message(ERROR_MESSAGES[code], attempts_remaining),
        attempts_remaining=attempts_remaining,
    )


def start_join_family(auth_user_id):
    session = _call_database(start_pwa_join_session, auth_user_id)
    return _public_session(session)


def submit_join_family_name(auth_user_id, family_name):
    normalized_name = normalize_human_name(family_name)
    if normalized_name is None:
        result = _call_database(
            record_pwa_join_failure,
            auth_user_id,
            "family_name",
            ("family_name", "address", "address_confirmed", "family_code"),
        )
        _raise_attempt_failure(result, "INVALID_FAMILY_NAME")
    result = _call_database(
        submit_pwa_join_family_name,
        auth_user_id,
        normalized_name,
    )
    if not result["success"]:
        _raise_attempt_failure(result, "JOIN_FAMILY_NAME_NOT_FOUND")
    return _public_session(result["session"])


def submit_join_family_address(auth_user_id, home_address):
    parsed_address = parse_home_address(home_address)
    if not parsed_address:
        result = _call_database(
            record_pwa_join_failure,
            auth_user_id,
            "address",
            ("address", "address_confirmed", "family_code"),
        )
        _raise_attempt_failure(result, "INVALID_ADDRESS_FORMAT")

    city, street, house_number = parsed_address
    normalized_address = f"{city}, {street}, {house_number}"
    try:
        location = geocode_address(
            city=city,
            street=street,
            house_number=house_number,
        )
    except Exception as exc:
        raise JoinFamilyError("SERVER_ERROR", 503) from exc

    if not location:
        result = _call_database(
            record_pwa_join_failure,
            auth_user_id,
            "address",
            ("address", "address_confirmed", "family_code"),
        )
        _raise_attempt_failure(result, "JOIN_FAMILY_ADDRESS_NOT_FOUND")

    result = _call_database(
        submit_pwa_join_address,
        auth_user_id,
        normalized_address,
        location["address"],
        location["latitude"],
        location["longitude"],
    )
    if not result["success"]:
        _raise_attempt_failure(result, "JOIN_FAMILY_ADDRESS_NOT_FOUND")
    return _public_session(result["session"])


def confirm_join_family_address(auth_user_id, confirmed):
    session = _call_database(
        confirm_pwa_join_address,
        auth_user_id,
        confirmed,
    )
    return _public_session(session)


def submit_join_family_code(auth_user_id, family_code):
    normalized_code = family_code.strip()
    if not is_valid_family_code(normalized_code):
        result = _call_database(
            record_pwa_join_failure,
            auth_user_id,
            "family_code",
            ("family_code",),
        )
        _raise_attempt_failure(result, "INVALID_FAMILY_CODE")

    result = _call_database(
        verify_pwa_join_family_code,
        auth_user_id,
        normalized_code,
    )
    if not result["success"]:
        _raise_attempt_failure(result, "INVALID_FAMILY_CODE")
    return _public_session(result["session"])


def complete_join_family(auth_user_id, user_name):
    normalized_name = normalize_human_name(user_name)
    if normalized_name is None:
        raise JoinFamilyError("INVALID_USER_NAME", 400)
    _call_database(complete_pwa_join, auth_user_id, normalized_name)
    return {"created": True}
