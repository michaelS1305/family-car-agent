import os
from google import genai
from telegram_service import send_confirmation_message
from database import (
    get_active_driver,
    get_last_driver,
    get_recent_events,
    create_reservation,
    get_user_reservations,
    cancel_reservation,
    update_reservation
)
from datetime import datetime
from zoneinfo import ZoneInfo

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def understand_message(text):
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"""
You are an AI assistant for a family shared car.

Classify the user's intent.

Available intents:
- car_status
- unknown

User message:
{text}

Return ONLY the intent name.
"""
    )

    return response.text.strip()


def get_car_status_tool():
    active_driver = get_active_driver()

    if active_driver:
        return {
            "status": "in_use",
            "current_driver": active_driver[0]
        }

    return {
        "status": "available",
        "current_driver": None
    }


def get_last_driver_tool():
    event = get_last_driver()

    if not event:
        return {
            "driver": None,
            "status": None,
            "event_time": None
        }

    return {
        "driver": event[0],
        "status": event[1],
        "event_time": event[2]
    }

def get_recent_events_tool():
    events = get_recent_events()

    return [
        {
            "driver": event[0],
            "status": event[1],
            "event_time": event[2]
        }
        for event in events
    ]

def create_reservation_tool(
    user_id: int,
    start_time: str,
    end_time: str
):
    """Reserve the family car for a user for a specific time range."""
    return create_reservation(
        user_id,
        start_time,
        end_time
    )

def get_user_reservations_tool(user_id: int):
    reservations = get_user_reservations(user_id)

    return [
        {
            "reservation_id": reservation[0],
            "start_time": reservation[1],
            "end_time": reservation[2],
            "status": reservation[3]
        }
        for reservation in reservations
    ]

def cancel_reservation_tool(
    reservation_id: int,
    user_id: int
):
    """Cancel one of the current user's reservations."""
    return cancel_reservation(
        reservation_id,
        user_id
    )

def update_reservation_tool(
    reservation_id: int,
    user_id: int,
    start_time: str,
    end_time: str
):
    """Update the time range of one of the current user's reservations."""
    return update_reservation(
        reservation_id,
        user_id,
        start_time,
        end_time
    )


def ask_agent(text, user_id, user_name, chat_id):
    now = datetime.now(ZoneInfo("Asia/Jerusalem"))

    def request_cancel_reservation_tool(reservation_id: int):
        """Request confirmation before cancelling a reservation."""

        send_confirmation_message(
            chat_id=chat_id,
            text="האם אתה בטוח שאתה רוצה לבטל את ההזמנה?",
            confirm_data=f"cancel_reservation:{reservation_id}",
            cancel_data="dismiss"
        )

        return {
            "success": True,
            "message": "Confirmation request sent to the user."
        }

    def request_update_reservation_tool(
        reservation_id: int,
        start_time: str,
        end_time: str
    ):
        """Request confirmation before updating a reservation."""

        send_confirmation_message(
            chat_id=chat_id,
            text=f"האם לעדכן את ההזמנה ל-{start_time} עד {end_time}?",
            confirm_data=f"update_reservation|{reservation_id}|{start_time}|{end_time}",
            cancel_data="dismiss"
        )

        return {
            "success": True,
            "message": "Confirmation request sent to the user."
        }

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"""
Current date and time: {now.isoformat()}

Current user:
- user_id: {user_id}
- name: {user_name}

User message:
{text}
""",
        config={
            "system_instruction": """
You are a family shared-car assistant.

Your job is ONLY to help family members manage and get information about their shared car.

GENERAL RULES:
- Reply in the same language as the user.
- Keep answers short, clear, and natural.
- Use the available tools whenever factual information is required.
- Never invent car status, drivers, reservations, times, or history.
- Never claim an action succeeded unless the relevant tool returned success.
- If a request is outside the available capabilities, say briefly that it is not supported yet.

CAR STATUS:
- Use get_car_status_tool when the user asks who has the car or whether it is currently available.
- Use get_last_driver_tool for questions about the most recent driver or event.
- Use get_recent_events_tool for questions about recent car usage or history.

RESERVATIONS:
- Use get_user_reservations_tool when the user asks about their existing reservations.
- Use create_reservation_tool to create a reservation.
- Always use the current user's user_id when creating, modifying, or cancelling reservations.
- Interpret relative dates such as today, tomorrow, tonight, and next week using the current date and time supplied in the user context.
- Never create a reservation unless both start_time and end_time are clearly known.
- If only one required time is missing, ask only for that missing information.
- Never invent a missing date or time.
- If create_reservation_tool reports a conflict, do not create the reservation and clearly tell the user that the requested time is already reserved.

MODIFYING RESERVATIONS:
- When the user wants to change a reservation, first use get_user_reservations_tool to identify the relevant reservation.
- If multiple reservations could match, ask which reservation they mean.
- If exactly one reservation clearly matches, determine the requested new start_time and end_time.
- If required information is missing, ask only for the missing information.
- Use request_update_reservation_tool to ask the user for confirmation.
- Never use update_reservation_tool directly from a normal user message.
- A reservation is only actually updated after the user presses the Telegram confirmation button.
- Never modify another user's reservation.

CANCELLING RESERVATIONS:
- When the user wants to cancel a reservation, first use get_user_reservations_tool to identify the relevant reservation.
- If exactly one reservation clearly matches, use request_cancel_reservation_tool to request confirmation.
- If multiple reservations could match, ask which reservation they mean.
- Never use cancel_reservation_tool directly from a normal user message.
- A reservation is only actually cancelled after the user presses the Telegram confirmation button.
- Never cancel another user's reservation.

IMPORTANT:
- A reservation and the car's current status are different things.
- Do not say the car is currently unavailable just because it has a future reservation.
- Do not create, modify, or cancel reservations merely because the user is discussing or asking about them.
""",
            "tools": [
                get_car_status_tool,
                get_last_driver_tool,
                get_recent_events_tool,
                create_reservation_tool,
                get_user_reservations_tool,
                request_cancel_reservation_tool,
                request_update_reservation_tool
            ]
        }
    )

    return response.text