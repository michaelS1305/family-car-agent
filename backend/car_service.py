from database import (
    CarTransitionBusyError,
    admit_car_transition_request,
    apply_carplay_transition,
    get_active_driver,
    get_user_by_token,
    get_family_by_id,
)
from math import radians, sin, cos, sqrt, atan2, isfinite, ceil

from identity import CurrentUser
from push_service import dispatch_car_transition_notification
from vehicle_identity import VehicleIdentityError
from psycopg.errors import LockNotAvailable, QueryCanceled
from vehicle_work import AdmissionDeadlineExceeded


class CarStatusError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CarTransitionError(Exception):
    def __init__(self, code, message, status_code, retry_after_seconds):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = max(1, ceil(retry_after_seconds))


def _admit_transition(user_id, family_id):
    admission = admit_car_transition_request(user_id, family_id)
    if admission["admitted"]:
        return
    message = (
        "בוצעו יותר מדי פעולות. נסו שוב בעוד מעט."
        if admission["code"] == "CARPLAY_USER_RATE_LIMITED"
        else "בוצעו יותר מדי פעולות במשפחה. נסו שוב בעוד מעט."
    )
    raise CarTransitionError(
        admission["code"],
        message,
        429,
        admission["retry_after_seconds"],
    )


def _transition_busy_error():
    return CarTransitionError(
        "CARPLAY_TRANSITION_BUSY",
        "מתבצעת כעת פעולה אחרת ברכב. נסו שוב.",
        409,
        1,
    )


def get_car_status(current_user: CurrentUser):
    if current_user.family_id is None:
        raise CarStatusError(
            "USER_WITHOUT_FAMILY",
            "The mapped user does not belong to a family",
            403,
        )

    return "occupied" if get_active_driver(current_user.family_id) else "available"


def _apply(shortcut_token, acquisition_id, *, disconnect=False):
    try:
        result, event_id, event_time = apply_carplay_transition(
            shortcut_token, acquisition_id, disconnect=disconnect)
    except VehicleIdentityError as error:
        raise CarTransitionError(error.code, error.message, error.status_code, 1) from error
    except (CarTransitionBusyError, LockNotAvailable, QueryCanceled, AdmissionDeadlineExceeded) as error:
        raise _transition_busy_error() from error
    if result.kind not in ('accepted', 'retry') or result.admission_outcome != 'accepted':
        raise CarTransitionError('CARPLAY_EVENT_REJECTED',
                                 'לא ניתן להשלים את הפעולה בבטחה.', 409, 1)
    return result, event_id, event_time


def connect_user(shortcut_token, acquisition_id):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    family_id = user[2]

    if family_id is None:
        return {
            "message": "User family not found"
        }

    _admit_transition(user[0], family_id)
    result, event_id, event_time = _apply(shortcut_token, acquisition_id)
    if result.transition != 'opened':
        return {
            "message": "הפעולה כבר טופלה",
        }

    dispatch_car_transition_notification(
        family_id=family_id,
        actor_user_id=user[0],
        actor_name=user[1],
        event_id=event_id,
        transition="connected",
    )
    return {
        "message": "Car connected",
        "user": user[1],
        "event_time": event_time,
    }


def _valid_coordinates(latitude, longitude):
    try:
        return (
            isfinite(latitude) and isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180
        )
    except (TypeError, ValueError, OverflowError):
        return False


def disconnect_user(shortcut_token, latitude=None, longitude=None, *, acquisition_id):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    family_id = user[2]

    if family_id is None:
        return {
            "message": "User family not found"
        }

    if latitude is None or longitude is None:
        return {
            "message": "Location is required"
        }

    if not _valid_coordinates(latitude, longitude):
        return {"message": "Invalid location"}

    family = get_family_by_id(family_id)

    if not family:
        return {
            "message": "Family not found"
        }

    home_latitude = family[3]
    home_longitude = family[4]

    if not _valid_coordinates(home_latitude, home_longitude):
        return {
            "message": "Home location is not configured"
        }

    try:
        distance = calculate_distance_meters(
            latitude, longitude, home_latitude, home_longitude
        )
        if not isfinite(distance):
            return {"message": "Unable to validate location"}
    except (ValueError, OverflowError, TypeError):
        return {"message": "Unable to validate location"}

    if distance > 500:
        return {
            "message": "הרכב לא שוחרר כי הוא לא נמצא ליד הבית"
        }

    _admit_transition(user[0], family_id)
    result, event_id, event_time = _apply(shortcut_token, acquisition_id, disconnect=True)
    if result.transition != 'returned':
        return {"message": "הפעולה כבר טופלה"}

    dispatch_car_transition_notification(
        family_id=family_id,
        actor_user_id=user[0],
        actor_name=user[1],
        event_id=event_id,
        transition="disconnected",
    )

    return {
        "message": "הרכב שוחרר בהצלחה",
        "result": {
            "message": "Car disconnected",
            "user": user[1],
            "event_time": event_time,
        },
    }


def calculate_distance_meters(lat1, lon1, lat2, lon2):
    earth_radius = 6371000

    lat1 = radians(lat1)
    lon1 = radians(lon1)
    lat2 = radians(lat2)
    lon2 = radians(lon2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return earth_radius * c
