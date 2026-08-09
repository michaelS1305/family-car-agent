from fastapi import FastAPI
from models import CarConnection
from datetime import datetime
from telegram_service import send_telegram_message
from database import conn, insert_car_event, get_latest_event, get_active_driver, init_db
from car_service import connect_user, disconnect_user
from ai_service import understand_message

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
    return disconnect_user(connection.shortcut_token)

@app.get("/car/status")
def get_car_status():
    active_driver = get_active_driver()

    if not active_driver:
        return {
            "status": "available",
            "current_driver": None
        }

    return {
        "status": "in_use",
        "current_driver": active_driver[0]
    }

@app.post("/telegram/webhook")
def telegram_webhook(update: dict):
    message = update.get("message")

    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    intent = understand_message(text)

    if intent == "car_status":
        active_driver = get_active_driver()

        if active_driver:
            reply = f"{active_driver[0]} עם הרכב כרגע 🚗"
        else:
            reply = "הרכב פנוי כרגע 🟢"

        send_telegram_message(chat_id, reply)

    else:
        send_telegram_message(
            chat_id,
            "אני עדיין לא יודע לעזור עם זה 🤖"
        )

    return {"ok": True}