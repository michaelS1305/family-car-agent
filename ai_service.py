import os
from google import genai

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