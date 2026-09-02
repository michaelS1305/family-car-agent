import os
import unicodedata
from math import asin, cos, radians, sin, sqrt

import requests

from dotenv import load_dotenv

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ACCEPTED_RESULT_TYPES = {"street_address", "premise"}
ACCEPTED_LOCATION_TYPES = {"ROOFTOP"}
MAX_EQUIVALENT_RESULT_DISTANCE_METERS = 50


def _distance_meters(first, second):
    first_latitude = radians(first["lat"])
    second_latitude = radians(second["lat"])
    latitude_delta = second_latitude - first_latitude
    longitude_delta = radians(second["lng"] - first["lng"])
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude)
        * cos(second_latitude)
        * sin(longitude_delta / 2) ** 2
    )
    return 6371000 * 2 * asin(sqrt(haversine))


def _normalize_address_component(value):
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _component_values(result, component_types):
    values = set()
    for component in result.get("address_components") or []:
        if set(component.get("types") or []).intersection(component_types):
            for field in ("long_name", "short_name"):
                normalized = _normalize_address_component(component.get(field))
                if normalized:
                    values.add(normalized)
    return values


def _component_matches(result, component_types, expected):
    normalized_expected = _normalize_address_component(expected)
    return bool(normalized_expected) and normalized_expected in _component_values(
        result,
        component_types,
    )


def _is_precise_address_result(result, city, street, house_number):
    geometry = result.get("geometry") or {}
    location = geometry.get("location") or {}
    result_types = set(result.get("types") or [])

    return (
        bool(result_types.intersection(ACCEPTED_RESULT_TYPES))
        and result.get("partial_match") is not True
        and geometry.get("location_type") in ACCEPTED_LOCATION_TYPES
        and isinstance(location.get("lat"), (int, float))
        and isinstance(location.get("lng"), (int, float))
        and _component_matches(result, {"street_number"}, house_number)
        and _component_matches(result, {"route"}, street)
        and _component_matches(
            result,
            {"locality", "postal_town", "sublocality_level_1"},
            city,
        )
        and _component_matches(result, {"country"}, "IL")
    )


def _select_unambiguous_address(results, city, street, house_number):
    precise_results = [
        result
        for result in results
        if _is_precise_address_result(result, city, street, house_number)
    ]
    if not precise_results:
        return None

    first = precise_results[0]
    first_location = first["geometry"]["location"]
    if any(
        _distance_meters(
            first_location,
            candidate["geometry"]["location"],
        )
        > MAX_EQUIVALENT_RESULT_DISTANCE_METERS
        for candidate in precise_results[1:]
    ):
        return None
    return first


def geocode_address(city, street, house_number):
    if not GOOGLE_MAPS_API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")

    address = f"{street} {house_number}, {city}, Israel"

    response = requests.get(
        GOOGLE_GEOCODING_URL,
        params={
            "address": address,
            "language": "he",
            "region": "il",
            "components": "country:IL",
            "key": GOOGLE_MAPS_API_KEY,
        },
        timeout=10,
    )
    response.raise_for_status()

    payload = response.json()
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        return None
    if status != "OK":
        raise RuntimeError(
            f"Google Maps Geocoding failed with status: {status or 'UNKNOWN'}"
        )

    result = _select_unambiguous_address(
        payload.get("results") or [],
        city,
        street,
        house_number,
    )
    if not result:
        return None

    location = result["geometry"]["location"]
    return {
        "address": result.get("formatted_address", address),
        "latitude": location["lat"],
        "longitude": location["lng"],
    }
