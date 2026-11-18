from datetime import datetime, timedelta
from uuid import UUID

from reservation_rules import (
    canonical_time as _canonical_time,
    local_now as _local_now,
    validate_create,
    ReservationValidationError,
)

from database import (
    VEHICLE_UNSET,
    cancel_current_user_reservation,
    create_current_user_reservation,
    list_family_reservations,
    update_current_user_reservation,
)


class ReservationCenterError(Exception):
    def __init__(self, code, message, status_code, vehicles=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.vehicles = vehicles


def _require_family(current_user):
    if current_user.family_id is None:
        raise ReservationCenterError(
            "FAMILY_ACCESS_DENIED",
            "לא ניתן לגשת להזמנות המשפחה.",
            403,
        )


def _validated_interval(start_time, end_time, now):
    try:
        return validate_create(start_time, end_time, now)
    except ReservationValidationError as error:
        raise ReservationCenterError(error.code, error.message, 422) from None


def _safe_reservation(row):
    return {
        "owner_name": row[0],
        "start_time": row[1],
        "end_time": row[2],
        "is_mine": bool(row[3]),
        "reservation_ref": str(row[4]),
        "vehicle_ref": str(row[5]) if row[5] else None,
        "vehicle_display_name": row[6],
        "member_ref": str(row[7]),
        "vehicle_category": row[8],
    }


def list_reservations(current_user, time_filter=None, scope="all", *,
                      range_start=None, range_end=None, vehicle_ref=None, member_ref=None):
    _require_family(current_user)
    bounded = range_start is not None or range_end is not None
    if (scope not in {"all", "mine"}
            or time_filter not in {None, "future", "past"}
            or (bounded and time_filter is not None)
            or (not bounded and (vehicle_ref is not None or member_ref is not None))
            or (member_ref is not None and scope == "mine")):
        raise ReservationCenterError(
            "INVALID_RESERVATION_FILTER",
            "מסנן ההזמנות אינו תקין.",
            422,
        )
    filters = {}
    if bounded:
        try:
            start, end = _canonical_time(range_start), _canonical_time(range_end)
            duration = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            if not timedelta(0) < duration <= timedelta(days=42):
                raise ValueError
        except (ReservationValidationError, ValueError):
            raise ReservationCenterError('INVALID_RESERVATION_RANGE', 'טווח ההזמנות אינו תקין.', 422) from None
        filters = {'range_start': start, 'range_end': end}
        for key, value in (('vehicle_ref', vehicle_ref), ('member_ref', member_ref)):
            if value is not None:
                try:
                    filters[key] = str(UUID(value))
                except (ValueError, TypeError, AttributeError):
                    raise ReservationCenterError('INVALID_RESERVATION_FILTER', 'מסנן ההזמנות אינו תקין.', 422) from None
    boundary = _canonical_time(_local_now())
    rows = list_family_reservations(
        current_user.family_id,
        current_user.user_id,
        time_filter or "future",
        scope,
        boundary,
        **filters,
    )
    # None means a scoped public filter could not be resolved; [] is a valid empty range.
    if rows is None:
        raise ReservationCenterError('RESERVATION_FILTER_NOT_FOUND_OR_UNAVAILABLE',
                                     'מסנן ההזמנות אינו זמין.', 404)
    return [_safe_reservation(row) for row in rows]


def create_reservation_for_current_user(current_user, start_time, end_time, *, vehicle_ref=VEHICLE_UNSET):
    _require_family(current_user)
    start, end = _validated_interval(start_time, end_time, _local_now())
    result = create_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        start,
        end,
        **({} if vehicle_ref is VEHICLE_UNSET else {'vehicle_ref': vehicle_ref}),
    )
    _raise_for_result(result)
    return {
        "owner_name": current_user.name,
        "start_time": start,
        "end_time": end,
        "is_mine": True,
        **{key: result.get(key) for key in ('reservation_ref', 'vehicle_ref', 'vehicle_display_name', 'member_ref', 'vehicle_category')},
    }


def update_reservation_for_current_user(
    current_user,
    original_start_time,
    original_end_time,
    start_time,
    end_time,
    *, reservation_ref=None, vehicle_ref=VEHICLE_UNSET,
):
    _require_family(current_user)
    now = _local_now()
    result = update_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        original_start_time,
        original_end_time,
        _canonical_time(now),
        start_time,
        end_time,
        **({} if reservation_ref is None else {'reservation_ref': reservation_ref}),
        **({} if vehicle_ref is VEHICLE_UNSET else {'vehicle_ref': vehicle_ref}),
    )
    _raise_for_result(result)
    return {
        "owner_name": current_user.name,
        "start_time": result["start_time"],
        "end_time": result["end_time"],
        "is_mine": True,
        **{key: result.get(key) for key in ('reservation_ref', 'vehicle_ref', 'vehicle_display_name', 'member_ref', 'vehicle_category')},
    }


def cancel_reservation_for_current_user(
    current_user,
    original_start_time,
    original_end_time,
    *, reservation_ref=None,
):
    _require_family(current_user)
    now = _local_now()
    result = cancel_current_user_reservation(
        current_user.user_id,
        current_user.family_id,
        original_start_time,
        original_end_time,
        _canonical_time(now),
        **({} if reservation_ref is None else {'reservation_ref': reservation_ref}),
    )
    _raise_for_result(result)
    return {"cancelled": True}


def _raise_for_result(result):
    if result.get("success"):
        return
    if result.get('code') in {'VEHICLE_REQUIRED', 'RESERVATION_AMBIGUOUS', 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE'}:
        raise ReservationCenterError(result['code'], result['message'],
                                     404 if result['code'] == 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE' else 409,
                                     result.get('vehicles'))
    if result.get("code") in {"INVALID_RESERVATION_TIME", "RESERVATION_TIME_IN_PAST"}:
        raise ReservationCenterError(result["code"], result["message"], 422)
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
