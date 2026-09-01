from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class FakeAuthUserAlreadyMappedError(Exception):
    pass


class FakeInvalidJoinStepError(Exception):
    pass


class FakeJoinSessionLockedError(Exception):
    def __init__(self, locked_until):
        self.locked_until = locked_until


database_stub = types.ModuleType("database")
database_stub.AuthUserAlreadyMappedError = FakeAuthUserAlreadyMappedError
database_stub.InvalidJoinStepError = FakeInvalidJoinStepError
database_stub.JoinSessionLockedError = FakeJoinSessionLockedError

for function_name in (
    "complete_pwa_join",
    "confirm_pwa_join_address",
    "record_pwa_join_failure",
    "start_pwa_join_session",
    "submit_pwa_join_address",
    "submit_pwa_join_family_name",
    "verify_pwa_join_family_code",
):
    setattr(database_stub, function_name, Mock())

geocoding_stub = types.ModuleType("geocoding_service")
geocoding_stub.geocode_address = Mock()


def load_service():
    module_path = Path(__file__).resolve().parents[1] / "join_family_service.py"
    spec = importlib.util.spec_from_file_location("join_family_service_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "database": database_stub,
            "geocoding_service": geocoding_stub,
        },
    ):
        spec.loader.exec_module(module)
    return module


service = load_service()


def session(step="family_name", **overrides):
    value = {
        "auth_user_id": "auth-user-uuid",
        "step": step,
        "family_name": None,
        "family_id": None,
        "normalized_address": None,
        "resolved_address": None,
        "family_name_attempts": 0,
        "address_attempts": 0,
        "family_code_attempts": 0,
        "locked_until": None,
        "was_reset": False,
    }
    value.update(overrides)
    return value


class JoinFamilyServiceTests(unittest.TestCase):
    def setUp(self):
        for name in dir(database_stub):
            value = getattr(database_stub, name)
            if isinstance(value, Mock):
                value.reset_mock(return_value=True, side_effect=True)
        geocoding_stub.geocode_address.reset_mock(return_value=True, side_effect=True)

    def test_start_returns_no_internal_identity_or_family_id(self):
        database_stub.start_pwa_join_session.return_value = session()

        result = service.start_join_family("auth-user-uuid")

        self.assertNotIn("auth_user_id", result)
        self.assertNotIn("family_id", result)
        self.assertEqual(result["attempts_remaining"]["family_name"], 3)

    def test_family_name_failure_includes_server_attempts(self):
        database_stub.submit_pwa_join_family_name.return_value = {
            "success": False,
            "attempts_remaining": 2,
            "locked_until": None,
            "session": session(family_name_attempts=1),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_name("auth-user-uuid", "לא קיימת")

        self.assertEqual(raised.exception.code, "JOIN_FAMILY_NAME_NOT_FOUND")
        self.assertEqual(raised.exception.attempts_remaining, 2)
        self.assertIn("נותרו 2 ניסיונות", raised.exception.message)

    def test_invalid_family_name_is_rejected_and_uses_server_attempt_counter(self):
        database_stub.record_pwa_join_failure.return_value = {
            "success": False,
            "attempts_remaining": 2,
            "locked_until": None,
            "session": session(family_name_attempts=1),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_name("auth-user-uuid", "111")

        self.assertEqual(raised.exception.code, "INVALID_FAMILY_NAME")
        self.assertEqual(raised.exception.status_code, 400)
        database_stub.submit_pwa_join_family_name.assert_not_called()
        database_stub.record_pwa_join_failure.assert_called_once_with(
            "auth-user-uuid",
            "family_name",
            ("family_name", "address", "address_confirmed", "family_code"),
        )

    def test_family_name_with_trailing_apostrophe_reaches_database_lookup(self):
        database_stub.submit_pwa_join_family_name.return_value = {
            "success": True,
            "session": session(step="address", family_name="סנדרוביץ'"),
        }

        result = service.submit_join_family_name(
            "auth-user-uuid",
            "סנדרוביץ'",
        )

        self.assertEqual(result["family_name"], "סנדרוביץ'")
        database_stub.submit_pwa_join_family_name.assert_called_once_with(
            "auth-user-uuid",
            "סנדרוביץ'",
        )

    def test_third_failure_returns_lock_metadata_and_warning(self):
        locked_until = datetime(2026, 8, 30, 12, 15, tzinfo=timezone.utc)
        database_stub.verify_pwa_join_family_code.return_value = {
            "success": False,
            "attempts_remaining": 0,
            "locked_until": locked_until,
            "session": session(
                step="locked",
                family_code_attempts=3,
                locked_until=locked_until,
            ),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_code("auth-user-uuid", "123456")

        self.assertEqual(raised.exception.code, "JOIN_LOCKED")
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.detail()["locked_until"], locked_until.isoformat())
        self.assertIn("בדקו את הפרטים", raised.exception.message)

    def test_invalid_address_counts_without_geocoding(self):
        database_stub.record_pwa_join_failure.return_value = {
            "success": False,
            "attempts_remaining": 1,
            "locked_until": None,
            "session": session(step="address", address_attempts=2),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_address("auth-user-uuid", "כתובת לא מלאה")

        geocoding_stub.geocode_address.assert_not_called()
        database_stub.record_pwa_join_failure.assert_called_once_with(
            "auth-user-uuid",
            "address",
            ("address", "address_confirmed", "family_code"),
        )
        self.assertEqual(raised.exception.attempts_remaining, 1)
        self.assertIn("ניסיון אחרון", raised.exception.message)

    def test_valid_address_is_geocoded_and_family_id_is_not_returned(self):
        geocoding_stub.geocode_address.return_value = {
            "address": "120 Dizengoff Street, Tel Aviv",
            "latitude": 32.0809,
            "longitude": 34.7806,
        }
        database_stub.submit_pwa_join_address.return_value = {
            "success": True,
            "session": session(
                step="address_confirmed",
                family_name="כהן",
                family_id=7,
                normalized_address="תל אביב, דיזנגוף, 120",
                resolved_address="120 Dizengoff Street, Tel Aviv",
            ),
        }

        result = service.submit_join_family_address(
            "auth-user-uuid",
            "תל אביב, דיזנגוף, 120",
        )

        self.assertEqual(result["step"], "address_confirmed")
        self.assertNotIn("family_id", result)
        database_stub.submit_pwa_join_address.assert_called_once_with(
            "auth-user-uuid",
            "תל אביב, דיזנגוף, 120",
            "120 Dizengoff Street, Tel Aviv",
            32.0809,
            34.7806,
        )

    def test_near_address_is_accepted_when_fifty_meter_match_succeeds(self):
        geocoding_stub.geocode_address.return_value = {
            "address": "הרצל 10, דימונה, ישראל",
            "latitude": 31.06903,
            "longitude": 35.03302,
        }
        database_stub.submit_pwa_join_address.return_value = {
            "success": True,
            "session": session(
                step="address_confirmed",
                family_name="כהן",
                family_id=7,
                normalized_address="דימונה, הרצל, 10",
                resolved_address="הרצל 10, דימונה, ישראל",
            ),
        }

        result = service.submit_join_family_address(
            "auth-user-uuid",
            "דימונה, הרצל, 10",
        )

        self.assertEqual(result["step"], "address_confirmed")
        database_stub.submit_pwa_join_address.assert_called_once_with(
            "auth-user-uuid",
            "דימונה, הרצל, 10",
            "הרצל 10, דימונה, ישראל",
            31.06903,
            35.03302,
        )

    def test_different_street_in_same_city_is_rejected_by_distance_match(self):
        geocoding_stub.geocode_address.return_value = {
            "address": "רחוב אחר 20, דימונה, ישראל",
            "latitude": 31.078,
            "longitude": 35.041,
        }
        database_stub.submit_pwa_join_address.return_value = {
            "success": False,
            "attempts_remaining": 2,
            "locked_until": None,
            "session": session(step="address", address_attempts=1),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_address("auth-user-uuid", "דימונה, רחוב אחר, 20")

        self.assertEqual(raised.exception.code, "JOIN_FAMILY_ADDRESS_NOT_FOUND")
        self.assertEqual(raised.exception.attempts_remaining, 2)

    def test_different_city_is_rejected_by_distance_match(self):
        geocoding_stub.geocode_address.return_value = {
            "address": "הרצל 10, באר שבע, ישראל",
            "latitude": 31.252,
            "longitude": 34.791,
        }
        database_stub.submit_pwa_join_address.return_value = {
            "success": False,
            "attempts_remaining": 1,
            "locked_until": None,
            "session": session(step="address", address_attempts=2),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_address("auth-user-uuid", "באר שבע, הרצל, 10")

        self.assertEqual(raised.exception.code, "JOIN_FAMILY_ADDRESS_NOT_FOUND")

    def test_coarse_or_ambiguous_geocode_is_rejected_before_location_match(self):
        geocoding_stub.geocode_address.return_value = None
        database_stub.record_pwa_join_failure.return_value = {
            "success": False,
            "attempts_remaining": 2,
            "locked_until": None,
            "session": session(step="address", address_attempts=1),
        }

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.submit_join_family_address("auth-user-uuid", "דימונה, רחוב לא ברור, 10")

        self.assertEqual(raised.exception.code, "JOIN_FAMILY_ADDRESS_NOT_FOUND")
        database_stub.submit_pwa_join_address.assert_not_called()

    def test_complete_uses_only_verified_auth_identity_and_name(self):
        database_stub.complete_pwa_join.return_value = {
            "created": True,
            "user_id": 17,
            "family_id": 7,
        }

        result = service.complete_join_family("verified-auth-user", " מיכאל ")

        self.assertTrue(result["created"])
        database_stub.complete_pwa_join.assert_called_once_with(
            "verified-auth-user",
            "מיכאל",
        )

    def test_complete_rejects_numeric_names_without_database_write(self):
        for value in ("111", "Michael1"):
            with self.subTest(value=value):
                with self.assertRaises(service.JoinFamilyError) as raised:
                    service.complete_join_family("verified-auth-user", value)
                self.assertEqual(raised.exception.code, "INVALID_USER_NAME")
        database_stub.complete_pwa_join.assert_not_called()

    def test_complete_translates_concurrent_mapping_to_idempotent_error_code(self):
        database_stub.complete_pwa_join.side_effect = FakeAuthUserAlreadyMappedError()

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.complete_join_family("verified-auth-user", "מיכאל")

        self.assertEqual(raised.exception.code, "AUTH_USER_ALREADY_MAPPED")
        self.assertEqual(raised.exception.status_code, 409)

    def test_active_lock_is_translated_to_structured_error(self):
        locked_until = datetime(2026, 8, 30, 12, 15, tzinfo=timezone.utc)
        database_stub.start_pwa_join_session.side_effect = FakeJoinSessionLockedError(
            locked_until
        )

        with self.assertRaises(service.JoinFamilyError) as raised:
            service.start_join_family("auth-user-uuid")

        self.assertEqual(raised.exception.code, "JOIN_LOCKED")
        self.assertEqual(raised.exception.detail()["locked_until"], locked_until.isoformat())


if __name__ == "__main__":
    unittest.main()
