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

    def test_mine_filter_adds_caller_owner_scope(self):
        self.connection.execute.return_value = self.cursor()
        database.list_family_reservations(
            42, 17, "past", "mine", "2026-09-06T12:00:00"
        )
        sql, parameters = self.connection.execute.call_args.args
        self.assertIn("r.end_time::timestamp <= %s::timestamp", sql)
        self.assertIn("AND r.user_id = %s", sql)
        self.assertEqual(parameters, (17, 42, "2026-09-06T12:00:00", 17))

    def test_foreign_missing_and_past_update_targets_are_indistinguishable(self):
        self.connection.execute.side_effect = [self.cursor(), self.cursor(None)]
        result = database.update_current_user_reservation(
            17,
            42,
            "old-start",
            "old-end",
            "boundary",
            "new-start",
            "new-end",
        )
        locator_sql, parameters = self.connection.execute.call_args_list[1].args

        self.assertEqual(result["code"], "RESERVATION_NOT_FOUND_OR_UNAVAILABLE")
        self.assertIn("r.user_id = %s", locator_sql)
        self.assertIn("u.family_id = %s", locator_sql)
        self.assertIn("r.end_time::timestamp > %s::timestamp", locator_sql)
        self.assertEqual(parameters, (17, 42, "old-start", "old-end", "boundary"))
        self.assertEqual(self.connection.execute.call_count, 2)
        self.assertTrue(self.transaction_context.committed)

    def test_foreign_missing_and_past_cancel_targets_are_indistinguishable(self):
        self.connection.execute.side_effect = [self.cursor(), self.cursor(None)]
        result = database.cancel_current_user_reservation(
            17, 42, "old-start", "old-end", "boundary"
        )
        locator_sql = self.connection.execute.call_args_list[1].args[0]

        self.assertEqual(result["code"], "RESERVATION_NOT_FOUND_OR_UNAVAILABLE")
        self.assertIn("r.user_id = %s", locator_sql)
        self.assertIn("u.family_id = %s", locator_sql)
        self.assertIn("r.end_time::timestamp > %s::timestamp", locator_sql)
        self.assertEqual(self.connection.execute.call_count, 2)

    def test_create_reuses_canonical_conflict_and_owner_logic_under_family_lock(self):
        self.connection.execute.side_effect = [
            self.cursor(),
            self.cursor((42,)),
            self.cursor(None),
            self.cursor((501,)),
        ]
        result = database.create_current_user_reservation(
            17, 42, "2026-09-08T10:00:00", "2026-09-08T11:00:00"
        )

        self.assertTrue(result["success"])
        self.assertIn("pg_advisory_xact_lock", self.connection.execute.call_args_list[0].args[0])
        self.assertIn("SELECT family_id", self.connection.execute.call_args_list[1].args[0])
        self.assertIn("FROM reservations r", self.connection.execute.call_args_list[2].args[0])
        self.assertIn("INSERT INTO reservations", self.connection.execute.call_args_list[3].args[0])


if __name__ == "__main__":
    unittest.main()
