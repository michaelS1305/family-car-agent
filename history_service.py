from database import get_car_usage_history
from identity import CurrentUser


COMPLETED_USAGE_LIMIT = 50


class CarHistoryError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def get_car_history(current_user: CurrentUser):
    if current_user.family_id is None:
        raise CarHistoryError(
            "USER_WITHOUT_FAMILY",
            "The mapped user does not belong to a family",
            403,
        )

    rows = get_car_usage_history(
        current_user.family_id,
        completed_limit=COMPLETED_USAGE_LIMIT,
    )
    active_usage = None
    recent_usage = []
    for name, started_at, ended_at, is_active, _sort_id in rows:
        if is_active:
            active_usage = {"name": name, "started_at": started_at}
        elif ended_at is not None:
            recent_usage.append({
                "name": name,
                "started_at": started_at,
                "ended_at": ended_at,
            })

    return {
        "active_usage": active_usage,
        "recent_usage": recent_usage,
    }
