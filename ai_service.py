import os
from google import genai
from database import (
    get_active_driver,
    get_last_driver,
    get_recent_events,
    create_reservation,
    get_user_reservations,
    cancel_reservation,
    update_reservation,
    save_conversation_message,
    get_recent_conversation
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

    # Load recent conversation BEFORE saving the current message
    recent_messages = get_recent_conversation(user_id, limit=10)

    conversation_history = "\n".join(
        f"{role}: {content}"
        for role, content in recent_messages
    )

    # Save current user message
    save_conversation_message(
        user_id=user_id,
        role="user",
        content=text
    )

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=f"""
Current date and time: {now.isoformat()}

Current user:
- user_id: {user_id}
- name: {user_name}

Recent conversation:
{conversation_history}

Current user message:
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

CONVERSATION CONTEXT:
- Use the recent conversation to understand short follow-up messages such as "yes", "no", "until 21", "that one", or "change it".
- When the assistant previously asked the user to confirm a specific reservation change or cancellation, a clear affirmative response such as "yes", "כן", "yep", or similar counts as confirmation for that exact action.
- Never treat an unrelated "yes" as confirmation.
- If the conversation context is not clear enough, ask a short clarification question instead of guessing.

CAR STATUS:
- Use get_car_status_tool when the user asks who has the car or whether it is currently available.
- Use get_last_driver_tool for questions about the most recent driver or event.
- Use get_recent_events_tool for questions about recent car usage or history.

RESERVATIONS:
- Use get_user_reservations_tool when the user asks about their reservations.
- Use create_reservation_tool to create a reservation.
- Always use the current user's user_id.
- Interpret relative dates such as today, tomorrow and tonight using the current date and time provided.
- Never create a reservation unless both start_time and end_time are known.
- If information is missing, ask only for the missing information.
- Never invent missing dates or times.
- If a requested time conflicts with an existing reservation, explain that the car is already reserved.

MODIFYING RESERVATIONS:
- First use get_user_reservations_tool to identify the relevant reservation.
- Never modify another user's reservation.
- If multiple reservations could match, ask which one the user means.
- Before modifying a reservation, clearly state the exact old reservation and the exact requested new reservation and ask for confirmation.
- Only after a clear confirmation in the current conversation context, use update_reservation_tool.
- If update_reservation_tool succeeds, clearly state the final reservation details.
- If it fails, clearly explain why and confirm that the original reservation was not changed.

CANCELLING RESERVATIONS:
- First use get_user_reservations_tool to identify the relevant reservation.
- Never cancel another user's reservation.
- If multiple reservations could match, ask which one the user means.
- Before cancelling, clearly state the exact reservation and ask for confirmation.
- Only after a clear confirmation in the current conversation context, use cancel_reservation_tool.
- If cancellation succeeds, clearly state which reservation was cancelled.
- If it fails, clearly explain why.

IMPORTANT:
- A reservation and the current car status are different things.
- A future reservation does not mean the car is currently unavailable.
- Never change data just because the user is asking a question about it.
""",
            "tools": [
                get_car_status_tool,
                get_last_driver_tool,
                get_recent_events_tool,
                create_reservation_tool,
                get_user_reservations_tool,
                cancel_reservation_tool,
                update_reservation_tool
            ]
        }
    )

    reply = response.text

    # Save assistant response
    save_conversation_message(
        user_id=user_id,
        role="assistant",
        content=reply
    )

    return reply