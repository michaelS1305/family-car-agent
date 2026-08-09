from database import get_active_driver, insert_car_event, get_user_by_token
from telegram_service import send_telegram_message

def connect_user(shortcut_token):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    active_driver = get_active_driver()

    if active_driver:
        if active_driver[0] == user[1]:
            return {
                "message": "User is already the current driver",
                "current_driver": active_driver[0]
            }

        # Handover: close previous driver's active session
        insert_car_event(active_driver[0], "disconnected")

    result = insert_car_event(user[1], "connected")

    send_telegram_message(
        user[2],
        f"{user[1]} took the car 🚗"
    )

    return result

def disconnect_user(shortcut_token):
    user = get_user_by_token(shortcut_token)

    if not user:
        return {
            "message": "Invalid shortcut token"
        }

    active_driver = get_active_driver()

    if not active_driver:
        return {
            "message": "Car is already available"
        }

    if active_driver[0] != user[1]:
        return {
            "message": "Only the current driver can disconnect",
            "current_driver": active_driver[0]
        }

    result = insert_car_event(user[1], "disconnected")

    send_telegram_message(
        user[2],
        "The car is now available 🟢"
    )

    return result