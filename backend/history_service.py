from database import get_car_usage_history
from identity import CurrentUser
from datetime import datetime


COMPLETED_USAGE_LIMIT = 50


class CarHistoryError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _parse_datetime(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or 'T' not in value:
            raise ValueError()
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError):
        raise CarHistoryError('INVALID_HISTORY_RANGE', 'Use offset-aware ISO date-times', 422) from None


def get_car_history(current_user: CurrentUser, *, limit=50, cursor=None, vehicle_ref=None,
                    member_ref=None, from_datetime=None, to_datetime=None):
    if current_user.family_id is None:
        raise CarHistoryError(
            "USER_WITHOUT_FAMILY",
            "The mapped user does not belong to a family",
            403,
        )

    if not 1 <= limit <= COMPLETED_USAGE_LIMIT:
        raise CarHistoryError('INVALID_HISTORY_LIMIT', 'Limit must be between 1 and 50', 422)
    start, end = _parse_datetime(from_datetime), _parse_datetime(to_datetime)
    if start is not None and end is not None and start > end:
        raise CarHistoryError('INVALID_HISTORY_RANGE', 'Start must not be after end', 422)
    rows = get_car_usage_history(
        current_user.family_id,
        completed_limit=limit, cursor=cursor, vehicle_ref=vehicle_ref, member_ref=member_ref,
        from_datetime=start, to_datetime=end,
    )
    if rows is None:
        raise CarHistoryError('INVALID_HISTORY_CURSOR', 'History cursor is unavailable; restart pagination', 422)
    active_usages = []
    recent_usage = []
    for name, started_at, ended_at, is_active, _sort_id, vehicle_name, vehicle_ref, session_ref, member_ref in rows:
        item = {'name': name, 'started_at': started_at, 'vehicle_name': vehicle_name, 'vehicle_ref': vehicle_ref,
                'session_ref': session_ref, 'member_ref': member_ref}
        if is_active:
            active_usages.append(item)
        elif ended_at is not None:
            recent_usage.append({**item, 'ended_at': ended_at})

    has_more = len(recent_usage) > limit
    recent_usage = recent_usage[:limit]
    return {
        "active_usage": active_usages[0] if active_usages else None,
        "active_usages": active_usages,
        "recent_usage": recent_usage,
        "has_more": has_more,
        "next_cursor": recent_usage[-1]['session_ref'] if has_more else None,
    }
