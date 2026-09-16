"""Allocator contracts and opt-in, isolated PostgreSQL assignment/Join races.

Fixtures deliberately do not execute any manual migration or touch public data.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

from tests.test_database_atomic_creation import database, RecordingContext


class AllocatorTests(unittest.TestCase):
    def setUp(self):
        self.conn = Mock()
        self.conn.transaction.side_effect = lambda: RecordingContext()
        self.states = []
        self.history = []
        def execute(sql, params):
            if sql.startswith("INSERT INTO family_code_history"):
                self.history.append(params[0])
                self.assertIn("ON CONFLICT (code) DO NOTHING", sql)
                return Mock()
            return Mock(fetchone=lambda: self.states.pop(0))
        self.conn.execute.side_effect = execute

    def allocate(self, codes, assign=None, excluded=None):
        with patch.object(database.secrets, "choice", side_effect=list("".join(codes))) as choice:
            result = database._allocate_family_code(self.conn, assign or (lambda code: code), excluded)
        self.assertTrue(all(call.args == (database.FAMILY_CODE_ALPHABET,) for call in choice.call_args_list))
        return result

    def test_never_used_preferred_over_released_and_active(self):
        self.states = [(False, True), (True, True), (False, False)]
        self.assertEqual(self.allocate(["old123", "act123", "00ab12"])[0], "00ab12")
        self.assertEqual(self.history, ["00ab12"])

    def test_released_fallback_reuses_history_without_error(self):
        self.states = [(False, True)] * database.FAMILY_CODE_SAMPLE_LIMIT
        self.assertEqual(self.allocate(["old123"] * database.FAMILY_CODE_SAMPLE_LIMIT)[0], "old123")
        self.assertEqual(self.history, ["old123"])

    def test_unchanged_current_excluded(self):
        self.states = [(False, False)]
        self.assertEqual(self.allocate(["old123", "new123"], excluded="old123")[0], "new123")

    def test_only_expected_unique_collision_retries(self):
        error = database.UniqueViolation()
        error.diag = types.SimpleNamespace(constraint_name="families_family_code_key")
        self.states = [(False, False)] * 2
        assign = Mock(side_effect=[error, 12])
        self.assertEqual(self.allocate(["aaa123", "bbb123"], assign), ("bbb123", 12))
        self.assertEqual(self.history, ["bbb123"])

    def test_unrelated_integrity_failure_propagates(self):
        error = database.UniqueViolation()
        error.diag = types.SimpleNamespace(constraint_name="unrelated_key")
        self.states = [(False, False)]
        with self.assertRaises(database.UniqueViolation):
            self.allocate(["aaa123"], Mock(side_effect=error))
        self.assertEqual(self.history, [])

    def test_exhaustion_bounded_and_no_history(self):
        count = database.FAMILY_CODE_SAMPLE_LIMIT * database.FAMILY_CODE_ASSIGNMENT_ATTEMPTS
        self.states = [(True, True)] * count
        with self.assertRaises(database.FamilyCodeTakenError):
            self.allocate(["act123"] * count)
        self.assertEqual(self.history, [])

    def test_collision_retries_stop_at_five_and_savepoints_roll_back(self):
        error = database.UniqueViolation()
        error.diag = types.SimpleNamespace(constraint_name="families_family_code_key")
        contexts = []
        def transaction():
            context = RecordingContext()
            contexts.append(context)
            return context
        self.conn.transaction.side_effect = transaction
        self.states = [(False, False)] * 5
        assign = Mock(side_effect=error)
        with self.assertRaises(database.FamilyCodeTakenError):
            self.allocate(["aaa123"] * 5, assign)
        self.assertEqual(assign.call_count, 5)
        self.assertTrue(all(context.rolled_back for context in contexts))
        self.assertEqual(self.history, [])

    def test_regeneration_denies_noncreator_missing_creator_and_missing_family(self):
        for row in (("old123", 17), ("old123", None), None):
            with self.subTest(row=row):
                conn = Mock()
                conn.transaction.return_value = RecordingContext()
                conn.execute.return_value.fetchone.return_value = row
                with patch.object(database.pool, "connection", return_value=RecordingContext(conn)):
                    self.assertIsNone(database.regenerate_family_code(18, 42))
                self.assertEqual(conn.execute.call_count, 2)
                self.assertIn("FOR UPDATE", conn.execute.call_args.args[0])

    def test_regeneration_updates_only_code_and_verified_session_step(self):
        conn = Mock()
        conn.transaction.return_value = RecordingContext()
        conn.execute.return_value.fetchone.return_value = ("old123", 17)
        with patch.object(database.pool, "connection", return_value=RecordingContext(conn)), patch.object(
            database, "_allocate_family_code", side_effect=lambda conn, assign, excluded_code: ("new123", assign("new123")),
        ):
            self.assertEqual(database.regenerate_family_code(17, 42), "new123")
        queries = [call.args[0] for call in conn.execute.call_args_list]
        self.assertIn("pg_advisory_xact_lock", queries[0])
        self.assertIn("UPDATE families SET family_code = %s WHERE id = %s", queries[2])
        self.assertIn("AND step = 'user_name'", queries[3])
        for forbidden in ("UPDATE users", "DELETE", "locked_until =", "attempts =", "shortcut_token"):
            self.assertNotIn(forbidden, " ".join(queries))


@unittest.skipUnless(os.environ.get("GEMINI_TEST_DATABASE_URL"), "Isolated PostgreSQL not configured")
class FamilyCodePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.psycopg, self.sql = psycopg, sql
        self.dsn = os.environ["GEMINI_TEST_DATABASE_URL"]
        url = urlsplit(self.dsn)
        if url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.path != "/test_gemini":
            raise RuntimeError("Only isolated local test_gemini database allowed")
        self.schema = "family_code_test_" + uuid4().hex
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        for name, value in (("pool", Mock(connection=self.connection)), ("UniqueViolation", psycopg.errors.UniqueViolation), ("ForeignKeyViolation", psycopg.errors.ForeignKeyViolation)):
            patcher = patch.object(database, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with self.connection() as conn:
            conn.execute("""CREATE TABLE families (
                id serial PRIMARY KEY, name text, family_code text NOT NULL UNIQUE,
                home_address text, home_latitude double precision, home_longitude double precision,
                created_at text, created_by_user_id integer)""")
            conn.execute("""CREATE TABLE users (
                id serial PRIMARY KEY, name text, family_id integer REFERENCES families(id),
                auth_user_id text CONSTRAINT users_auth_user_id_unique UNIQUE,
                family_role text, shortcut_token text)""")
            conn.execute("ALTER TABLE families ADD FOREIGN KEY (created_by_user_id) REFERENCES users(id)")
            conn.execute("""CREATE TABLE family_code_history (
                code text COLLATE "C" PRIMARY KEY CHECK (octet_length(code)=6 AND code ~ '^[a-z0-9]{6}$'))""")
            conn.execute("""CREATE TABLE pwa_join_sessions (
                auth_user_id text PRIMARY KEY, step text DEFAULT 'family_name',
                family_name text, family_id integer REFERENCES families(id),
                normalized_address text, resolved_address text,
                family_name_attempts smallint DEFAULT 0, address_attempts smallint DEFAULT 0,
                family_code_attempts smallint DEFAULT 0, locked_until timestamptz,
                created_at timestamptz DEFAULT NOW(), updated_at timestamptz DEFAULT NOW())""")
        self.family = self.create("creator")
        self.creator = self.query("SELECT id FROM users WHERE auth_user_id='creator'")[0][0]

    @contextmanager
    def connection(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("SET search_path TO {}").format(self.sql.Identifier(self.schema)))
            conn.commit()
            yield conn

    def drop_schema(self):
        with self.psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute(self.sql.SQL("DROP SCHEMA {} CASCADE").format(self.sql.Identifier(self.schema)))

    def query(self, sql, params=()):
        with self.connection() as conn:
            return conn.execute(sql, params).fetchall()

    def create(self, auth):
        return database.create_family_with_first_user(name="test", home_address="test", user_name="test", auth_user_id=auth)

    def current(self):
        return self.query("SELECT family_code FROM families WHERE id=%s", (self.family,))[0][0]

    def regenerate(self):
        return database.regenerate_family_code(self.creator, self.family)

    def session(self, step="family_code"):
        with self.connection() as conn:
            conn.execute("INSERT INTO pwa_join_sessions(auth_user_id, family_id, step, family_name_attempts, family_code_attempts) VALUES ('joiner',%s,%s,1,1)", (self.family, step))

    def test_create_records_history_and_failed_create_rolls_back(self):
        self.assertEqual(self.query("SELECT code FROM family_code_history"), [(self.current(),)])
        with patch.object(database, "_allocate_family_code", side_effect=database.FamilyCodeTakenError()):
            with self.assertRaises(database.FamilyCodeTakenError):
                self.create("failed")
        self.assertEqual(self.query("SELECT count(*) FROM users WHERE auth_user_id='failed'"), [(0,)])

    def test_creator_only_and_members_unchanged(self):
        with self.connection() as conn:
            parent = conn.execute("INSERT INTO users(name,family_id,auth_user_id,family_role,shortcut_token) VALUES ('parent',%s,'parent','parent','token') RETURNING id", (self.family,)).fetchone()[0]
        before = self.query("SELECT * FROM users ORDER BY id")
        self.assertIsNone(database.regenerate_family_code(parent, self.family))
        self.assertIsNone(database.regenerate_family_code(self.creator, 99999))
        old = self.current()
        self.assertNotEqual(self.regenerate(), old)
        self.assertEqual(self.query("SELECT * FROM users ORDER BY id"), before)
        with self.connection() as conn:
            conn.execute("UPDATE families SET created_by_user_id=NULL WHERE id=%s", (self.family,))
        self.assertIsNone(self.regenerate())

    def test_invalidates_verified_join_preserves_counters_and_lock(self):
        self.session("user_name")
        with self.connection() as conn:
            conn.execute("INSERT INTO pwa_join_sessions(auth_user_id,family_id,step,family_code_attempts,locked_until) VALUES ('locked',%s,'locked',3,NOW()+INTERVAL '15 minutes')", (self.family,))
        locked = self.query("SELECT * FROM pwa_join_sessions WHERE auth_user_id='locked'")
        old = self.current()
        new = self.regenerate()
        self.assertEqual(self.query("SELECT step,family_name_attempts,family_code_attempts FROM pwa_join_sessions WHERE auth_user_id='joiner'"), [("family_code", 1, 1)])
        self.assertEqual(self.query("SELECT * FROM pwa_join_sessions WHERE auth_user_id='locked'"), locked)
        with self.assertRaises(database.InvalidJoinStepError):
            database.complete_pwa_join("joiner", "name")
        self.assertFalse(database.verify_pwa_join_family_code("joiner", old)["success"])
        self.assertTrue(database.verify_pwa_join_family_code("joiner", new)["success"])
        self.assertTrue(database.complete_pwa_join("joiner", "name")["created"])

    def test_regeneration_rollback_restores_code_history_and_session(self):
        self.session("user_name")
        before = self.current()
        with self.connection() as conn:
            conn.execute("ALTER TABLE pwa_join_sessions ADD CHECK (step <> 'family_code')")
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.regenerate()
        self.assertEqual(self.current(), before)
        self.assertEqual(self.query("SELECT code FROM family_code_history"), [(before,)])
        self.assertEqual(self.query("SELECT step FROM pwa_join_sessions"), [("user_name",)])

    def test_concurrent_create_and_regenerations(self):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.regenerate) for _ in range(3)]
            futures += [executor.submit(self.create, f"new{i}") for i in range(2)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.query("SELECT count(*), count(DISTINCT family_code) FROM families"), [(3, 3)])
        self.assertEqual(self.query("SELECT count(*) FROM family_code_history"), [(6,)])

    def ordered(self, first, second, hook_name):
        entered, release = threading.Event(), threading.Event()
        original = getattr(database, hook_name)
        def paused(*args, **kwargs):
            result = original(*args, **kwargs)
            if not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test coordination timeout")
            return result
        with patch.object(database, hook_name, side_effect=paused), ThreadPoolExecutor(max_workers=2) as executor:
            a = executor.submit(first)
            try:
                self.assertTrue(entered.wait(5))
                b = executor.submit(second)
            finally:
                release.set()
            return a.result(timeout=10), b.result(timeout=10)

    def test_verification_before_regeneration_is_invalidated(self):
        self.session()
        old = self.current()
        self.ordered(lambda: database.verify_pwa_join_family_code("joiner", old), self.regenerate, "_lock_pwa_join_session")
        self.assertEqual(self.query("SELECT step FROM pwa_join_sessions"), [("family_code",)])

    def test_regeneration_before_verification_rejects_old_code(self):
        self.session()
        old = self.current()
        _, result = self.ordered(self.regenerate, lambda: database.verify_pwa_join_family_code("joiner", old), "_allocate_family_code")
        self.assertFalse(result["success"])

    def test_completion_before_regeneration_remains_member(self):
        self.session("user_name")
        result, _ = self.ordered(lambda: database.complete_pwa_join("joiner", "name"), self.regenerate, "_lock_pwa_join_session")
        self.assertTrue(result["created"])
        self.assertEqual(self.query("SELECT family_id FROM users WHERE auth_user_id='joiner'"), [(self.family,)])

    def test_regeneration_before_completion_rejects_completion(self):
        self.session("user_name")
        def complete():
            with self.assertRaises(database.InvalidJoinStepError):
                database.complete_pwa_join("joiner", "name")
        self.ordered(self.regenerate, complete, "_allocate_family_code")
        self.assertEqual(self.query("SELECT count(*) FROM users WHERE auth_user_id='joiner'"), [(0,)])
