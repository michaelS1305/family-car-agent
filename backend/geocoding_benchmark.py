"""One-off forward-geocoding benchmark for multiple providers.

API credentials are read only from process environment variables:

- GEOAPIFY_API_KEY
- GOOGLE_MAPS_API_KEY
- TOMTOM_API_KEY
- MAPBOX_ACCESS_TOKEN

The script never writes credentials or provider responses to disk.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable


DEFAULT_TIMEOUT_SECONDS = 20


@dataclass
class BenchmarkResult:
    provider: str
    status: str
    formatted_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    result_type: str | None = None
    precision: str | None = None
    confidence: Any = None
    distance_from_truth_meters: float | None = None
    provider_status: str | None = None
    error: str | None = None


def _distance_meters(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    radius_meters = 6_371_000
    first_latitude_radians = math.radians(first_latitude)
    second_latitude_radians = math.radians(second_latitude)
    latitude_delta = math.radians(second_latitude - first_latitude)
    longitude_delta = math.radians(second_longitude - first_longitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude_radians)
        * math.cos(second_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return radius_meters * 2 * math.atan2(
        math.sqrt(haversine), math.sqrt(1 - haversine)
    )


def _request_json(
    base_url: str,
    parameters: dict[str, Any],
    timeout_seconds: int,
) -> tuple[int, dict[str, Any]]:
    query = urllib.parse.urlencode(parameters)
    request = urllib.request.Request(
        f"{base_url}?{query}",
        headers={"User-Agent": "family-car-agent-geocoding-benchmark/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def _finish_result(
    result: BenchmarkResult,
    truth: tuple[float, float] | None,
) -> BenchmarkResult:
    if truth is not None and result.latitude is not None and result.longitude is not None:
        result.distance_from_truth_meters = round(
            _distance_meters(
                result.latitude,
                result.longitude,
                truth[0],
                truth[1],
            ),
            1,
        )
    return result


def _skipped(provider: str, environment_variable: str) -> BenchmarkResult:
    return BenchmarkResult(
        provider=provider,
        status="skipped",
        provider_status="credential_not_configured",
        error=f"Missing environment variable: {environment_variable}",
    )


def _failed(provider: str, error: Exception) -> BenchmarkResult:
    if isinstance(error, urllib.error.HTTPError):
        provider_status = f"HTTP {error.code}"
    elif isinstance(error, urllib.error.URLError):
        provider_status = "network_error"
    else:
        provider_status = type(error).__name__
    return BenchmarkResult(
        provider=provider,
        status="error",
        provider_status=provider_status,
        error=str(error)[:300],
    )


def benchmark_geoapify(
    address: str,
    truth: tuple[float, float] | None,
    country_code: str,
    language: str,
    timeout_seconds: int,
) -> BenchmarkResult:
    provider = "Geoapify"
    api_key = os.getenv("GEOAPIFY_API_KEY")
    if not api_key:
        return _skipped(provider, "GEOAPIFY_API_KEY")
    try:
        http_status, payload = _request_json(
            "https://api.geoapify.com/v1/geocode/search",
            {
                "text": address,
                "lang": language,
                "filter": f"countrycode:{country_code.lower()}",
                "format": "json",
                "limit": 5,
                "apiKey": api_key,
            },
            timeout_seconds,
        )
        results = payload.get("results") or []
        if not results:
            return BenchmarkResult(
                provider=provider,
                status="no_result",
                provider_status=f"HTTP {http_status}; results=0",
            )
        best = results[0]
        rank = best.get("rank") or {}
        return _finish_result(
            BenchmarkResult(
                provider=provider,
                status="ok",
                formatted_address=best.get("formatted"),
                latitude=best.get("lat"),
                longitude=best.get("lon"),
                result_type=best.get("result_type"),
                precision=rank.get("match_type"),
                confidence={
                    key: rank.get(key)
                    for key in (
                        "confidence",
                        "confidence_city_level",
                        "confidence_street_level",
                        "confidence_building_level",
                    )
                    if rank.get(key) is not None
                },
                provider_status=f"HTTP {http_status}; results={len(results)}",
            ),
            truth,
        )
    except Exception as error:
        return _failed(provider, error)


def benchmark_google(
    address: str,
    truth: tuple[float, float] | None,
    country_code: str,
    language: str,
    timeout_seconds: int,
) -> BenchmarkResult:
    provider = "Google Maps Geocoding"
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return _skipped(provider, "GOOGLE_MAPS_API_KEY")
    try:
        http_status, payload = _request_json(
            "https://maps.googleapis.com/maps/api/geocode/json",
            {
                "address": address,
                "language": language,
                "region": country_code.lower(),
                "components": f"country:{country_code.upper()}",
                "key": api_key,
            },
            timeout_seconds,
        )
        provider_status = payload.get("status") or f"HTTP {http_status}"
        results = payload.get("results") or []
        if provider_status != "OK" or not results:
            return BenchmarkResult(
                provider=provider,
                status="no_result" if not results else "error",
                provider_status=str(provider_status),
                error=payload.get("error_message"),
            )
        best = results[0]
        geometry = best.get("geometry") or {}
        location = geometry.get("location") or {}
        return _finish_result(
            BenchmarkResult(
                provider=provider,
                status="ok",
                formatted_address=best.get("formatted_address"),
                latitude=location.get("lat"),
                longitude=location.get("lng"),
                result_type=", ".join(best.get("types") or []) or None,
                precision=geometry.get("location_type"),
                confidence={"partial_match": bool(best.get("partial_match", False))},
                provider_status=f"{provider_status}; results={len(results)}",
            ),
            truth,
        )
    except Exception as error:
        return _failed(provider, error)


def benchmark_tomtom(
    address: str,
    truth: tuple[float, float] | None,
    country_code: str,
    language: str,
    timeout_seconds: int,
) -> BenchmarkResult:
    provider = "TomTom"
    api_key = os.getenv("TOMTOM_API_KEY")
    if not api_key:
        return _skipped(provider, "TOMTOM_API_KEY")
    try:
        encoded_address = urllib.parse.quote(address, safe="")
        http_status, payload = _request_json(
            f"https://api.tomtom.com/search/2/geocode/{encoded_address}.json",
            {
                "key": api_key,
                "limit": 5,
                "countrySet": country_code.upper(),
                "language": f"{language}-{country_code.upper()}",
            },
            timeout_seconds,
        )
        results = payload.get("results") or []
        if not results:
            return BenchmarkResult(
                provider=provider,
                status="no_result",
                provider_status=f"HTTP {http_status}; results=0",
            )
        best = results[0]
        position = best.get("position") or {}
        address_details = best.get("address") or {}
        match_confidence = best.get("matchConfidence") or {}
        return _finish_result(
            BenchmarkResult(
                provider=provider,
                status="ok",
                formatted_address=address_details.get("freeformAddress"),
                latitude=position.get("lat"),
                longitude=position.get("lon"),
                result_type=best.get("type"),
                precision=(best.get("entityType") or address_details.get("municipality")),
                confidence={
                    "score": best.get("score"),
                    "match_confidence": match_confidence.get("score"),
                },
                provider_status=f"HTTP {http_status}; results={len(results)}",
            ),
            truth,
        )
    except Exception as error:
        return _failed(provider, error)


def benchmark_mapbox(
    address: str,
    truth: tuple[float, float] | None,
    country_code: str,
    language: str,
    timeout_seconds: int,
) -> BenchmarkResult:
    provider = "Mapbox"
    access_token = os.getenv("MAPBOX_ACCESS_TOKEN")
    if not access_token:
        return _skipped(provider, "MAPBOX_ACCESS_TOKEN")
    try:
        http_status, payload = _request_json(
            "https://api.mapbox.com/search/geocode/v6/forward",
            {
                "q": address,
                "access_token": access_token,
                "country": country_code.lower(),
                "language": language,
                "limit": 5,
                "autocomplete": "false",
            },
            timeout_seconds,
        )
        features = payload.get("features") or []
        if not features:
            return BenchmarkResult(
                provider=provider,
                status="no_result",
                provider_status=f"HTTP {http_status}; results=0",
            )
        best = features[0]
        properties = best.get("properties") or {}
        coordinates = (best.get("geometry") or {}).get("coordinates") or []
        match_code = properties.get("match_code") or {}
        return _finish_result(
            BenchmarkResult(
                provider=provider,
                status="ok",
                formatted_address=(
                    properties.get("full_address")
                    or properties.get("place_formatted")
                    or properties.get("name")
                ),
                latitude=coordinates[1] if len(coordinates) >= 2 else None,
                longitude=coordinates[0] if len(coordinates) >= 2 else None,
                result_type=properties.get("feature_type"),
                precision=properties.get("coordinate_accuracy"),
                confidence={
                    "match_code": match_code,
                    "relevance": properties.get("relevance"),
                },
                provider_status=f"HTTP {http_status}; results={len(features)}",
            ),
            truth,
        )
    except Exception as error:
        return _failed(provider, error)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare one address across four geocoding providers."
    )
    parser.add_argument("address", help="Address to geocode")
    parser.add_argument("--truth-lat", type=float, help="Known latitude")
    parser.add_argument("--truth-lon", type=float, help="Known longitude")
    parser.add_argument("--country-code", default="IL", help="ISO country code")
    parser.add_argument("--language", default="he", help="Result language")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-provider timeout in seconds",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if (arguments.truth_lat is None) != (arguments.truth_lon is None):
        print("--truth-lat and --truth-lon must be provided together", file=sys.stderr)
        return 2

    truth = None
    if arguments.truth_lat is not None:
        truth = (arguments.truth_lat, arguments.truth_lon)

    providers: tuple[Callable[..., BenchmarkResult], ...] = (
        benchmark_geoapify,
        benchmark_google,
        benchmark_tomtom,
        benchmark_mapbox,
    )
    results = [
        provider(
            arguments.address,
            truth,
            arguments.country_code,
            arguments.language,
            arguments.timeout,
        )
        for provider in providers
    ]

    output = {
        "query": {
            "address": arguments.address,
            "truth_latitude": truth[0] if truth else None,
            "truth_longitude": truth[1] if truth else None,
            "country_code": arguments.country_code,
            "language": arguments.language,
        },
        "providers": [asdict(result) for result in results],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
