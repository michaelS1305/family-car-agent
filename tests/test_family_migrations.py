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


if __name__ == "__main__":
    unittest.main()
