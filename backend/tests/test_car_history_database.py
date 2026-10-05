import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from tests.test_database_atomic_creation import RecordingContext, database


class CarHistoryDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock(name="connection")
        self.pool_patch = patch.object(database, "pool")
        self.pool = self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)
        self.pool.connection.return_value = RecordingContext(self.connection)

    def test_queries_are_bounded_family_scoped_projection_reads(self):
        self.connection.execute.return_value.fetchall.return_value = []
        database.get_car_usage_history(42, completed_limit=500)
        active, completed = [call.args for call in self.connection.execute.call_args_list]
        for sql, _ in (active, completed):
            self.assertIn('vehicle_driver_sessions', sql)
            self.assertIn('WHERE s.family_id=%s', sql)
            self.assertNotIn('car_events', sql)
            self.assertNotIn('shortcut_token', sql)
            self.assertNotIn('auth_user_id', sql)
        self.assertIn('s.ended_at IS NULL', active[0])
        self.assertIn('LIMIT 101', active[0])
        self.assertEqual(active[1], (42,))
        self.assertIn('s.ended_at IS NOT NULL', completed[0])
        self.assertEqual(completed[1], (42, 50))

    def test_active_cannot_be_pushed_off_completed_page_and_timestamps_are_aware(self):
        start = datetime(2026, 9, 20, tzinfo=timezone.utc)
        active = ('A', start, None, True, 1, 'Car A', 'ref-a')
        ended = ('B', start, start, False, 2, 'Car B', 'ref-b')
        self.connection.execute.return_value.fetchall.side_effect = [[active], [ended] * 50]
        rows = database.get_car_usage_history(42)
        self.assertEqual(len(rows), 51)
        self.assertEqual(rows[0], ('A', start.isoformat(), None, True, 1, 'Car A', 'ref-a'))
        self.assertTrue(rows[1][2].endswith('+00:00'))
