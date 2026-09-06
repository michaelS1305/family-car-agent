import unittest
from unittest.mock import Mock

from tests.test_database_atomic_creation import RecordingContext, database


class PushSubscriptionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.original_pool = database.pool
        self.pool = Mock()
        self.connection = Mock()
        self.pool.connection.return_value = RecordingContext(self.connection)
        database.pool = self.pool

    def tearDown(self):
        database.pool = self.original_pool

    def test_upsert_is_idempotent_only_for_the_same_owner(self):
        cursor = Mock()
        cursor.fetchone.return_value = (91,)
        self.connection.execute.return_value = cursor

        result = database.upsert_push_subscription(
            7, "https://push.example/device", "p256dh", "auth", None
        )

        self.assertEqual(result, 91)
        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("ON CONFLICT (endpoint) DO UPDATE", sql)
        self.assertIn("WHERE push_subscriptions.user_id = EXCLUDED.user_id", sql)
        self.assertEqual(parameters[:4], (7, "https://push.example/device", "p256dh", "auth"))

    def test_endpoint_owned_by_another_user_is_not_transferred(self):
        cursor = Mock()
        cursor.fetchone.return_value = None
        self.connection.execute.return_value = cursor

        with self.assertRaises(database.PushSubscriptionOwnershipError):
            database.upsert_push_subscription(
                7, "https://push.example/foreign", "p256dh", "auth", None
            )

    def test_one_user_can_register_multiple_endpoint_rows(self):
        first = Mock()
        first.fetchone.return_value = (1,)
        second = Mock()
        second.fetchone.return_value = (2,)
        self.connection.execute.side_effect = [first, second]

        ids = [
            database.upsert_push_subscription(7, endpoint, "p", "a", None)
            for endpoint in ("https://push.example/phone", "https://push.example/desktop")
        ]

        self.assertEqual(ids, [1, 2])
        self.assertEqual(self.connection.execute.call_count, 2)

    def test_remove_scopes_foreign_and_missing_endpoints_to_current_user(self):
        database.remove_push_subscription(7, "https://push.example/device")

        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("WHERE user_id = %s AND endpoint = %s", sql)
        self.assertEqual(parameters, (7, "https://push.example/device"))

    def test_fanout_query_is_family_scoped_and_excludes_actor_user(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        self.connection.execute.return_value = cursor

        self.assertEqual(database.get_family_push_subscriptions(42, 7), [])

        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("JOIN users u", sql)
        self.assertIn("u.family_id = %s", sql)
        self.assertIn("u.auth_user_id IS NOT NULL", sql)
        self.assertIn("u.id <> %s", sql)
        self.assertIn("ps.expiration_time IS NULL OR ps.expiration_time > NOW()", sql)
        self.assertEqual(parameters, (42, 7))

    def test_dead_cleanup_uses_the_complete_subscription_snapshot(self):
        subscription = {
            "id": 91,
            "endpoint": "https://push.example/device",
            "p256dh": "p",
            "auth": "a",
            "updated_at": "2026-09-06T12:00:00+00:00",
        }

        database.remove_dead_push_subscription(subscription)

        sql, parameters = self.connection.execute.call_args.args
        for condition in ("id = %s", "endpoint = %s", "p256dh = %s", "auth = %s", "updated_at = %s"):
            self.assertIn(condition, sql)
        self.assertEqual(parameters, tuple(subscription.values()))


if __name__ == "__main__":
    unittest.main()
