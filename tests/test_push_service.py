import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from identity import CurrentUser


class OwnershipError(Exception):
    pass


def load_push_service():
    database_stub = types.ModuleType("database")
    database_stub.PushSubscriptionOwnershipError = OwnershipError
    database_stub.get_family_push_subscriptions = Mock(return_value=[])
    database_stub.remove_dead_push_subscription = Mock()
    database_stub.remove_push_subscription = Mock()
    database_stub.upsert_push_subscription = Mock(return_value=1)
    path = Path(__file__).resolve().parents[1] / "push_service.py"
    spec = importlib.util.spec_from_file_location("push_service_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"database": database_stub}):
        spec.loader.exec_module(module)
    return module, database_stub


class PushServiceTests(unittest.TestCase):
    def setUp(self):
        self.service, self.database = load_push_service()
        self.user = CurrentUser(user_id=7, name="מיכאל", family_id=42)
        self.subscription = types.SimpleNamespace(
            endpoint="https://push.example/subscription",
            expiration_time=None,
            keys=types.SimpleNamespace(p256dh="public-key", auth="auth-secret"),
        )
        self.environment = {
            "WEB_PUSH_ENABLED": "true",
            "VAPID_PUBLIC_KEY": "public-vapid-key",
            "VAPID_PRIVATE_KEY": "private-vapid-key",
            "VAPID_SUBJECT": "mailto:push@example.test",
        }

    def test_disabled_config_is_safe_and_contains_no_private_key(self):
        with patch.dict(os.environ, {}, clear=True):
            result = self.service.get_public_push_config(self.user)
        self.assertEqual(result, {"enabled": False, "public_vapid_key": None})
        self.assertNotIn("private", json.dumps(result))

    def test_enabled_config_returns_only_public_key(self):
        with patch.dict(os.environ, self.environment, clear=True):
            result = self.service.get_public_push_config(self.user)
        self.assertEqual(result, {"enabled": True, "public_vapid_key": "public-vapid-key"})
        self.assertNotIn("private-vapid-key", json.dumps(result))

    def test_user_without_family_fails_closed(self):
        user = CurrentUser(user_id=7, name="מיכאל", family_id=None)
        with self.assertRaises(self.service.PushServiceError) as raised:
            self.service.get_public_push_config(user)
        self.assertEqual(raised.exception.code, "USER_WITHOUT_FAMILY")

    def test_invalid_vapid_subject_fails_closed(self):
        invalid = {**self.environment, "VAPID_SUBJECT": "https://"}
        with patch.dict(os.environ, invalid, clear=True):
            with self.assertRaises(self.service.PushServiceError) as raised:
                self.service.get_public_push_config(self.user)
        self.assertEqual(raised.exception.code, "PUSH_CONFIGURATION_INVALID")

    def test_registration_uses_only_current_user_identity(self):
        with patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(
                self.service.register_push_subscription(self.user, self.subscription),
                {"registered": True},
            )
        self.database.upsert_push_subscription.assert_called_once_with(
            7,
            "https://push.example/subscription",
            "public-key",
            "auth-secret",
            None,
        )

    def test_cross_user_endpoint_conflict_is_safe(self):
        self.database.upsert_push_subscription.side_effect = OwnershipError()
        with patch.dict(os.environ, self.environment, clear=True):
            with self.assertRaises(self.service.PushServiceError) as raised:
                self.service.register_push_subscription(self.user, self.subscription)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "PUSH_SUBSCRIPTION_OWNED_BY_ANOTHER_USER")

    def test_remove_is_idempotently_scoped_to_current_user(self):
        result = self.service.unregister_push_subscription(
            self.user, "https://push.example/subscription"
        )
        self.assertEqual(result, {"removed": True})
        self.database.remove_push_subscription.assert_called_once_with(
            7, "https://push.example/subscription"
        )

    def test_actor_is_excluded_by_family_scoped_lookup_and_other_devices_receive(self):
        self.database.get_family_push_subscriptions.return_value = [
            {
                "id": 11,
                "endpoint": "https://push.example/mother-phone",
                "p256dh": "p1",
                "auth": "a1",
                "updated_at": "snapshot",
            },
            {
                "id": 12,
                "endpoint": "https://push.example/mother-desktop",
                "p256dh": "p2",
                "auth": "a2",
                "updated_at": "snapshot",
            },
        ]
        sender = Mock()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            self.service, "_webpush", sender
        ):
            self.service.dispatch_car_transition_notification(
                family_id=42,
                actor_user_id=7,
                actor_name="מיכאל",
                event_id=81,
                transition="connected",
            )
        self.database.get_family_push_subscriptions.assert_called_once_with(42, 7)
        self.assertEqual(sender.call_count, 2)
        payload = sender.call_args.args[1]
        self.assertEqual(payload["body"], "מיכאל לקח את הרכב")
        self.assertEqual(payload["tag"], "car-event-81")

    def test_disconnect_copy_is_deterministic(self):
        self.database.get_family_push_subscriptions.return_value = [
            {"id": 11, "endpoint": "https://push.example/one", "p256dh": "p", "auth": "a", "updated_at": "s"}
        ]
        sender = Mock()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            self.service, "_webpush", sender
        ):
            self.service.dispatch_car_transition_notification(
                family_id=42,
                actor_user_id=7,
                actor_name="מיכאל",
                event_id=82,
                transition="disconnected",
            )
        self.assertEqual(sender.call_args.args[1]["body"], "הרכב התפנה")

    def test_one_provider_failure_does_not_stop_other_subscriptions(self):
        subscriptions = [
            {"id": 1, "endpoint": "https://push.example/one", "p256dh": "p1", "auth": "a1", "updated_at": "s1"},
            {"id": 2, "endpoint": "https://push.example/two", "p256dh": "p2", "auth": "a2", "updated_at": "s2"},
        ]
        self.database.get_family_push_subscriptions.return_value = subscriptions
        sender = Mock(side_effect=[RuntimeError("provider down"), None])
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            self.service, "_webpush", sender
        ):
            self.service.dispatch_car_transition_notification(
                family_id=42, actor_user_id=7, actor_name="מיכאל",
                event_id=83, transition="connected",
            )
        self.assertEqual(sender.call_count, 2)
        self.database.remove_dead_push_subscription.assert_not_called()

    def test_only_404_and_410_remove_snapshot_subscription(self):
        subscription = {
            "id": 1, "endpoint": "https://push.example/dead", "p256dh": "p",
            "auth": "a", "updated_at": "snapshot",
        }
        self.database.get_family_push_subscriptions.return_value = [subscription]
        for status in (404, 410, 429, 500, 401, 400):
            with self.subTest(status=status):
                self.database.remove_dead_push_subscription.reset_mock()
                error = RuntimeError("send failed")
                error.response = types.SimpleNamespace(status_code=status)
                with patch.dict(os.environ, self.environment, clear=True), patch.object(
                    self.service, "_webpush", side_effect=error
                ):
                    self.service.dispatch_car_transition_notification(
                        family_id=42, actor_user_id=7, actor_name="מיכאל",
                        event_id=84, transition="connected",
                    )
                if status in {404, 410}:
                    self.database.remove_dead_push_subscription.assert_called_once_with(subscription)
                else:
                    self.database.remove_dead_push_subscription.assert_not_called()

    def test_disabled_dispatch_has_no_database_or_provider_side_effect(self):
        with patch.dict(os.environ, {"WEB_PUSH_ENABLED": "false"}, clear=True), patch.object(
            self.service, "_webpush"
        ) as sender:
            self.service.dispatch_car_transition_notification(
                family_id=42, actor_user_id=7, actor_name="מיכאל",
                event_id=85, transition="connected",
            )
        self.database.get_family_push_subscriptions.assert_not_called()
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
