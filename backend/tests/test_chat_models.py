import unittest

from pydantic import ValidationError

from models import ChatRequest


class ChatRequestValidationTests(unittest.TestCase):
    def test_valid_request_is_trimmed(self):
        request = ChatRequest(
            request_id="0da80a79-74f1-496f-9bd0-dd4ef43d38a7",
            message="  מי עם הרכב?  ",
        )
        self.assertEqual(request.message, "מי עם הרכב?")

    def test_invalid_uuid_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChatRequest(request_id="not-a-uuid", message="test")

    def test_empty_message_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChatRequest(
                request_id="0da80a79-74f1-496f-9bd0-dd4ef43d38a7",
                message="   ",
            )

    def test_message_over_4000_characters_is_rejected(self):
        with self.assertRaises(ValidationError):
            ChatRequest(
                request_id="0da80a79-74f1-496f-9bd0-dd4ef43d38a7",
                message="a" * 4001,
            )

    def test_client_identity_fields_are_rejected(self):
        with self.assertRaises(ValidationError):
            ChatRequest(
                request_id="0da80a79-74f1-496f-9bd0-dd4ef43d38a7",
                message="מי עם הרכב?",
                user_id=999,
                family_id=888,
                auth_user_id="forged",
            )


if __name__ == "__main__":
    unittest.main()
