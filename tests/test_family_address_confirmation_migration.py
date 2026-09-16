"""Static contracts only: never connects to a database or executes SQL."""
from pathlib import Path
import unittest


class FamilyAddressConfirmationMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = (Path(__file__).resolve().parents[1] / 'supabase/manual_migrations/'
                   '2026091602_family_address_confirmations.sql').read_text(encoding='utf-8')
        cls.statements = '\n'.join(line for line in cls.sql.splitlines()
                                   if not line.lstrip().startswith('--'))

    def test_transaction_preflight_and_no_silent_rerun(self):
        self.assertLess(self.sql.index('BEGIN;'), self.sql.index('DO $preflight$'))
        self.assertLess(self.sql.index('END\n$preflight$;'), self.sql.index('CREATE TABLE'))
        self.assertTrue(self.sql.rstrip().endswith('COMMIT;'))
        for required in ("current_user <> 'postgres'", "relkind IN ('r', 'p')",
                         'format_type(atttypid, atttypmod)', 'require_not_null',
                         "to_regclass('public.' || object_name)"):
            self.assertIn(required, self.sql)
        self.assertNotIn('IF NOT EXISTS', self.sql[self.sql.index('CREATE TABLE'):])

    def test_digest_payload_purpose_and_expiration(self):
        for contract in (
            'token_digest bytea PRIMARY KEY CHECK (octet_length(token_digest) = 32)',
            "purpose IN ('create_family', 'family_address_update')",
            "normalized_address text NOT NULL CHECK (btrim(normalized_address) <> '')",
            'latitude BETWEEN -90 AND 90', 'longitude BETWEEN -180 AND 180',
            "clock_timestamp() + INTERVAL '15 minutes'", 'isfinite(expires_at)',
            'ON public.family_address_confirmations (expires_at)',
        ):
            self.assertIn(contract, self.sql)
        self.assertNotIn('raw_token', self.statements)

    def test_identity_types_cascades_and_binding(self):
        for contract in (
            'auth_user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE',
            'user_id integer REFERENCES public.users(id) ON DELETE CASCADE',
            'family_id integer REFERENCES public.families(id) ON DELETE CASCADE',
            "purpose = 'create_family' AND user_id IS NULL AND family_id IS NULL",
            "purpose = 'family_address_update' AND user_id IS NOT NULL AND family_id IS NOT NULL",
        ):
            self.assertIn(contract, self.sql)
        self.assertEqual(self.statements.count('ON DELETE CASCADE'), 3)

    def test_replacement_keys_and_security(self):
        self.assertEqual(self.sql.count('CREATE UNIQUE INDEX'), 2)
        self.assertIn("(auth_user_id) WHERE purpose = 'create_family'", self.sql)
        self.assertIn("(user_id) WHERE purpose = 'family_address_update'", self.sql)
        self.assertEqual(self.sql.count('FROM PUBLIC, anon, authenticated;'), 2)
        self.assertIn('REVOKE ALL PRIVILEGES (', self.sql)
        for forbidden in ('GRANT ', 'CREATE POLICY', 'ROW LEVEL SECURITY', 'DEFAULT PRIVILEGES'):
            self.assertNotIn(forbidden, self.statements)

    def test_additive_no_backfill_or_other_objects(self):
        self.assertEqual(self.sql.count('CREATE TABLE '), 1)
        for forbidden in ('ALTER TABLE', 'INSERT INTO', 'UPDATE public.', 'DELETE FROM',
                          'DROP ', 'TRUNCATE ', '2026090602', '2026091601',
                          'geocoding_', 'pwa_join_sessions', 'family_code_history'):
            self.assertNotIn(forbidden, self.statements)


if __name__ == '__main__':
    unittest.main()
