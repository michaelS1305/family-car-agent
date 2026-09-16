"""Static migration contract only. No connection, SQL execution or application import."""
from pathlib import Path
import re
import unittest


class AccountDeletionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (Path(__file__).resolve().parents[1] /
                   "supabase/manual_migrations/2026091603_account_deletion_jobs.sql").read_text(encoding="utf-8")
        cls.statements = "\n".join(line for line in cls.sql.splitlines()
                                   if not line.lstrip().startswith("--"))
        cls.table = cls.statements.split("CREATE TABLE public.account_deletion_jobs (", 1)[1].split("\n);", 1)[0]

    def test_transactional_strict_preflight(self):
        self.assertTrue(self.statements.strip().startswith("BEGIN;"))
        self.assertTrue(self.statements.strip().endswith("COMMIT;"))
        self.assertLess(self.sql.index("END\n$preflight$;"), self.sql.index("CREATE TABLE"))
        for required in ("current_user <> 'postgres'", "pg_roles", "rolname = 'anon'",
                         "rolname = 'authenticated'", "relkind IN ('r', 'p')",
                         "format_type(atttypid, atttypmod)", "attnotnull", "NOT attisdropped",
                         "('auth.users', 'id', 'uuid', true)",
                         "('public.families', 'created_by_user_id', 'integer', true)"):
            self.assertIn(required, self.statements)

    def test_exact_minimal_columns_and_states(self):
        columns = re.findall(r"^    (\w+) (uuid|text|timestamptz)\b", self.table, re.MULTILINE)
        self.assertEqual(columns, [("auth_user_id", "uuid"), ("phase", "text"),
                                   ("created_at", "timestamptz"), ("next_attempt_at", "timestamptz")])
        self.assertIn("auth_user_id uuid PRIMARY KEY", self.table)
        self.assertIn("phase text NOT NULL DEFAULT 'draining'", self.table)
        self.assertIn("phase IN ('draining', 'auth_pending')", self.table)
        self.assertIn("next_attempt_at >= created_at", self.table)
        for column in ("created_at", "next_attempt_at"):
            self.assertIn(f"{column} timestamptz NOT NULL DEFAULT clock_timestamp()", self.table)
            self.assertIn(f"isfinite({column})", self.table)

    def test_survives_identity_deletion_and_has_no_payload(self):
        for forbidden in ("REFERENCES", "FOREIGN KEY", "ON DELETE", "json", "email",
                          "family_id", "user_id integer", "address", "token", "error_message"):
            self.assertNotIn(forbidden, self.table)

    def test_acl_and_no_browser_or_default_privilege_changes(self):
        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE public.account_deletion_jobs", self.statements)
        self.assertIn("REVOKE ALL PRIVILEGES (auth_user_id, phase, created_at, next_attempt_at)", self.statements)
        self.assertEqual(self.statements.count("FROM PUBLIC, anon, authenticated;"), 2)
        for forbidden in ("GRANT ", "CREATE POLICY", "ROW LEVEL SECURITY", "ALTER DEFAULT PRIVILEGES"):
            self.assertNotIn(forbidden, self.statements)

    def test_conflicting_objects_and_no_silent_rerun(self):
        for name in ("account_deletion_jobs", "account_deletion_jobs_pkey", "account_deletion_jobs_next_attempt_idx"):
            self.assertIn(f"'{name}'", self.statements)
        self.assertIn("to_regclass('public.' || object_name) IS NOT NULL", self.statements)
        self.assertNotIn("IF NOT EXISTS", self.statements[self.statements.index("CREATE TABLE"):])
        self.assertIn("ON public.account_deletion_jobs (next_attempt_at, auth_user_id)", self.statements)

    def test_additive_only_no_backfill_or_existing_schema_mutation(self):
        self.assertEqual(self.statements.count("CREATE TABLE "), 1)
        self.assertEqual(self.statements.count("CREATE INDEX "), 1)
        for forbidden in ("ALTER TABLE", "INSERT INTO", "DELETE FROM", "UPDATE public.",
                          "DROP ", "TRUNCATE ", "CREATE FUNCTION", "CREATE TRIGGER"):
            self.assertNotIn(forbidden, self.statements)


if __name__ == "__main__":
    unittest.main()
