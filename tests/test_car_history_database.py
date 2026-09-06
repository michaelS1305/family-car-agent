import unittest
from unittest.mock import Mock, patch

from tests.test_database_atomic_creation import RecordingContext, database


class CarHistoryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock(name="connection")
        self.connection_context = RecordingContext(self.connection)
        self.pool_patch = patch.object(database, "pool")
        self.pool = self.pool_patch.start()
        self.pool.connection.return_value = self.connection_context

    def tearDown(self):
        self.pool_patch.stop()

    def test_query_is_family_scoped_and_matches_canonical_active_semantics(self):
        cursor = Mock()
        cursor.fetchall.return_value = []
        self.connection.execute.return_value = cursor
        database.get_car_usage_history(42, completed_limit=50)
        sql, parameters = self.connection.execute.call_args.args

        self.assertIn("WHERE family_id = %s", sql)
        self.assertIn("c.status = 'connected'", sql)
        self.assertIn("d.status = 'disconnected'", sql)
        self.assertIn("d.id > c.id", sql)
        self.assertIn("c.user_id IS NOT NULL AND d.user_id = c.user_id", sql)
        self.assertIn("c.user_id IS NULL AND d.driver_name = c.driver_name", sql)
        self.assertEqual(parameters, (42, 50))

    def test_duplicate_connect_is_deduplicated_and_only_display_fields_are_selected(self):
        cursor = Mock()
        cursor.fetchall.return_value = [
            ("מיכאל", "2026-09-05T10:00:00", "2026-09-05T11:00:00", False, 8)
        ]
        self.connection.execute.return_value = cursor
        rows = database.get_car_usage_history(42)
        sql = self.connection.execute.call_args.args[0]

        self.assertEqual(len(rows), 1)
        self.assertIn("newer_connect.id > candidate.id", sql)
        self.assertIn("newer_connect.id < candidate.ended_event_id", sql)
        self.assertIn("ORDER BY is_active DESC, sort_id DESC", sql)
        self.assertNotIn("shortcut_token", sql)
        self.assertNotIn("auth_user_id", sql)


if __name__ == "__main__":
    unittest.main()
