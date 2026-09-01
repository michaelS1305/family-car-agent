import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch


DATABASE_FUNCTIONS = (
    "create_family",
    "create_family_with_first_user",
    "get_family_by_code",
    "get_family_by_name_and_location",
    "get_family_by_location",
    "insert_user",
    "generate_shortcut_token",
    "get_onboarding_session",
    "save_onboarding_session",
    "delete_onboarding_session",
)


def build_stub_module(module_name, function_names):
    module = types.ModuleType(module_name)
    for function_name in function_names:
        setattr(module, function_name, Mock(name=function_name))
    return module


database_stub = build_stub_module("database", DATABASE_FUNCTIONS)
geocoding_stub = build_stub_module("geocoding_service", ("geocode_address",))
telegram_stub = build_stub_module("telegram_service", ("send_telegram_message",))

with patch.dict(
    sys.modules,
    {
        "database": database_stub,
        "geocoding_service": geocoding_stub,
        "telegram_service": telegram_stub,
    },
):
    onboarding_service = importlib.import_module("onboarding_service")


class TelegramOnboardingFamilyCodeTests(unittest.TestCase):
    def setUp(self):
        for function_name in DATABASE_FUNCTIONS:
            getattr(database_stub, function_name).reset_mock(return_value=True)

    def test_create_rejects_invalid_code_without_querying_or_advancing(self):
        database_stub.get_onboarding_session.return_value = (
            "create_family_code",
            json.dumps({"family_name": "כהן"}),
        )

        response = onboarding_service.handle_onboarding(101, "12345")

        self.assertEqual(
            response,
            "הקוד המשפחתי חייב להכיל בדיוק 6 ספרות.\nלדוגמה: 482731",
        )
        database_stub.get_family_by_code.assert_not_called()
        database_stub.save_onboarding_session.assert_not_called()

    def test_create_accepts_trimmed_valid_code_and_advances_as_before(self):
        database_stub.get_onboarding_session.return_value = (
            "create_family_code",
            json.dumps({"family_name": "כהן"}),
        )
        database_stub.get_family_by_code.return_value = None

        response = onboarding_service.handle_onboarding(101, " 482731 ")

        database_stub.get_family_by_code.assert_called_once_with("482731")
        args, kwargs = database_stub.save_onboarding_session.call_args
        self.assertEqual(args, (101,))
        self.assertEqual(kwargs["step"], "create_family_address")
        self.assertEqual(
            json.loads(kwargs["data"]),
            {"family_name": "כהן", "family_code": "482731"},
        )
        self.assertIn("מה כתובת הבית של המשפחה?", response)

    def test_join_invalid_code_keeps_existing_attempt_behavior(self):
        database_stub.get_onboarding_session.return_value = (
            "join_verify_family_code",
            json.dumps({"family_id": 7, "family_name": "כהן", "code_attempts": 0}),
        )

        response = onboarding_service.handle_onboarding(202, "not-a-code")

        database_stub.get_family_by_code.assert_not_called()
        args, kwargs = database_stub.save_onboarding_session.call_args
        self.assertEqual(args, (202,))
        self.assertEqual(kwargs["step"], "join_verify_family_code")
        self.assertEqual(json.loads(kwargs["data"])["code_attempts"], 1)
        self.assertEqual(response, "הקוד שהוזן אינו נכון ❌\n\nנותרו לך 2 ניסיונות.")

    def test_join_valid_code_advances_to_name_step_as_before(self):
        database_stub.get_onboarding_session.return_value = (
            "join_verify_family_code",
            json.dumps({"family_id": 7, "family_name": "כהן", "code_attempts": 0}),
        )
        database_stub.get_family_by_code.return_value = (7, "כהן")

        response = onboarding_service.handle_onboarding(202, " 482731 ")

        database_stub.get_family_by_code.assert_called_once_with("482731")
        database_stub.save_onboarding_session.assert_called_once()
        args, kwargs = database_stub.save_onboarding_session.call_args
        self.assertEqual(args, (202,))
        self.assertEqual(kwargs["step"], "join_user_name")
        self.assertEqual(response, "הקוד נכון ✅\nמה השם שלך?")


class TelegramOnboardingFamilyCreationTests(unittest.TestCase):
    def setUp(self):
        for function_name in DATABASE_FUNCTIONS:
            getattr(database_stub, function_name).reset_mock(return_value=True)

        telegram_stub.send_telegram_message.reset_mock(return_value=True)

    def test_create_user_step_uses_atomic_operation_and_keeps_response(self):
        database_stub.get_onboarding_session.return_value = (
            "create_user_name",
            json.dumps(
                {
                    "family_name": "כהן",
                    "family_code": "482731",
                    "home_address": "תל אביב, דיזנגוף, 120",
                    "home_latitude": 32.0809,
                    "home_longitude": 34.7806,
                }
            ),
        )
        database_stub.generate_shortcut_token.return_value = "shortcut-token"
        database_stub.create_family_with_first_user.return_value = 7

        response = onboarding_service.handle_onboarding(303, " מיכאל ")

        database_stub.create_family_with_first_user.assert_called_once_with(
            name="כהן",
            family_code="482731",
            home_address="תל אביב, דיזנגוף, 120",
            user_name="מיכאל",
            shortcut_token="shortcut-token",
            telegram_chat_id=303,
            home_latitude=32.0809,
            home_longitude=34.7806,
        )
        database_stub.create_family.assert_not_called()
        database_stub.insert_user.assert_not_called()
        database_stub.save_onboarding_session.assert_called_once_with(
            303,
            step="waiting_for_shortcuts_install",
        )
        self.assertIn("נרשמת בהצלחה ✅", response)
        self.assertIn("משפחה: כהן", response)
        self.assertIn("שם: מיכאל", response)


if __name__ == "__main__":
    unittest.main()
