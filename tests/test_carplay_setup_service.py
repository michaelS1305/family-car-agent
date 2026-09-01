import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


class UserNotFoundError(Exception):
    pass


database_stub = types.ModuleType("database")
database_stub.UserNotFoundError = UserNotFoundError
database_stub.get_or_create_shortcut_token = Mock(return_value="connection-code")
database_stub.set_carplay_setup_status = Mock(return_value="completed")


def load_service():
    path = Path(__file__).resolve().parents[1] / "carplay_setup_service.py"
    spec = importlib.util.spec_from_file_location("carplay_setup_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub}):
        spec.loader.exec_module(module)
    return module


service = load_service()


class CarPlaySetupServiceTests(unittest.TestCase):
    def setUp(self):
        database_stub.get_or_create_shortcut_token.reset_mock(
            return_value=True,
            side_effect=True,
        )
        database_stub.get_or_create_shortcut_token.return_value = "connection-code"
        database_stub.set_carplay_setup_status.reset_mock(
            return_value=True,
            side_effect=True,
        )
        database_stub.set_carplay_setup_status.return_value = "completed"

    def test_returns_existing_or_created_code_and_exact_shortcut_links(self):
        result = service.prepare_carplay_setup(
            CurrentUser(user_id=17, name="מיכאל", family_id=42)
        )

        database_stub.get_or_create_shortcut_token.assert_called_once_with(17)
        self.assertEqual(result.connection_code, "connection-code")
        self.assertEqual(
            result.connect_shortcut_url,
            "https://www.icloud.com/shortcuts/7a4ba428c6464f95894564e0f20e6f76",
        )
        self.assertEqual(
            result.disconnect_shortcut_url,
            "https://www.icloud.com/shortcuts/825de2b3834640f4888b9e265454e22b",
        )

    def test_requires_a_family_mapping(self):
        with self.assertRaises(service.CarPlaySetupError) as raised:
            service.prepare_carplay_setup(
                CurrentUser(user_id=17, name="מיכאל", family_id=None)
            )
        self.assertEqual(raised.exception.code, "CARPLAY_SETUP_UNAVAILABLE")
        database_stub.get_or_create_shortcut_token.assert_not_called()

    def test_missing_internal_user_is_structured(self):
        database_stub.get_or_create_shortcut_token.side_effect = UserNotFoundError()
        with self.assertRaises(service.CarPlaySetupError) as raised:
            service.prepare_carplay_setup(
                CurrentUser(user_id=17, name="מיכאל", family_id=42)
            )
        self.assertEqual(raised.exception.code, "AUTH_USER_NOT_FOUND")

    def test_updates_only_an_allowed_server_side_status_for_current_user(self):
        current_user = CurrentUser(user_id=17, name="מיכאל", family_id=42)

        result = service.update_carplay_setup_status(current_user, "completed")

        self.assertEqual(result, "completed")
        database_stub.set_carplay_setup_status.assert_called_once_with(17, "completed")

    def test_rejects_an_unknown_status_before_database_access(self):
        with self.assertRaises(service.CarPlaySetupError) as raised:
            service.update_carplay_setup_status(
                CurrentUser(user_id=17, name="מיכאל", family_id=42),
                "anything-else",
            )

        self.assertEqual(raised.exception.code, "INVALID_CARPLAY_SETUP_STATUS")
        self.assertEqual(raised.exception.status_code, 422)
        database_stub.set_carplay_setup_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
