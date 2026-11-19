"""Opt-in disposable local PostgreSQL tests; never run the manual migration."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from legal_acceptance import record_legal_acceptance
from tests import test_family_address_confirmations as address_fixture

database = address_fixture.database
from tests.test_legal_acceptance import ACCEPTANCE


@unittest.skipUnless(os.environ.get("GEMINI_TEST_DATABASE_URL"), "Isolated local PostgreSQL not configured")
class LegalAcceptancePostgresTests(unittest.TestCase):
    def setUp(self):
        # Existing fixture enforces localhost and /test_gemini before connecting.
        self.fixture = address_fixture.FamilyAddressPostgresTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.connection = self.fixture.connection
        self.auth = uuid4()
        with self.connection() as conn:
            conn.execute("INSERT INTO auth_users(id) VALUES (%s)", (self.auth,))
            conn.execute("DROP TABLE legal_acceptances")
            migration = (Path(__file__).parents[2] / "supabase/manual_migrations/2026111901_legal_acceptances.sql").read_text()
            # Only table DDL is adapted to the isolated fixture schema. No public/auth mutations.
            ddl = migration.split("CREATE TABLE public.legal_acceptances", 1)[1].split(";", 1)[0]
            conn.execute("CREATE TABLE legal_acceptances" + ddl.replace("auth.users", "auth_users"))
            conn.execute("ALTER TABLE legal_acceptances ENABLE ROW LEVEL SECURITY")
            conn.execute("REVOKE ALL ON legal_acceptances FROM PUBLIC")

    def test_concurrent_duplicates_preserve_server_timestamp_and_cascade(self):
        def record(_):
            with self.connection() as conn:
                record_legal_acceptance(conn, self.auth, ACCEPTANCE)
                return conn.execute("SELECT accepted_at FROM legal_acceptances").fetchone()[0]
        with ThreadPoolExecutor(max_workers=4) as executor:
            times = list(executor.map(record, range(4)))
        self.assertEqual(len(set(times)), 1)
        with self.connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM legal_acceptances").fetchone()[0], 1)
            self.assertLessEqual(times[0], conn.execute("SELECT clock_timestamp()").fetchone()[0])
            with self.assertRaises(self.fixture.psycopg.errors.ForeignKeyViolation):
                with conn.transaction():
                    record_legal_acceptance(conn, uuid4(), ACCEPTANCE)
            conn.execute("DELETE FROM auth_users WHERE id=%s", (self.auth,))
            self.assertEqual(conn.execute("SELECT count(*) FROM legal_acceptances").fetchone()[0], 0)

    def test_no_client_policy_and_rls_denies_nonowner(self):
        role = "legal_test_" + uuid4().hex
        sql = self.fixture.sql
        # Transactional role fixture is rolled back, including grants and the role itself.
        with self.fixture.psycopg.connect(self.fixture.dsn, connect_timeout=3) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.fixture.schema)))
            try:
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
                conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(self.fixture.schema), sql.Identifier(role)))
                self.assertTrue(conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid='legal_acceptances'::regclass").fetchone()[0])
                self.assertEqual(conn.execute("SELECT count(*) FROM pg_policy WHERE polrelid='legal_acceptances'::regclass").fetchone()[0], 0)
                self.assertFalse(conn.execute("SELECT has_table_privilege(%s, 'legal_acceptances', 'INSERT')", (role,)).fetchone()[0])
                # Even an accidental table grant cannot bypass RLS without a policy.
                conn.execute(sql.SQL("GRANT SELECT, INSERT ON legal_acceptances TO {}").format(sql.Identifier(role)))
                with self.assertRaises(self.fixture.psycopg.errors.InsufficientPrivilege):
                    with conn.transaction():
                        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                        record_legal_acceptance(conn, self.auth, ACCEPTANCE)
            finally:
                conn.rollback()

    def test_create_and_join_persist_or_roll_back_together(self):
        for creating in (True, False):
            for fail in (True, False):
                auth = uuid4()
                with self.connection() as conn:
                    conn.execute("INSERT INTO auth_users VALUES (%s)", (auth,))
                    if not creating:
                        # Fixture family exists independently of onboarding under test.
                        conn.execute("ALTER TABLE families ALTER COLUMN created_by_user_id DROP NOT NULL")
                        family = conn.execute("INSERT INTO families(name,family_code,home_address) VALUES ('Fixture',%s,'address') RETURNING id", (uuid4().hex[:6],)).fetchone()[0]
                        conn.execute("CREATE TABLE IF NOT EXISTS pwa_join_sessions(auth_user_id uuid PRIMARY KEY)")
                        conn.execute("INSERT INTO pwa_join_sessions VALUES (%s)", (auth,))
                def write(conn, identity, acceptance):
                    record_legal_acceptance(conn, identity, acceptance)
                    if fail:
                        raise RuntimeError("synthetic failure after insert")
                with patch.object(database, "record_legal_acceptance", side_effect=write), \
                     patch.object(database, "_lock_pwa_join_session", return_value={"step": "user_name", "family_id": family if not creating else 0}):
                    def complete():
                        if creating:
                            return database.create_family_with_first_user("Family", "address", "Name", auth_user_id=auth, legal_acceptance=ACCEPTANCE)
                        return database.complete_pwa_join(auth, "Name", legal_acceptance=ACCEPTANCE)
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                            complete()
                    else:
                        complete()
                with self.connection() as conn:
                    for table in ("users", "legal_acceptances"):
                        self.assertEqual(conn.execute(f"SELECT count(*) FROM {table} WHERE auth_user_id=%s", (auth,)).fetchone()[0], 0 if fail else 1)
                    if not creating:
                        self.assertEqual(conn.execute("SELECT count(*) FROM pwa_join_sessions WHERE auth_user_id=%s", (auth,)).fetchone()[0], 1 if fail else 0)


if __name__ == "__main__":
    unittest.main()
