import importlib.util
from dataclasses import replace
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


database_stub = types.ModuleType("database")
database_stub.get_family_profile = Mock()
database_stub.update_family_member_role = Mock()
database_stub.get_family_by_location = Mock()
database_stub.update_family_address = Mock()


def load_service():
    module_path = Path(__file__).resolve().parents[1] / "family_service.py"
    spec = importlib.util.spec_from_file_location("family_service_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    geocoding_stub = types.ModuleType("geocoding_service")
    geocoding_stub.geocode_address = Mock()
    with patch.dict(sys.modules, {
        "database": database_stub,
        "geocoding_service": geocoding_stub,
    }):
        spec.loader.exec_module(module)
    return module


service = load_service()


class FamilyServiceTests(unittest.TestCase):
    def setUp(self):
        service._address_resolutions.clear()
        database_stub.get_family_profile.reset_mock(return_value=True, side_effect=True)
        database_stub.update_family_member_role.reset_mock(return_value=True, side_effect=True)
        database_stub.get_family_by_location.reset_mock(return_value=True, side_effect=True)
        database_stub.update_family_address.reset_mock(return_value=True, side_effect=True)
        database_stub.get_family_profile.return_value = (
            ("כהן", "דימונה, המעפיל, 1209", "482731", 17),
            [
                ("11111111-1111-4111-8111-111111111111", "מיכאל", None, 17),
                ("22222222-2222-4222-8222-222222222222", "נועה", "child", 18),
            ],
        )
        database_stub.update_family_member_role.return_value = (
            "22222222-2222-4222-8222-222222222222",
            "נועה",
            "parent",
            False,
        )
        database_stub.get_family_by_location.return_value = None
        database_stub.update_family_address.return_value = ("דימונה, המעפיל, 1210",)

    def current_user(self, user_id=17, family_id=42):
        return CurrentUser(user_id=user_id, name="מיכאל", family_id=family_id)

    def test_authenticated_family_read_is_scoped_and_contains_no_internal_ids(self):
        response = service.get_family_for_current_user(self.current_user())

        database_stub.get_family_profile.assert_called_once_with(42)
        self.assertEqual(response["name"], "כהן")
        self.assertTrue(response["can_edit_roles"])
        self.assertEqual(response["members"][0].member_ref, "11111111-1111-4111-8111-111111111111")
        self.assertTrue(response["members"][0].is_family_admin)
        serialized = repr(response)
        for prohibited in ("user_id", "family_id", "auth_user_id", "shortcut_token"):
            self.assertNotIn(prohibited, serialized)

    def test_non_creator_is_read_only(self):
        response = service.get_family_for_current_user(self.current_user(user_id=18))
        self.assertFalse(response["can_edit_roles"])

    def test_missing_family_fails_closed(self):
        database_stub.get_family_profile.return_value = None
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.get_family_for_current_user(self.current_user())
        self.assertEqual(raised.exception.status_code, 404)

    def test_null_creator_fails_closed(self):
        database_stub.get_family_profile.return_value = (
            ("כהן", "כתובת", "482731", None),
            [],
        )
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.get_family_for_current_user(self.current_user())
        self.assertEqual(raised.exception.code, "FAMILY_CREATOR_NOT_CONFIGURED")
        self.assertEqual(raised.exception.status_code, 503)

    def test_creator_can_set_parent_child_or_clear_role(self):
        for role in ("parent", "child", None):
            with self.subTest(role=role):
                database_stub.update_family_member_role.reset_mock()
                database_stub.update_family_member_role.return_value = (
                    "22222222-2222-4222-8222-222222222222",
                    "נועה",
                    role,
                    False,
                )
                updated = service.set_family_member_role(
                    self.current_user(),
                    "22222222-2222-4222-8222-222222222222",
                    role,
                )
                self.assertEqual(updated.role, role)
                database_stub.update_family_member_role.assert_called_once_with(
                    17,
                    42,
                    "22222222-2222-4222-8222-222222222222",
                    role,
                )

    def test_non_creator_cannot_update_roles(self):
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.set_family_member_role(
                self.current_user(user_id=18),
                "22222222-2222-4222-8222-222222222222",
                "parent",
            )
        self.assertEqual(raised.exception.status_code, 403)
        database_stub.update_family_member_role.assert_not_called()

    def test_foreign_and_nonexistent_member_use_the_same_not_found_response(self):
        database_stub.update_family_member_role.return_value = None
        responses = []
        for member_ref in ("foreign-reference", "missing-reference"):
            with self.assertRaises(service.FamilyProfileError) as raised:
                service.set_family_member_role(self.current_user(), member_ref, "parent")
            responses.append((raised.exception.code, raised.exception.status_code))
        self.assertEqual(responses, [
            ("FAMILY_MEMBER_NOT_FOUND", 404),
            ("FAMILY_MEMBER_NOT_FOUND", 404),
        ])

    def test_roles_are_never_used_as_authorization(self):
        database_stub.get_family_profile.return_value = (
            ("כהן", "כתובת", "482731", 17),
            [("11111111-1111-4111-8111-111111111111", "מיכאל", "child", 17)],
        )
        response = service.get_family_for_current_user(self.current_user())
        self.assertTrue(response["can_edit_roles"])
        self.assertEqual(response["members"][0].role, "child")

    @patch.object(service, "geocode_address")
    def test_creator_resolves_and_atomically_updates_address(self, geocode):
        geocode.return_value = {
            "address": "המעפיל 1210, דימונה, ישראל",
            "latitude": 31.072,
            "longitude": 35.036,
        }
        resolved = service.resolve_family_address_for_current_user(
            self.current_user(),
            "דימונה, המעפיל, 1210",
        )
        updated = service.update_family_address_for_current_user(
            self.current_user(),
            resolved["resolution_token"],
        )
        self.assertEqual(updated["home_address"], "דימונה, המעפיל, 1210")
        database_stub.update_family_address.assert_called_once_with(
            17, 42, "דימונה, המעפיל, 1210", 31.072, 35.036,
        )

    @patch.object(service, "geocode_address")
    def test_non_creator_cannot_resolve_or_update_address(self, geocode):
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.resolve_family_address_for_current_user(
                self.current_user(user_id=18), "דימונה, המעפיל, 1210",
            )
        self.assertEqual(raised.exception.status_code, 403)
        geocode.assert_not_called()
        database_stub.update_family_address.assert_not_called()

    @patch.object(service, "geocode_address", return_value=None)
    def test_unresolved_address_is_rejected_without_update(self, _geocode):
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.resolve_family_address_for_current_user(
                self.current_user(), "דימונה, המעפיל, 9999",
            )
        self.assertEqual(raised.exception.code, "ADDRESS_NOT_FOUND")
        database_stub.update_family_address.assert_not_called()

    @patch.object(service, "geocode_address")
    def test_address_used_by_another_family_is_rejected_before_update(self, geocode):
        geocode.return_value = {
            "address": "המעפיל 1210, דימונה, ישראל",
            "latitude": 31.072,
            "longitude": 35.036,
        }
        database_stub.get_family_by_location.return_value = (99,)

        with self.assertRaises(service.FamilyProfileError) as raised:
            service.resolve_family_address_for_current_user(
                self.current_user(), "דימונה, המעפיל, 1210",
            )

        self.assertEqual(raised.exception.code, "FAMILY_ALREADY_EXISTS_AT_ADDRESS")
        database_stub.update_family_address.assert_not_called()

    @patch.object(service, "geocode_address")
    def test_failed_authorized_update_preserves_old_address_and_consumes_resolution(self, geocode):
        geocode.return_value = {
            "address": "המעפיל 1210, דימונה, ישראל",
            "latitude": 31.072,
            "longitude": 35.036,
        }
        database_stub.update_family_address.return_value = None
        resolved = service.resolve_family_address_for_current_user(
            self.current_user(), "דימונה, המעפיל, 1210",
        )

        with self.assertRaises(service.FamilyProfileError) as raised:
            service.update_family_address_for_current_user(
                self.current_user(), resolved["resolution_token"],
            )

        self.assertEqual(raised.exception.code, "FAMILY_ADDRESS_FORBIDDEN")
        with self.assertRaises(service.FamilyProfileError) as replay:
            service.update_family_address_for_current_user(
                self.current_user(), resolved["resolution_token"],
            )
        self.assertEqual(replay.exception.code, "ADDRESS_RESOLUTION_EXPIRED")

    @patch.object(service, "geocode_address")
    def test_expired_address_resolution_fails_closed(self, geocode):
        geocode.return_value = {
            "address": "המעפיל 1210, דימונה, ישראל",
            "latitude": 31.072,
            "longitude": 35.036,
        }
        resolved = service.resolve_family_address_for_current_user(
            self.current_user(), "דימונה, המעפיל, 1210",
        )
        token = resolved["resolution_token"]
        service._address_resolutions[token] = replace(
            service._address_resolutions[token],
            expires_at=0,
        )

        with self.assertRaises(service.FamilyProfileError) as raised:
            service.update_family_address_for_current_user(self.current_user(), token)

        self.assertEqual(raised.exception.code, "ADDRESS_RESOLUTION_EXPIRED")
        database_stub.update_family_address.assert_not_called()

    @patch.object(service, "geocode_address")
    def test_stale_or_foreign_resolution_fails_closed(self, geocode):
        geocode.return_value = {
            "address": "המעפיל 1210, דימונה, ישראל",
            "latitude": 31.072,
            "longitude": 35.036,
        }
        resolved = service.resolve_family_address_for_current_user(
            self.current_user(), "דימונה, המעפיל, 1210",
        )
        with self.assertRaises(service.FamilyProfileError) as raised:
            service.update_family_address_for_current_user(
                self.current_user(user_id=99), resolved["resolution_token"],
            )
        self.assertEqual(raised.exception.status_code, 403)
        database_stub.update_family_address.assert_not_called()


if __name__ == "__main__":
    unittest.main()
