import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
import threading
from unittest.mock import Mock, patch


class RecordingContext:
    def __init__(self, value=None):
        self.value = value
        self.entered = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        self.entered = True
        return self.value

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


def load_database_module_without_real_connection():
    fake_pool = Mock(name="pool")
    psycopg_pool_stub = types.ModuleType("psycopg_pool")
    psycopg_pool_stub.ConnectionPool = Mock(return_value=fake_pool)

    psycopg_stub = types.ModuleType("psycopg")
    psycopg_errors_stub = types.ModuleType("psycopg.errors")
    psycopg_errors_stub.ForeignKeyViolation = type(
        "ForeignKeyViolation",
        (Exception,),
        {},
    )
    psycopg_errors_stub.UniqueViolation = type("UniqueViolation", (Exception,), {})

    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = Mock()

    module_path = Path(__file__).resolve().parents[1] / "database.py"
    spec = importlib.util.spec_from_file_location("database_under_test", module_path)
    module = importlib.util.module_from_spec(spec)

    with patch.dict(
        sys.modules,
        {
            "psycopg": psycopg_stub,
            "psycopg.errors": psycopg_errors_stub,
            "psycopg_pool": psycopg_pool_stub,
            "dotenv": dotenv_stub,
        },
    ), patch.dict(os.environ, {"DATABASE_URL": "postgresql://test"}):
        spec.loader.exec_module(module)

    return module


database = load_database_module_without_real_connection()


class ShortcutCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class ShortcutState:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = None
        self.update_count = 0


class ShortcutTransaction:
    def __init__(self, state):
        self.state = state

    def __enter__(self):
        self.state.lock.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.state.lock.release()


class ShortcutConnection:
    def __init__(self, state):
        self.state = state

    def transaction(self):
        return ShortcutTransaction(self.state)

    def execute(self, sql, parameters):
        if "SELECT shortcut_token" in sql:
            return ShortcutCursor((self.state.token,))
        if "UPDATE users" in sql:
            self.state.token = parameters[0]
            self.state.update_count += 1
            return ShortcutCursor((self.state.token,))
        raise AssertionError(sql)


class ShortcutConnectionContext:
    def __init__(self, state):
        self.connection = ShortcutConnection(state)

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ShortcutPool:
    def __init__(self, state):
        self.state = state

    def connection(self):
        return ShortcutConnectionContext(self.state)


class ShortcutTokenConcurrencyTests(unittest.TestCase):
    def test_concurrent_requests_receive_the_same_single_token(self):
        state = ShortcutState()
        original_pool = database.pool
        original_generator = database.generate_shortcut_token
        generated = iter(("first-code", "second-code"))
        database.pool = ShortcutPool(state)
        database.generate_shortcut_token = lambda: next(generated)
        results = []

        try:
            threads = [
                threading.Thread(
                    target=lambda: results.append(
                        database.get_or_create_shortcut_token(17)
                    )
                )
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            database.pool = original_pool
            database.generate_shortcut_token = original_generator

        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 1)
        self.assertIn(results[0], {"first-code", "second-code"})
        self.assertEqual(state.update_count, 1)


class AtomicFamilyCreationTests(unittest.TestCase):
    def setUp(self):
        database.pool.connection.reset_mock()
        self.connection = Mock(name="connection")
        self.connection_context = RecordingContext(self.connection)
        self.transaction_context = RecordingContext()
        self.connection.transaction.return_value = self.transaction_context
        database.pool.connection.return_value = self.connection_context

    def call_atomic_creation(self):
        return database.create_family_with_first_user(
            name="כהן",
            family_code="482731",
            home_address="תל אביב, דיזנגוף, 120",
            user_name="מיכאל",
            home_latitude=32.0809,
            home_longitude=34.7806,
        )

    def test_success_uses_one_connection_and_one_transaction(self):
        family_cursor = Mock(name="family_cursor")
        family_cursor.fetchone.return_value = (7,)
        self.connection.execute.side_effect = [family_cursor, Mock(name="user_cursor")]

        family_id = self.call_atomic_creation()

        self.assertEqual(family_id, 7)
        database.pool.connection.assert_called_once_with()
        self.connection.transaction.assert_called_once_with()
        self.assertEqual(self.connection.execute.call_count, 2)
        self.assertTrue(self.transaction_context.committed)
        self.assertFalse(self.transaction_context.rolled_back)

        user_insert = self.connection.execute.call_args_list[1]
        self.assertIn("INSERT INTO users", user_insert.args[0])
        self.assertEqual(
            user_insert.args[1],
            ("מיכאל", 7, None),
        )

    def test_user_insert_failure_rolls_back_family_insert(self):
        family_cursor = Mock(name="family_cursor")
        family_cursor.fetchone.return_value = (7,)
        self.connection.execute.side_effect = [
            family_cursor,
            RuntimeError("user insert failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "user insert failed"):
            self.call_atomic_creation()

        self.assertEqual(self.connection.execute.call_count, 2)
        self.assertTrue(self.transaction_context.rolled_back)
        self.assertFalse(self.transaction_context.committed)

    def test_duplicate_family_code_stops_before_user_insert_and_rolls_back(self):
        class DuplicateFamilyCodeError(Exception):
            pass

        self.connection.execute.side_effect = DuplicateFamilyCodeError(
            "duplicate family code"
        )

        with self.assertRaisesRegex(DuplicateFamilyCodeError, "duplicate family code"):
            self.call_atomic_creation()

        self.connection.execute.assert_called_once()
        self.assertIn("INSERT INTO families", self.connection.execute.call_args.args[0])
        self.assertTrue(self.transaction_context.rolled_back)
        self.assertFalse(self.transaction_context.committed)

    def test_pwa_creation_serializes_checks_and_stores_auth_identity(self):
        lock_cursor = Mock(name="lock_cursor")
        mapped_cursor = Mock(name="mapped_cursor")
        mapped_cursor.fetchone.return_value = None
        code_cursor = Mock(name="code_cursor")
        code_cursor.fetchone.return_value = None
        location_cursor = Mock(name="location_cursor")
        location_cursor.fetchone.return_value = None
        family_cursor = Mock(name="family_cursor")
        family_cursor.fetchone.return_value = (7,)
        self.connection.execute.side_effect = [
            lock_cursor,
            mapped_cursor,
            code_cursor,
            location_cursor,
            family_cursor,
            Mock(name="user_cursor"),
        ]

        family_id = database.create_family_with_first_user(
            name="כהן",
            family_code="482731",
            home_address="תל אביב, דיזנגוף, 120",
            user_name="מיכאל",
            home_latitude=32.0809,
            home_longitude=34.7806,
            auth_user_id="auth-user-uuid",
            prevent_duplicate_location=True,
        )

        self.assertEqual(family_id, 7)
        self.assertIn(
            "pg_advisory_xact_lock",
            self.connection.execute.call_args_list[0].args[0],
        )
        user_insert = self.connection.execute.call_args_list[-1]
        self.assertEqual(
            user_insert.args[1],
            ("מיכאל", 7, "auth-user-uuid"),
        )
        self.assertTrue(self.transaction_context.committed)

    def test_pwa_duplicate_auth_user_rolls_back_before_family_insert(self):
        mapped_cursor = Mock(name="mapped_cursor")
        mapped_cursor.fetchone.return_value = (17,)
        self.connection.execute.side_effect = [Mock(name="lock_cursor"), mapped_cursor]

        with self.assertRaises(database.AuthUserAlreadyMappedError):
            database.create_family_with_first_user(
                name="כהן",
                family_code="482731",
                home_address="תל אביב, דיזנגוף, 120",
                user_name="מיכאל",
                home_latitude=32.0809,
                home_longitude=34.7806,
                auth_user_id="auth-user-uuid",
                prevent_duplicate_location=True,
            )

        self.assertEqual(self.connection.execute.call_count, 2)
        self.assertTrue(self.transaction_context.rolled_back)

    def test_pwa_duplicate_location_rolls_back_before_insert(self):
        mapped_cursor = Mock(name="mapped_cursor")
        mapped_cursor.fetchone.return_value = None
        code_cursor = Mock(name="code_cursor")
        code_cursor.fetchone.return_value = None
        location_cursor = Mock(name="location_cursor")
        location_cursor.fetchone.return_value = (9, "לוי")
        self.connection.execute.side_effect = [
            Mock(name="lock_cursor"),
            mapped_cursor,
            code_cursor,
            location_cursor,
        ]

        with self.assertRaises(database.FamilyAlreadyExistsAtLocationError):
            database.create_family_with_first_user(
                name="כהן",
                family_code="482731",
                home_address="תל אביב, דיזנגוף, 120",
                user_name="מיכאל",
                home_latitude=32.0809,
                home_longitude=34.7806,
                auth_user_id="auth-user-uuid",
                prevent_duplicate_location=True,
            )

        self.assertEqual(self.connection.execute.call_count, 4)
        self.assertTrue(self.transaction_context.rolled_back)

    def test_missing_auth_user_fk_is_structured_and_rolls_back_everything(self):
        mapped_cursor = Mock(name="mapped_cursor")
        mapped_cursor.fetchone.return_value = None
        code_cursor = Mock(name="code_cursor")
        code_cursor.fetchone.return_value = None
        location_cursor = Mock(name="location_cursor")
        location_cursor.fetchone.return_value = None
        family_cursor = Mock(name="family_cursor")
        family_cursor.fetchone.return_value = (7,)
        foreign_key_error = database.ForeignKeyViolation("missing auth user")
        foreign_key_error.diag = types.SimpleNamespace(
            constraint_name="users_auth_user_id_fkey"
        )
        self.connection.execute.side_effect = [
            Mock(name="lock_cursor"),
            mapped_cursor,
            code_cursor,
            location_cursor,
            family_cursor,
            foreign_key_error,
        ]

        with self.assertLogs(database.logger, level="WARNING") as captured_logs:
            with self.assertRaises(database.AuthUserIdentityNotFoundError):
                database.create_family_with_first_user(
                    name="כהן",
                    family_code="482731",
                    home_address="תל אביב, דיזנגוף, 120",
                    user_name="מיכאל",
                    home_latitude=32.0809,
                    home_longitude=34.7806,
                    auth_user_id="deleted-auth-user-uuid",
                    prevent_duplicate_location=True,
                )

        self.assertTrue(self.transaction_context.rolled_back)
        self.assertFalse(self.transaction_context.committed)
        self.assertIn("exception_type=ForeignKeyViolation", captured_logs.output[0])
        self.assertIn("stage=insert_first_user", captured_logs.output[0])
        self.assertIn("error_code=AUTH_SESSION_INVALID", captured_logs.output[0])
        self.assertNotIn("deleted-auth-user-uuid", captured_logs.output[0])


class AuthUserLookupTests(unittest.TestCase):
    def setUp(self):
        database.pool.connection.reset_mock()
        self.connection = Mock(name="connection")
        self.connection_context = RecordingContext(self.connection)
        self.cursor = Mock(name="cursor")
        self.connection.execute.return_value = self.cursor
        database.pool.connection.return_value = self.connection_context

    def test_returns_internal_identity_for_auth_user_id(self):
        self.cursor.fetchone.return_value = (17, "מיכאל", 42, "completed")

        user = database.get_user_by_auth_user_id("auth-user-uuid")

        self.assertEqual(user, (17, "מיכאל", 42, "completed"))
        database.pool.connection.assert_called_once_with()
        self.connection.execute.assert_called_once()
        sql, params = self.connection.execute.call_args.args
        self.assertIn("SELECT id, name, family_id, carplay_setup_status", sql)
        self.assertIn("WHERE auth_user_id = %s", sql)
        self.assertEqual(params, ("auth-user-uuid",))

    def test_returns_none_when_auth_user_id_is_not_mapped(self):
        self.cursor.fetchone.return_value = None

        user = database.get_user_by_auth_user_id("unknown-auth-user")

        self.assertIsNone(user)
        database.pool.connection.assert_called_once_with()
        self.connection.execute.assert_called_once()

    def test_updates_carplay_setup_status_for_internal_user_only(self):
        self.cursor.fetchone.return_value = ("skipped",)

        result = database.set_carplay_setup_status(17, "skipped")

        self.assertEqual(result, "skipped")
        sql, params = self.connection.execute.call_args.args
        self.assertIn("UPDATE users", sql)
        self.assertIn("RETURNING carplay_setup_status", sql)
        self.assertEqual(params, ("skipped", 17))

    def test_carplay_status_update_rejects_a_missing_internal_user(self):
        self.cursor.fetchone.return_value = None

        with self.assertRaises(database.UserNotFoundError):
            database.set_carplay_setup_status(999, "completed")


class AtomicPwaJoinTests(unittest.TestCase):
    def setUp(self):
        database.pool.connection.reset_mock()
        self.connection = Mock(name="connection")
        self.connection_context = RecordingContext(self.connection)
        self.transaction_context = RecordingContext()
        self.connection.transaction.return_value = self.transaction_context
        database.pool.connection.return_value = self.connection_context

    @staticmethod
    def session_row():
        return (
            "auth-user-uuid",
            "user_name",
            "כהן",
            7,
            "תל אביב, דיזנגוף, 120",
            "120 Dizengoff Street, Tel Aviv",
            0,
            0,
            0,
            None,
            "created",
            "updated",
        )

    @staticmethod
    def cursor(row=None):
        cursor = Mock()
        cursor.fetchone.return_value = row
        return cursor

    def test_complete_join_inserts_user_and_deletes_session_in_one_transaction(self):
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(self.session_row()),
            self.cursor(None),
            self.cursor((7,)),
            self.cursor((17,)),
            self.cursor(),
        ]

        result = database.complete_pwa_join("auth-user-uuid", "מיכאל")

        self.assertEqual(result, {"created": True, "user_id": 17, "family_id": 7})
        self.assertTrue(self.transaction_context.committed)
        self.assertFalse(self.transaction_context.rolled_back)
        user_insert = self.connection.execute.call_args_list[6]
        self.assertIn("INSERT INTO users", user_insert.args[0])
        self.assertEqual(user_insert.args[1], ("מיכאל", 7, "auth-user-uuid"))
        self.assertIn(
            "DELETE FROM pwa_join_sessions",
            self.connection.execute.call_args_list[7].args[0],
        )

    def test_user_insert_failure_rolls_back_without_deleting_join_session(self):
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(self.session_row()),
            self.cursor(None),
            self.cursor((7,)),
            RuntimeError("user insert failed"),
        ]

        with self.assertRaisesRegex(RuntimeError, "user insert failed"):
            database.complete_pwa_join("auth-user-uuid", "מיכאל")

        self.assertTrue(self.transaction_context.rolled_back)
        self.assertFalse(self.transaction_context.committed)
        self.assertFalse(
            any(
                "DELETE FROM pwa_join_sessions" in call.args[0]
                for call in self.connection.execute.call_args_list
            )
        )

    def test_third_name_failure_locks_for_fifteen_minutes_under_row_lock(self):
        active_session = list(self.session_row())
        active_session[1] = "family_name"
        active_session[3] = None
        active_session[6] = 2
        locked_session = list(active_session)
        locked_session[1] = "locked"
        locked_session[6] = 3
        locked_session[9] = "locked-until"
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(tuple(active_session)),
            self.cursor(None),
            self.cursor(None),
            self.cursor(tuple(locked_session)),
        ]

        result = database.submit_pwa_join_family_name(
            "auth-user-uuid",
            "לא קיימת",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["attempts_remaining"], 0)
        self.assertEqual(result["locked_until"], "locked-until")
        self.assertIn(
            "FOR UPDATE",
            self.connection.execute.call_args_list[3].args[0],
        )
        self.assertIn(
            "INTERVAL '15 minutes'",
            self.connection.execute.call_args_list[6].args[0],
        )
        self.assertTrue(self.transaction_context.committed)

    def test_same_literal_family_name_advances_without_incrementing_attempts(self):
        active_session = list(self.session_row())
        active_session[1] = "family_name"
        active_session[2] = None
        active_session[3] = None
        active_session[6] = 2
        advanced_session = list(active_session)
        advanced_session[1] = "address"
        advanced_session[2] = "סנדרוביץ'"
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(tuple(active_session)),
            self.cursor((1,)),
            self.cursor(tuple(advanced_session)),
        ]

        result = database.submit_pwa_join_family_name(
            "auth-user-uuid",
            "סנדרוביץ'",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["session"]["family_name_attempts"], 2)
        self.assertFalse(
            any(
                "family_name_attempts = %s" in call.args[0]
                for call in self.connection.execute.call_args_list
            )
        )

    def test_legacy_punctuation_name_uses_canonical_fallback_without_failure(self):
        active_session = list(self.session_row())
        active_session[1] = "family_name"
        active_session[2] = None
        active_session[3] = None
        active_session[6] = 2
        advanced_session = list(active_session)
        advanced_session[1] = "address"
        advanced_session[2] = "סנדרוביץ'"
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(tuple(active_session)),
            self.cursor(None),
            self.cursor((1,)),
            self.cursor(tuple(advanced_session)),
        ]

        result = database.submit_pwa_join_family_name(
            "auth-user-uuid",
            "סנדרוביץ'",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["session"]["family_name_attempts"], 2)
        fallback_lookup = self.connection.execute.call_args_list[5]
        self.assertIn("NORMALIZE(name, NFC)", fallback_lookup.args[0])
        self.assertIn("TRANSLATE", fallback_lookup.args[0])
        self.assertIn("REGEXP_REPLACE", fallback_lookup.args[0])
        source_characters, target_characters, lookup_name = fallback_lookup.args[1]
        for legacy_character in ("’", "׳", "‐", "‑", "‒", "–", "—", "−"):
            self.assertIn(legacy_character, source_characters)
        self.assertEqual(len(source_characters), len(target_characters))
        self.assertEqual(lookup_name, "סנדרוביץ'")

    def test_legacy_name_and_location_falls_back_to_canonical_comparison(self):
        expected_family = (7, "סנדרוביץ׳", "דימונה, המעפיל, 1209", 31.0, 35.0)
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(expected_family),
        ]

        family = database._get_family_by_name_and_location(
            self.connection,
            "סנדרוביץ'",
            31.0,
            35.0,
        )

        self.assertEqual(family, expected_family)
        fallback_lookup = self.connection.execute.call_args_list[1]
        self.assertIn("NORMALIZE(name, NFC)", fallback_lookup.args[0])
        self.assertEqual(fallback_lookup.args[1][2], "סנדרוביץ'")

    def test_expired_lock_is_reset_safely_when_session_starts(self):
        reset_session = list(self.session_row())
        reset_session[1] = "family_name"
        reset_session[2] = None
        reset_session[3] = None
        reset_session[4] = None
        reset_session[5] = None
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(tuple(reset_session)),
        ]

        result = database.start_pwa_join_session("auth-user-uuid")

        self.assertEqual(result["step"], "family_name")
        self.assertTrue(result["was_reset"])
        reset_sql = self.connection.execute.call_args_list[2].args[0]
        self.assertIn("locked_until <= NOW()", reset_sql)
        self.assertIn("family_code_attempts = 0", reset_sql)

    def test_concurrent_completion_that_loses_session_is_idempotent(self):
        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(None),
            self.cursor((17,)),
        ]

        with self.assertRaises(database.AuthUserAlreadyMappedError):
            database.complete_pwa_join("auth-user-uuid", "מיכאל")

        self.assertTrue(self.transaction_context.rolled_back)
        self.assertEqual(self.connection.execute.call_count, 5)

    def test_concurrent_completion_rechecks_mapping_after_recreated_session(self):
        recreated_session = list(self.session_row())
        recreated_session[1] = "family_name"
        recreated_session[2] = None
        recreated_session[3] = None
        recreated_session[4] = None
        recreated_session[5] = None

        self.connection.execute.side_effect = [
            self.cursor(None),
            self.cursor(),
            self.cursor(None),
            self.cursor(tuple(recreated_session)),
            self.cursor((17,)),
        ]

        with self.assertRaises(database.AuthUserAlreadyMappedError):
            database.complete_pwa_join("auth-user-uuid", "מיכאל")

        self.assertTrue(self.transaction_context.rolled_back)
        self.assertFalse(self.transaction_context.committed)
        self.assertEqual(self.connection.execute.call_count, 5)
        mapping_recheck = self.connection.execute.call_args_list[4]
        self.assertIn(
            "SELECT id FROM users WHERE auth_user_id = %s",
            mapping_recheck.args[0],
        )
        self.assertFalse(
            any(
                "SELECT id FROM families" in call.args[0]
                or "INSERT INTO users" in call.args[0]
                for call in self.connection.execute.call_args_list
            )
        )


if __name__ == "__main__":
    unittest.main()
