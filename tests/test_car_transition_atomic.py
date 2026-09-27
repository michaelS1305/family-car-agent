"""Legacy SQL entry points are disabled; engine races live in test_carplay_adapter."""
import unittest
from unittest.mock import Mock, patch
from tests.test_database_atomic_creation import database


class LegacyWriterDisabledTests(unittest.TestCase):
    def test_all_old_mutation_entry_points_fail_without_database_access(self):
        with patch.object(database, 'pool') as pool:
            for method, args in (
                (database.connect_car_atomically, (1, 'name', 10)),
                (database.disconnect_car_atomically, (1, 10)),
                (database._insert_car_event_on_connection, (Mock(), 1, 'name', 'connected', 10)),
            ):
                with self.subTest(method=method.__name__), self.assertRaises(RuntimeError):
                    method(*args)
            pool.connection.assert_not_called()

    def test_current_state_query_uses_family_scoped_sessions_only(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = ('Driver', 1)
        self.assertEqual(database._get_active_driver_on_connection(conn, 10), ('Driver', 1))
        query, params = conn.execute.call_args.args
        self.assertIn('vehicle_driver_sessions', query)
        self.assertIn('s.family_id=%s', query)
        self.assertIn('s.ended_at IS NULL', query)
        self.assertNotIn('car_events', query)
        self.assertEqual(params, (10,))
