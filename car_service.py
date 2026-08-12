from database import (
    get_active_driver,
    insert_car_event,
    get_user_by_token,
    get_family_by_id,
    get_users_by_family_id,
)
from telegram_service import send_telegram_message
from math import radians, sin, cos, sqrt, atan2


def notify_family(family_id, message):
    family_users = get_users_by_family_id(family_id)

    for family_user in family_users:
        telegram_chat_id = family_user[2]

        if telegram_chat_id is not None:
            send_telegram_message(
                telegram_chat_id,
                message
            )


def connect_user(shortcut_token):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    family_id = user[3]

    if family_id is None:
        return {
            "message": "User family not found"
        }

    active_driver = get_active_driver(family_id)

    if active_driver:
        active_driver_name = active_driver[0]
        active_driver_user_id = active_driver[1]

        if active_driver_user_id == user[0]:
            return {
                "message": "User is already the current driver",
                "current_driver": active_driver_name
            }

        # Handover: close the previous driver's active session.
        insert_car_event(
            active_driver_user_id,
            active_driver_name,
            "disconnected",
            family_id
        )

    result = insert_car_event(
        user[0],
        user[1],
        "connected",
        family_id
    )

    notify_family(
        family_id,
        f"{user[1]} לקח/ה את הרכב 🚗"
    )

    return result


def disconnect_user(shortcut_token, latitude=None, longitude=None):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    family_id = user[3]

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

    family = get_family_by_id(family_id)

    if not family:
        return {
            "message": "Family not found"
        }

    home_latitude = family[3]
    home_longitude = family[4]

    if home_latitude is None or home_longitude is None:
        return {
            "message": "Home location is not configured"
        }

    distance = calculate_distance_meters(
        latitude,
        longitude,
        home_latitude,
        home_longitude
    )

    if distance > 500:
        return {
            "message": "הרכב לא שוחרר כי הוא לא נמצא ליד הבית",
            "distance_from_home": round(distance)
        }

    result = insert_car_event(
        user[0],
        user[1],
        "disconnected",
        family_id
    )

    notify_family(
        family_id,
        "הרכב פנוי עכשיו 🟢"
    )

    return {
        "message": "הרכב שוחרר בהצלחה",
        "distance_from_home": round(distance),
        "result": result
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