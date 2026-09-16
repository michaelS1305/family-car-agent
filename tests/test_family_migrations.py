from pathlib import Path
import unittest


MIGRATIONS = Path(__file__).resolve().parents[1] / "supabase" / "manual_migrations"


class FamilyMigrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expand = (MIGRATIONS / "2026090601_family_roles_expand.sql").read_text(
            encoding="utf-8"
        )
        cls.contract = (MIGRATIONS / "2026090602_family_creator_contract.sql").read_text(
            encoding="utf-8"
        )

    def test_expand_guards_exact_legacy_state_and_scopes_backfill(self):
        self.assertIn("expected exactly 1 legacy family", self.expand)
        self.assertIn("expected exactly 2 legacy users", self.expand)
        self.assertIn("WHERE id = 1", self.expand)
        self.assertIn("WHERE id = legacy_family_id", self.expand)
        self.assertNotIn("UPDATE public.families\n    SET created_by_user_id = 1;", self.expand)

    def test_expand_adds_public_refs_roles_and_nullable_creator(self):
        self.assertIn("ADD COLUMN family_role text NULL", self.expand)
        self.assertIn("ADD COLUMN member_public_id uuid DEFAULT gen_random_uuid()", self.expand)
        self.assertIn("ALTER COLUMN member_public_id SET NOT NULL", self.expand)
        self.assertIn("UNIQUE (member_public_id)", self.expand)
        self.assertIn("ADD COLUMN created_by_user_id integer NULL", self.expand)
        self.assertIn("ON DELETE RESTRICT", self.expand)
        self.assertNotIn("created_by_user_id SET NOT NULL", self.expand)

    def test_contract_checks_all_invariants_before_not_null(self):
        for invariant in (
            "created_by_user_id IS NULL",
            "creator does not exist",
            "creator does not belong",
            "member_public_id is null",
            "duplicate member_public_id",
            "invalid family_role",
        ):
            self.assertIn(invariant, self.contract)
        self.assertLess(
            self.contract.index("DO $preflight$"),
            self.contract.index("ALTER COLUMN created_by_user_id SET NOT NULL"),
        )


class FamilyCodeHistoryMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (MIGRATIONS / "2026091601_family_code_history.sql").read_text(
            encoding="utf-8"
        )

    def test_validation_precedes_creation_and_backfill_under_lock(self):
        sql = self.sql
        self.assertLess(sql.index("BEGIN;"), sql.index("DO $preflight$"))
        self.assertLess(sql.index("LOCK TABLE"), sql.index("octet_length(family_code)"))
        self.assertLess(sql.index("octet_length(family_code)"), sql.index("CREATE TABLE"))
        self.assertLess(sql.index("CREATE TABLE"), sql.index("INSERT INTO"))
        for guard in (
            "attnotnull", "atttypid = 'text'::regtype", "contype = 'u'",
            "conkey = ARRAY[code_attribute]", "convalidated",
            "to_regclass('public.family_code_history') IS NOT NULL",
            'family_code COLLATE "C" ~ \'^[a-z0-9]{6}$\'',
        ):
            self.assertIn(guard, sql)
        self.assertIn("SELECT family_code FROM public.families;", sql)
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))

    def test_persistent_registry_is_minimal_and_backend_only(self):
        sql = self.sql
        self.assertIn('code text COLLATE "C" PRIMARY KEY', sql)
        self.assertIn("octet_length(code) = 6 AND code ~ '^[a-z0-9]{6}$'", sql)
        self.assertIn("REVOKE ALL PRIVILEGES (code)", sql)
        self.assertEqual(sql.count("FROM PUBLIC, anon, authenticated;"), 2)
        statements = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        for forbidden in (
            "REFERENCES", "ALTER TABLE", "UPDATE ", "DELETE ", "TRUNCATE ",
            "CREATE TRIGGER", "CREATE POLICY", "ROW LEVEL SECURITY",
            "DEFAULT PRIVILEGES", "2026090602", "created_by_user_id",
            "pwa_join_sessions", "ON CONFLICT",
        ):
            self.assertNotIn(forbidden, statements)


if __name__ == "__main__":
    unittest.main()
