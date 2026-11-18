import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from tests.test_database_atomic_creation import RecordingContext, database


class ReservationCenterDatabaseTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(database, "reservation_now", return_value=datetime(2026, 9, 6, 12))
        clock.start()
        self.addCleanup(clock.stop)
        self.connection = Mock(name="connection")
        self.connection_context = RecordingContext(self.connection)
        self.transaction_context = RecordingContext()
        self.connection.transaction.return_value = self.transaction_context
        self.pool_patch = patch.object(database, "pool")
        self.pool = self.pool_patch.start()
        self.pool.connection.return_value = self.connection_context

    def tearDown(self):
        self.pool_patch.stop()

    @staticmethod
    def cursor(row=None, rows=None):
        cursor = Mock()
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = rows or []
        return cursor

    def test_list_is_family_scoped_filtered_and_does_not_select_ids(self):
        self.connection.execute.return_value = self.cursor(rows=[
            ("מיכאל", "2026-09-08T10:00:00", "2026-09-08T11:00:00", True)
        ])
        rows = database.list_family_reservations(
            42, 17, "future", "all", "2026-09-06T12:00:00"
        )
        sql, parameters = self.connection.execute.call_args.args

        self.assertEqual(len(rows), 1)
        self.assertIn("WHERE u.family_id = %s", sql)
        self.assertIn("r.status = 'active'", sql)
        self.assertIn("r.end_time::timestamp > %s::timestamp", sql)
        self.assertNotIn("r.id,", sql)
        self.assertNotIn("r.user_id,", sql)
        self.assertEqual(parameters, (17, 42, "2026-09-06T12:00:00"))
        self.assertEqual(sql.split('ORDER BY', 1)[1].strip(), 'r.start_time::timestamp ASC')

    def test_mine_filter_adds_caller_owner_scope(self):
        self.connection.execute.return_value = self.cursor()
        database.list_family_reservations(
            42, 17, "past", "mine", "2026-09-06T12:00:00"
        )
        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("r.end_time::timestamp <= %s::timestamp", sql)
        self.assertIn("AND r.user_id = %s", sql)
        self.assertEqual(parameters, (17, 42, "2026-09-06T12:00:00", 17))

    def test_foreign_and_missing_update_targets_are_indistinguishable(self):
        self.connection.execute.side_effect = [self.cursor(), self.cursor((42,)), self.cursor(), self.cursor(rows=[])]
        result = database.update_current_user_reservation(
            17,
            42,
            "old-start",
            "old-end",
            "boundary",
            "new-start",
            "new-end",
        )
        locator_sql, parameters = self.connection.execute.call_args_list[3].args

        self.assertEqual(result["code"], "RESERVATION_NOT_FOUND_OR_UNAVAILABLE")
        self.assertIn("r.user_id=%s", locator_sql)
        self.assertIn("u.family_id=%s", locator_sql)
        self.assertIn('LIMIT 2 FOR UPDATE OF r', locator_sql)
        self.assertEqual(parameters, (17, 42, "old-start", "old-end"))
        self.assertEqual(self.connection.execute.call_count, 4)
        self.assertTrue(self.transaction_context.committed)

    def test_foreign_and_missing_cancel_targets_are_indistinguishable(self):
        self.connection.execute.side_effect = [self.cursor(), self.cursor((42,)), self.cursor(), self.cursor(rows=[])]
        result = database.cancel_current_user_reservation(
            17, 42, "old-start", "old-end", "boundary"
        )
        locator_sql = self.connection.execute.call_args_list[3].args[0]

        self.assertEqual(result["code"], "RESERVATION_NOT_FOUND_OR_UNAVAILABLE")
        self.assertIn("r.user_id=%s", locator_sql)
        self.assertIn("u.family_id=%s", locator_sql)
        self.assertIn('LIMIT 2 FOR UPDATE OF r', locator_sql)
        self.assertEqual(self.connection.execute.call_count, 4)

    def test_create_reuses_canonical_conflict_and_owner_logic_under_family_lock(self):
        self.connection.execute.side_effect = [
            self.cursor(), self.cursor((42,)), self.cursor(),
            self.cursor((42,)),
            self.cursor(), self.cursor((42,)),
            self.cursor(),
            self.cursor(rows=[]),
            self.cursor(None),
            self.cursor((501,)),
            self.cursor(('00000000-0000-0000-0000-000000000003', None)),
        ]
        result = database.create_current_user_reservation(
            17, 42, "2026-09-08T10:00:00", "2026-09-08T11:00:00"
        )

        self.assertTrue(result["success"])
        self.assertIn("pg_advisory_xact_lock", self.connection.execute.call_args_list[0].args[0])
        self.assertIn("SELECT family_id", self.connection.execute.call_args_list[3].args[0])
        self.assertIn("FROM reservations r", self.connection.execute.call_args_list[8].args[0])
        self.assertIn("INSERT INTO reservations", self.connection.execute.call_args_list[9].args[0])

    def test_bounded_query_uses_half_open_timestamps_and_deterministic_order(self):
        self.connection.execute.side_effect = [self.cursor((8,)), self.cursor((17,)), self.cursor()]
        database.list_family_reservations(42, 17, 'future', 'all', 'unused',
            range_start='2026-09-01T00:00:00', range_end='2026-09-02T00:00:00',
            vehicle_ref='vehicle', member_ref='member')
        vehicle_sql, vehicle_args = self.connection.execute.call_args_list[0].args
        member_sql, member_args = self.connection.execute.call_args_list[1].args
        sql, args = self.connection.execute.call_args.args
        self.assertIn('family_id=%s AND vehicle_ref=%s', vehicle_sql)
        self.assertNotIn('retired_at', vehicle_sql)
        self.assertEqual(vehicle_args, (42, 'vehicle'))
        self.assertIn('family_id=%s AND member_public_id=%s', member_sql)
        self.assertEqual(member_args, (42, 'member'))
        self.assertIn('r.start_time::timestamp < %s::timestamp AND r.end_time::timestamp > %s::timestamp', sql)
        self.assertIn('WHERE u.family_id = %s', sql)
        self.assertIn('AND r.vehicle_id=%s AND v.family_id=%s AND r.user_id=%s', sql)
        self.assertIn('ORDER BY r.start_time::timestamp ASC, r.reservation_ref ASC', sql)
        self.assertNotIn('LIMIT', sql)
        self.assertNotIn('timestamptz', sql)
        self.assertEqual(args, (17, 42, '2026-09-02T00:00:00', '2026-09-01T00:00:00', 8, 42, 17))

    def test_unavailable_filters_stop_before_data_query(self):
        for field in ('vehicle_ref', 'member_ref'):
            self.connection.execute.reset_mock()
            self.connection.execute.return_value = self.cursor()
            result = database.list_family_reservations(42, 17, 'future', 'all', 'unused',
                range_start='2026-09-01', range_end='2026-09-02', **{field: 'unavailable'})
            self.assertIsNone(result)
            self.assertEqual(self.connection.execute.call_count, 1)

    def test_cast_failure_propagates_not_empty_success(self):
        self.connection.execute.side_effect = ValueError('simulated invalid legacy timestamp')
        with self.assertRaises(ValueError):
            database.list_family_reservations(42, 17, 'future', 'all', '',
                range_start='2026-09-01', range_end='2026-09-02')

    def test_bounded_mine_retains_owner_and_family_predicates(self):
        self.connection.execute.return_value = self.cursor()
        database.list_family_reservations(42, 17, 'future', 'mine', 'unused',
            range_start='2026-09-01', range_end='2026-09-02')
        sql, args = self.connection.execute.call_args.args
        self.assertIn('WHERE u.family_id = %s', sql)
        self.assertIn('AND r.user_id = %s', sql)
        self.assertEqual(args, (17, 42, '2026-09-02', '2026-09-01', 17))

    def test_enrichment_is_scoped_and_nullable(self):
        for category in (None, 'sedan'):
            self.connection.execute.return_value = self.cursor(('public-member', category))
            result = database._enrich_reservation_response(self.connection,
                {'success': True, 'reservation_ref': 'public-reservation'}, 17, 42)
            self.assertEqual(result['member_ref'], 'public-member')
            self.assertEqual(result['vehicle_category'], category)
            sql, args = self.connection.execute.call_args.args
            self.assertIn('LEFT JOIN vehicles', sql)
            self.assertNotIn('retired_at', sql)
            self.assertIn('r.user_id=%s AND u.family_id=%s', sql)
            self.assertEqual(args, ('public-reservation', 17, 42))


if __name__ == "__main__":
    unittest.main()
