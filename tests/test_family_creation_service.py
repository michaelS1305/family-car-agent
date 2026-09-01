import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


def stub_module(name, **attributes):
    module = types.ModuleType(name)
    for attribute_name, value in attributes.items():
        setattr(module, attribute_name, value)
    return module


class FamilyCodeTakenError(Exception):
    pass


class AuthUserAlreadyMappedError(Exception):
    pass


class AuthUserIdentityNotFoundError(Exception):
    pass


class FamilyAlreadyExistsAtLocationError(Exception):
    pass


database_stub = stub_module(
    "database",
    FamilyCodeTakenError=FamilyCodeTakenError,
    AuthUserAlreadyMappedError=AuthUserAlreadyMappedError,
    AuthUserIdentityNotFoundError=AuthUserIdentityNotFoundError,
    FamilyAlreadyExistsAtLocationError=FamilyAlreadyExistsAtLocationError,
    create_family_with_first_user=Mock(),
    get_family_by_code=Mock(),
    get_family_by_location=Mock(),
    get_user_by_auth_user_id=Mock(),
)
geocoding_stub = stub_module("geocoding_service", geocode_address=Mock())


def load_service_module():
    module_path = Path(__file__).resolve().parents[1] / "family_creation_service.py"
    spec = importlib.util.spec_from_file_location("family_creation_service_test", module_path)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {"database": database_stub, "geocoding_service": geocoding_stub},
    ):
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(spec.name, None)

    return module


service = load_service_module()


class FamilyCreationServiceTests(unittest.TestCase):
    def setUp(self):
        for mocked_function in (
            database_stub.create_family_with_first_user,
            database_stub.get_family_by_code,
            database_stub.get_family_by_location,
            database_stub.get_user_by_auth_user_id,
            geocoding_stub.geocode_address,
        ):
            mocked_function.reset_mock(return_value=True, side_effect=True)

        database_stub.get_user_by_auth_user_id.return_value = None
        database_stub.get_family_by_code.return_value = None
        database_stub.get_family_by_location.return_value = None
        geocoding_stub.geocode_address.return_value = {
            "address": "120 Dizengoff Street, Tel Aviv",
            "latitude": 32.0809,
            "longitude": 34.7806,
        }
        service._address_resolutions.clear()
        service._auth_resolution_tokens.clear()

    def create(self, **overrides):
        values = {
            "auth_user_id": "auth-user-uuid",
            "family_name": " כהן ",
            "family_code": "482731",
            "address_resolution_token": "missing-resolution-token",
            "user_name": " מיכאל ",
        }
        values.update(overrides)
        return service.create_family_for_auth_user(**values)

    def assert_error(self, code, **overrides):
        with self.assertRaises(service.FamilyCreationError) as raised:
            self.create(**overrides)
        self.assertEqual(raised.exception.code, code)

    def resolve_address(self, address="תל אביב, דיזנגוף, 120"):
        return service.resolve_create_family_address("auth-user-uuid", address)

    def test_valid_create_stores_exact_confirmed_resolution_without_regeocoding(self):
        resolved = self.resolve_address()
        geocoding_stub.geocode_address.reset_mock()

        result = self.create(address_resolution_token=resolved.resolution_token)

        self.assertEqual(result, {"created": True})
        geocoding_stub.geocode_address.assert_not_called()
        database_stub.create_family_with_first_user.assert_called_once_with(
            name="כהן",
            family_code="482731",
            home_address="תל אביב, דיזנגוף, 120",
            user_name="מיכאל",
            shortcut_token=None,
            telegram_chat_id=None,
            home_latitude=32.0809,
            home_longitude=34.7806,
            auth_user_id="auth-user-uuid",
            prevent_duplicate_location=True,
        )

    def test_invalid_family_code(self):
        self.assert_error("INVALID_FAMILY_CODE", family_code="12345")
        geocoding_stub.geocode_address.assert_not_called()

    def test_numeric_family_and_personal_names_are_rejected(self):
        self.assert_error("INVALID_FAMILY_NAME", family_name="111")
        self.assert_error("INVALID_FAMILY_NAME", family_name="Family1")
        self.assert_error("INVALID_USER_NAME", user_name="111")
        self.assert_error("INVALID_USER_NAME", user_name="Michael1")

    def test_english_and_separated_names_remain_valid(self):
        resolved = self.resolve_address()
        self.create(
            family_name="Smith-Jones",
            user_name="O'Connor",
            address_resolution_token=resolved.resolution_token,
        )
        database_stub.create_family_with_first_user.assert_called_once()

    def test_hebrew_family_name_with_trailing_apostrophe_remains_valid(self):
        resolved = self.resolve_address()
        self.create(
            family_name="סנדרוביץ'",
            user_name="מיכאל",
            address_resolution_token=resolved.resolution_token,
        )
        self.assertEqual(
            database_stub.create_family_with_first_user.call_args.kwargs["name"],
            "סנדרוביץ'",
        )

    def test_duplicate_family_code(self):
        database_stub.get_family_by_code.return_value = (7, "כהן")
        self.assert_error("FAMILY_CODE_TAKEN")

    def test_invalid_address_format(self):
        with self.assertRaises(service.FamilyCreationError) as raised:
            self.resolve_address("תל אביב")
        self.assertEqual(raised.exception.code, "INVALID_ADDRESS_FORMAT")
        geocoding_stub.geocode_address.assert_not_called()

    def test_address_not_found(self):
        geocoding_stub.geocode_address.return_value = None
        with self.assertRaises(service.FamilyCreationError) as raised:
            self.resolve_address()
        self.assertEqual(raised.exception.code, "ADDRESS_NOT_FOUND")

    def test_duplicate_family_near_address(self):
        database_stub.get_family_by_location.return_value = (9, "לוי")
        with self.assertRaises(service.FamilyCreationError) as raised:
            self.resolve_address()
        self.assertEqual(raised.exception.code, "FAMILY_ALREADY_EXISTS_AT_ADDRESS")

    def test_auth_user_already_mapped(self):
        database_stub.get_user_by_auth_user_id.return_value = (17, "מיכאל", 42)
        self.assert_error("AUTH_USER_ALREADY_MAPPED")
        geocoding_stub.geocode_address.assert_not_called()

    def test_atomic_race_errors_are_mapped_to_structured_codes(self):
        database_stub.create_family_with_first_user.side_effect = FamilyCodeTakenError()
        resolved = self.resolve_address()
        self.assert_error(
            "FAMILY_CODE_TAKEN",
            address_resolution_token=resolved.resolution_token,
        )

    def test_missing_auth_user_becomes_structured_session_error(self):
        resolved = self.resolve_address()
        database_stub.create_family_with_first_user.side_effect = (
            AuthUserIdentityNotFoundError()
        )

        with self.assertRaises(service.FamilyCreationError) as raised:
            self.create(address_resolution_token=resolved.resolution_token)

        self.assertEqual(raised.exception.code, "AUTH_SESSION_INVALID")
        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn(resolved.resolution_token, service._address_resolutions)

    def test_address_resolution_returns_no_coordinates_to_api_contract_layer(self):
        resolved = service.resolve_create_family_address(
            "auth-user-uuid",
            "תל אביב, דיזנגוף, 120",
        )

        self.assertEqual(resolved.normalized_address, "תל אביב, דיזנגוף, 120")
        self.assertEqual(resolved.display_address, "120 Dizengoff Street, Tel Aviv")
        self.assertIsInstance(resolved.resolution_token, str)
        self.assertGreater(len(resolved.resolution_token), 20)

    def test_resolution_token_is_bound_to_authenticated_user(self):
        resolved = self.resolve_address()

        with self.assertRaises(service.FamilyCreationError) as raised:
            service.create_family_for_auth_user(
                auth_user_id="different-auth-user",
                family_name="כהן",
                family_code="482731",
                address_resolution_token=resolved.resolution_token,
                user_name="מיכאל",
            )

        self.assertEqual(raised.exception.code, "ADDRESS_RESOLUTION_EXPIRED")
        database_stub.create_family_with_first_user.assert_not_called()

    def test_resolution_token_is_discarded_only_after_success(self):
        resolved = self.resolve_address()

        self.create(address_resolution_token=resolved.resolution_token)

        with self.assertRaises(service.FamilyCreationError) as raised:
            self.create(address_resolution_token=resolved.resolution_token)
        self.assertEqual(raised.exception.code, "ADDRESS_RESOLUTION_EXPIRED")

    def test_expired_resolution_requires_address_confirmation_again(self):
        with patch.object(service.time, "monotonic", return_value=100):
            resolved = self.resolve_address()

        with patch.object(
            service.time,
            "monotonic",
            return_value=100 + service.ADDRESS_RESOLUTION_TTL_SECONDS + 1,
        ):
            with self.assertRaises(service.FamilyCreationError) as raised:
                self.create(address_resolution_token=resolved.resolution_token)

        self.assertEqual(raised.exception.code, "ADDRESS_RESOLUTION_EXPIRED")
        database_stub.create_family_with_first_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
