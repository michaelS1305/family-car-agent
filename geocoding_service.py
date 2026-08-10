import os
import requests

from dotenv import load_dotenv

load_dotenv()

GEOAPIFY_API_KEY = os.getenv("GEOAPIFY_API_KEY")


def geocode_address(city, street, house_number):
    if not GEOAPIFY_API_KEY:
        raise RuntimeError("GEOAPIFY_API_KEY is not configured")

    address = f"{street} {house_number}, {city}, Israel"

    response = requests.get(
        "https://api.geoapify.com/v1/geocode/search",
        params={
            "text": address,
            "format": "json",
            "limit": 1,
            "apiKey": GEOAPIFY_API_KEY,
        },
        timeout=10,
    )

    response.raise_for_status()

    results = response.json().get("results", [])

    if not results:
        return None

    result = results[0]

    return {
        "address": result.get("formatted", address),
        "latitude": result["lat"],
        "longitude": result["lon"],
    }