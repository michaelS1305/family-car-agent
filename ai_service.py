import os
from google import genai
from database import get_active_driver

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

def understand_message(text):
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
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


def ask_agent(text):
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=text,
        config={
            "tools": [get_car_status_tool]
        }
    )

    return response.text