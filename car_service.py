from database import (
    connect_car_atomically,
    disconnect_car_atomically,
    get_active_driver,
    get_user_by_token,
    get_family_by_id,
)
from math import radians, sin, cos, sqrt, atan2, isfinite

from identity import CurrentUser
from push_service import dispatch_car_transition_notification


class CarStatusError(Exception):
    def __init__(self, code, message, status_code):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def get_car_status(current_user: CurrentUser):
    if current_user.family_id is None:
        raise CarStatusError(
            "USER_WITHOUT_FAMILY",
            "The mapped user does not belong to a family",
            403,
        )

    return "occupied" if get_active_driver(current_user.family_id) else "available"


def connect_user(shortcut_token):
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

    transition = connect_car_atomically(user[0], user[1], family_id)
    if transition["transition"] == "none":
        return {
            "message": "User is already the current driver",
            "current_driver": transition["current_driver"],
        }

    dispatch_car_transition_notification(
        family_id=family_id,
        actor_user_id=user[0],
        actor_name=user[1],
        event_id=transition["event_id"],
        transition="connected",
    )
    return {
        "message": "Car connected",
        "user": user[1],
        "event_time": transition["event_time"],
    }


def _valid_coordinates(latitude, longitude):
    try:
        return (
            isfinite(latitude) and isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180
        )
    except (TypeError, ValueError, OverflowError):
        return False


def disconnect_user(shortcut_token, latitude=None, longitude=None):
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

    active_driver = get_active_driver(family_id)

    if not active_driver:
        return {
            "message": "הרכב כבר פנוי"
        }

    active_driver_name = active_driver[0]
    active_driver_user_id = active_driver[1]

    if active_driver_user_id != user[0]:
        return {
            "message": "Only the current driver can disconnect",
            "current_driver": active_driver_name
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

    transition = disconnect_car_atomically(user[0], family_id)
    if transition["transition"] == "none":
        if transition["reason"] == "already_available":
            return {"message": "הרכב כבר פנוי"}
        if transition["reason"] == "different_driver":
            return {
                "message": "Only the current driver can disconnect",
                "current_driver": transition["current_driver"],
            }
        return {"message": "הרכב לא התפנה"}

    dispatch_car_transition_notification(
        family_id=family_id,
        actor_user_id=user[0],
        actor_name=user[1],
        event_id=transition["event_id"],
        transition="disconnected",
    )

    return {
        "message": "הרכב שוחרר בהצלחה",
        "result": {
            "message": "Car disconnected",
            "user": user[1],
            "event_time": transition["event_time"],
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
