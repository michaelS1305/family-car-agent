"""Shared Jerusalem wall-clock rules; no database access or identity inputs."""
from datetime import datetime
from zoneinfo import ZoneInfo

ISRAEL_TIMEZONE = ZoneInfo("Asia/Jerusalem")


class ReservationValidationError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def result(self):
        return {"success": False, "code": self.code, "message": self.message}


def local_now():
    return datetime.now(ISRAEL_TIMEZONE).replace(tzinfo=None)


def canonical_time(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise ValueError()
        if value.tzinfo is not None:
            value = value.astimezone(ISRAEL_TIMEZONE).replace(tzinfo=None)
        return value.isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError):
        raise ReservationValidationError(
            "INVALID_RESERVATION_TIME", "התאריך או השעה אינם תקינים."
        ) from None


def interval(start, end):
    start, end = canonical_time(start), canonical_time(end)
    if start >= end:
        raise ReservationValidationError(
            "INVALID_RESERVATION_TIME", "שעת הסיום חייבת להיות אחרי שעת ההתחלה."
        )
    return start, end


def validate_create(start, end, now):
    start, end = interval(start, end)
    if datetime.fromisoformat(start) < now:
        raise ReservationValidationError(
            "RESERVATION_TIME_IN_PAST", "אפשר להזמין את הרכב רק לזמן עתידי."
        )
    return start, end


def validate_target(start, end, now):
    try:
        start, end = interval(start, end)
        if datetime.fromisoformat(end) <= now:
            raise ValueError()
    except (ReservationValidationError, ValueError):
        raise ReservationValidationError(
            "RESERVATION_NOT_FOUND_OR_UNAVAILABLE", "לא מצאנו הזמנה זמינה לשינוי."
        ) from None
    return start, end


def validate_update(start, end, original_start, original_end, now):
    original_start, _ = validate_target(original_start, original_end, now)
    start, end = interval(start, end)
    if datetime.fromisoformat(end) <= now or (
        datetime.fromisoformat(start) < now and start != original_start
    ):
        raise ReservationValidationError(
            "RESERVATION_TIME_IN_PAST", "לא ניתן לשנות את ההזמנה לזמן שכבר עבר."
        )
    return start, end
