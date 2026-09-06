import unittest

from pydantic import ValidationError

from models import PushSubscriptionRemoveRequest, PushSubscriptionRequest


class PushSubscriptionModelTests(unittest.TestCase):
    def test_valid_browser_subscription_is_accepted(self):
        model = PushSubscriptionRequest.model_validate({
            "endpoint": "https://push.example/device",
            "expiration_time": 1_800_000_000_000,
            "keys": {"p256dh": "public-key", "auth": "auth-secret"},
        })
        self.assertEqual(model.endpoint, "https://push.example/device")

    def test_endpoint_must_be_https_and_bounded(self):
        for endpoint in ("http://push.example/device", "not-a-url", "https://x.test/" + "x" * 4096):
            with self.subTest(endpoint=endpoint[:30]):
                with self.assertRaises(ValidationError):
                    PushSubscriptionRemoveRequest.model_validate({"endpoint": endpoint})

    def test_keys_are_required_bounded_and_extra_identity_is_forbidden(self):
        invalid_payloads = (
            {"endpoint": "https://push.example/device", "keys": {"p256dh": "", "auth": "a"}},
            {"endpoint": "https://push.example/device", "keys": {"p256dh": "p", "auth": ""}},
            {"endpoint": "https://push.example/device", "keys": {"p256dh": "p", "auth": "a"}, "user_id": 999},
            {"endpoint": "https://push.example/device", "keys": {"p256dh": "p", "auth": "a", "family_id": 888}},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    PushSubscriptionRequest.model_validate(payload)

    def test_negative_expiration_is_rejected(self):
        for expiration in (-1, 253_402_300_800_000):
            with self.subTest(expiration=expiration):
                with self.assertRaises(ValidationError):
                    PushSubscriptionRequest.model_validate({
                        "endpoint": "https://push.example/device",
                        "expiration_time": expiration,
                        "keys": {"p256dh": "p", "auth": "a"},
                    })


if __name__ == "__main__":
    unittest.main()
