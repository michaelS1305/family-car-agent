from fastapi import FastAPI
from models import CarConnection
from onboarding_service import handle_onboarding
from telegram_service import send_telegram_message
from database import (
    init_db,
    get_user_by_telegram_chat_id,
    get_onboarding_session,
)
from car_service import connect_user, disconnect_user
from ai_service import ask_agent

app = FastAPI()

init_db()


@app.get("/")
def home():
    return {"message": "Family Car Agent is running"}


@app.post("/car/connect")
def connect_car(connection: CarConnection):
    return connect_user(connection.shortcut_token)


@app.post("/car/disconnect")
def disconnect_car(connection: CarConnection):
    return disconnect_user(
        connection.shortcut_token,
        connection.latitude,
        connection.longitude,
    )


@app.post("/telegram/webhook")
def telegram_webhook(update: dict):
    message = update.get("message")

    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    user = get_user_by_telegram_chat_id(chat_id)
    onboarding_session = get_onboarding_session(chat_id)

    # If the user is not registered yet,
    # or still has an active onboarding session,
    # continue onboarding.
    if not user or onboarding_session:
        reply = handle_onboarding(
            chat_id=chat_id,
            text=text,
        )

        if reply:
            send_telegram_message(chat_id, reply)

        return {"ok": True}

    try:
        reply = ask_agent(
            text,
            user_id=user[0],
            user_name=user[1],
            chat_id=chat_id,
            family_id=user[3],
        )

        send_telegram_message(chat_id, reply)

    except Exception:
        send_telegram_message(
            chat_id,
            "אני לא זמין כרגע, נסה שוב בעוד כמה דקות.",
        )

    return {"ok": True}