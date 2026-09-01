import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


requests_stub = types.ModuleType("requests")
requests_stub.get = Mock()
dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = Mock()


def load_geocoding_service():
    module_path = Path(__file__).resolve().parents[1] / "geocoding_service.py"
    spec = importlib.util.spec_from_file_location(
        "geocoding_service_under_test",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"requests": requests_stub, "dotenv": dotenv_stub},
    ):
        spec.loader.exec_module(module)
    return module


geocoding_service = load_geocoding_service()


def address_component(long_name, short_name, *types_):
    return {
        "long_name": long_name,
        "short_name": short_name,
        "types": list(types_),
    }


def precise_result(latitude=31.0721, longitude=35.0364, **overrides):
    result = {
        "formatted_address": "המעפיל 1209, דימונה, ישראל",
        "types": ["street_address"],
        "partial_match": False,
        "address_components": [
            address_component("1209", "1209", "street_number"),
            address_component("המעפיל", "המעפיל", "route"),
            address_component("דימונה", "דימונה", "locality", "political"),
            address_component("ישראל", "IL", "country", "political"),
        ],
        "geometry": {
            "location": {"lat": latitude, "lng": longitude},
            "location_type": "ROOFTOP",
        },
    }
    result.update(overrides)
    return result


class GeocodingServiceTests(unittest.TestCase):
    def setUp(self):
        self.response = Mock()
        self.response.raise_for_status.return_value = None

    def geocode(self, results, status="OK"):
        self.response.json.return_value = {"status": status, "results": results}
        with (
            patch.object(geocoding_service, "GOOGLE_MAPS_API_KEY", "test-key"),
            patch.object(
                geocoding_service.requests,
                "get",
                return_value=self.response,
            ) as get,
        ):
            value = geocoding_service.geocode_address(
                "דימונה",
                "המעפיל",
                "1209",
            )
        return value, get

    def test_rooftop_street_address_is_accepted_with_israel_bias(self):
        value, get = self.geocode([precise_result()])

        self.assertEqual(value["latitude"], 31.0721)
        self.assertEqual(value["longitude"], 35.0364)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["address"], "המעפיל 1209, דימונה, Israel")
        self.assertEqual(params["language"], "he")
        self.assertEqual(params["region"], "il")
        self.assertEqual(params["components"], "country:IL")
        self.assertEqual(params["key"], "test-key")

    def test_rooftop_premise_with_complete_components_is_accepted(self):
        value, _ = self.geocode([precise_result(types=["premise"])])

        self.assertIsNotNone(value)

    def test_partial_match_is_rejected(self):
        value, _ = self.geocode([precise_result(partial_match=True)])

        self.assertIsNone(value)

    def test_city_or_street_level_result_is_rejected(self):
        for result_type in ("locality", "route"):
            with self.subTest(result_type=result_type):
                value, _ = self.geocode([precise_result(types=[result_type])])
                self.assertIsNone(value)

    def test_non_rooftop_result_is_rejected(self):
        for location_type in (
            "RANGE_INTERPOLATED",
            "GEOMETRIC_CENTER",
            "APPROXIMATE",
        ):
            with self.subTest(location_type=location_type):
                result = precise_result()
                result["geometry"]["location_type"] = location_type
                value, _ = self.geocode([result])
                self.assertIsNone(value)

    def test_mismatched_address_component_is_rejected(self):
        replacements = {
            "street_number": "1210",
            "route": "הרצל",
            "locality": "באר שבע",
            "country": "US",
        }
        for component_type, replacement in replacements.items():
            with self.subTest(component_type=component_type):
                result = precise_result()
                for component in result["address_components"]:
                    if component_type in component["types"]:
                        component["long_name"] = replacement
                        component["short_name"] = replacement
                value, _ = self.geocode([result])
                self.assertIsNone(value)

    def test_component_comparison_normalizes_spacing_and_punctuation(self):
        result = precise_result()
        result["address_components"][1]["long_name"] = "המעפיל-"
        result["address_components"][1]["short_name"] = "המעפיל-"

        value, _ = self.geocode([result])

        self.assertIsNotNone(value)

    def test_result_before_precise_address_does_not_capture_city_coordinates(self):
        city_result = precise_result(
            latitude=31.07127,
            longitude=35.0337,
            types=["locality", "political"],
        )

        value, _ = self.geocode([city_result, precise_result()])

        self.assertEqual(value["latitude"], 31.0721)
        self.assertEqual(value["longitude"], 35.0364)

    def test_distinct_precise_results_are_rejected_as_ambiguous(self):
        value, _ = self.geocode([
            precise_result(),
            precise_result(latitude=31.079, longitude=35.043),
        ])

        self.assertIsNone(value)

    def test_duplicate_nearby_results_are_treated_as_the_same_address(self):
        value, _ = self.geocode([
            precise_result(),
            precise_result(latitude=31.07215, longitude=35.03645),
        ])

        self.assertIsNotNone(value)

    def test_zero_results_returns_none(self):
        value, _ = self.geocode([], status="ZERO_RESULTS")

        self.assertIsNone(value)

    def test_provider_error_status_is_not_treated_as_address_not_found(self):
        with self.assertRaisesRegex(RuntimeError, "REQUEST_DENIED"):
            self.geocode([], status="REQUEST_DENIED")


if __name__ == "__main__":
    unittest.main()
