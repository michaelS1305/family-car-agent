from fastapi import FastAPI
from models import CarConnection
from datetime import datetime
from telegram_service import send_telegram_message, send_telegram_message
from database import (conn,  
                      get_active_driver, 
                      init_db, 
                      get_user_by_telegram_chat_id,
                      cancel_reservation,
                      update_reservation)
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
    callback = update.get("callback_query")

    if callback:
        chat_id = callback["message"]["chat"]["id"]
        data = callback["data"]

        user = get_user_by_telegram_chat_id(chat_id)

        if not user:
            send_telegram_message(
                chat_id,
                "המשתמש הזה עדיין לא רשום במערכת."
            )
            return {"ok": True}

        # Cancel reservation
        if data.startswith("cancel_reservation:"):
            reservation_id = int(data.split(":")[1])

            result = cancel_reservation(
                reservation_id,
                user[0]
            )

            if result["success"]:
                send_telegram_message(
                    chat_id,
                    "ההזמנה בוטלה ✅"
                )
            else:
                send_telegram_message(
                    chat_id,
                    result["message"]
                )

        # Update reservation
        elif data.startswith("update_reservation|"):
            _, reservation_id, start_time, end_time = data.split("|")

            result = update_reservation(
                int(reservation_id),
                user[0],
                start_time,
                end_time
            )

            if result["success"]:
                send_telegram_message(
                    chat_id,
                    "ההזמנה עודכנה ✅"
                )
            else:
                send_telegram_message(
                    chat_id,
                    result["message"]
                )

        # User rejected the confirmation
        elif data == "dismiss":
            send_telegram_message(
                chat_id,
                "לא ביצעתי שום שינוי."
            )

        return {"ok": True}

    message = update.get("message")

    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    user = get_user_by_telegram_chat_id(chat_id)

    if not user:
        send_telegram_message(
            chat_id,
            "המשתמש הזה עדיין לא רשום במערכת."
        )
        return {"ok": True}

    try:
        reply = ask_agent(
            text,
            user_id=user[0],
            user_name=user[1],
            chat_id=chat_id
        )

        send_telegram_message(chat_id, reply)

    except Exception as e:
            send_telegram_message(
                chat_id,
                f"Error: {str(e)}"
            )

    return {"ok": True}