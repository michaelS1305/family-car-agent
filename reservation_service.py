from datetime import datetime
from zoneinfo import ZoneInfo

from database import (
    cancel_current_user_reservation,
    create_current_user_reservation,
    list_family_reservations,
    update_current_user_reservation,
)
from identity import CurrentUser


ISRAEL_TIMEZONE = ZoneInfo("Asia/Jerusalem")


class ReservationCenterError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _require_family(current_user):
    if current_user.family_id is None:
        raise ReservationCenterError(
            "FAMILY_ACCESS_DENIED",
            "לא ניתן לגשת להזמנות המשפחה.",
            403,
        )


def _local_now():
    return datetime.now(ISRAEL_TIMEZONE).replace(tzinfo=None)


def _canonical_time(value):
    if value.tzinfo is not None:
        value = value.astimezone(ISRAEL_TIMEZONE).replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def _validated_interval(start_time, end_time, now):
    start = start_time
    end = end_time
    if start.tzinfo is not None:
        start = start.astimezone(ISRAEL_TIMEZONE).replace(tzinfo=None)
    if end.tzinfo is not None:
        end = end.astimezone(ISRAEL_TIMEZONE).replace(tzinfo=None)
    if start >= end:
        raise ReservationCenterError(
            "INVALID_RESERVATION_TIME",
            "שעת הסיום חייבת להיות אחרי שעת ההתחלה.",
            422,
        )
    if start < now:
        raise ReservationCenterError(
            "RESERVATION_TIME_IN_PAST",
            "אפשר להזמין את הרכב רק לזמן עתידי.",
            422,
        )
    return _canonical_time(start), _canonical_time(end)


def _safe_reservation(row):
    return {
        "owner_name": row[0],
        "start_time": row[1],
        "end_time": row[2],
        "is_mine": bool(row[3]),
    }


def list_reservations(current_user, time_filter="future", scope="all"):
    _require_family(current_user)
    if time_filter not in {"future", "past"} or scope not in {"all", "mine"}:
        raise ReservationCenterError(
            "INVALID_RESERVATION_FILTER",
            "מסנן ההזמנות אינו תקין.",
            422,
        )
    boundary = _canonical_time(_local_now())
    return [
        _safe_reservation(row)
        for row in list_family_reservations(
            current_user.family_id,
            current_user.user_id,
            time_filter,
            scope,
            boundary,
        )
    ]


def create_reservation_for_current_user(current_user, start_time, end_time):
    _require_family(current_user)
    start, end = _validated_interval(start_time, end_time, _local_now())
    result = create_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        start,
        end,
    )
    _raise_for_result(result)
    return {
        "owner_name": current_user.name,
        "start_time": start,
        "end_time": end,
        "is_mine": True,
    }


def update_reservation_for_current_user(
    current_user,
    original_start_time,
    original_end_time,
    start_time,
    end_time,
):
    _require_family(current_user)
    now = _local_now()
    start, end = _validated_interval(start_time, end_time, now)
    result = update_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        original_start_time,
        original_end_time,
        _canonical_time(now),
        start,
        end,
    )
    _raise_for_result(result)
    return {
        "owner_name": current_user.name,
        "start_time": start,
        "end_time": end,
        "is_mine": True,
    }


def cancel_reservation_for_current_user(
    current_user,
    original_start_time,
    original_end_time,
):
    _require_family(current_user)
    now = _local_now()
    result = cancel_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        original_start_time,
        original_end_time,
        _canonical_time(now),
    )
    _raise_for_result(result)
    return {"cancelled": True}


def _raise_for_result(result):
    if result.get("success"):
        return
    if result.get("code") == "RESERVATION_CONFLICT":
        raise ReservationCenterError(
            "RESERVATION_CONFLICT",
            "הרכב כבר מוזמן בזמן הזה.",
            409,
        )
    raise ReservationCenterError(
        "RESERVATION_NOT_FOUND_OR_UNAVAILABLE",
        "לא מצאנו הזמנה זמינה לשינוי.",
        404,
    )
