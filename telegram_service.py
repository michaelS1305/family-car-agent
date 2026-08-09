import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text
        }
    )

    return response.json()

def send_confirmation_message(chat_id, text, confirm_data, cancel_data):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ אישור",
                        "callback_data": confirm_data
                    },
                    {
                        "text": "❌ ביטול",
                        "callback_data": cancel_data
                    }
                ]
            ]
        }
    }

    response = requests.post(url, json=payload)
    return response.json()