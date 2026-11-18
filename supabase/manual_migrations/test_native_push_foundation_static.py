"""Offline structural checks only; no SQL execution or database imports."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
SQL = (ROOT / "2026101801_native_push_foundation.sql").read_text(encoding="utf-8")
VERIFY = (ROOT / "2026101801_native_push_verify.sql").read_text(encoding="utf-8")
CHECKPOINT = (ROOT.parent / "bootstrap/2026-09-30/current_schema.sql").read_text(encoding="utf-8")


class NativePushStaticTest(unittest.TestCase):
    def test_four_tables_only(self):
        self.assertEqual(re.findall(r"CREATE TABLE public\.(\w+)", SQL), [
            "native_push_installations", "native_push_registration_challenges",
            "native_push_events", "native_push_deliveries"])

    def test_existing_composite_target(self):
        self.assertIn('UNIQUE (event_id, user_id, vehicle_id, family_id)', CHECKPOINT)
        self.assertIn('REFERENCES public.vehicle_events(event_id,user_id,vehicle_id,family_id) ON DELETE CASCADE', SQL)
        self.assertEqual(SQL.count('REFERENCES public.native_push_installations(installation_ref,user_id) ON DELETE CASCADE'), 2)

    def test_no_legacy_ddl_or_privilege_changes(self):
        self.assertNotRegex(SQL, r'(?i)\b(?:ALTER|DROP|TRUNCATE) TABLE public\.(?:users|vehicle_events|push_subscriptions|registered_devices)\b')
        self.assertNotRegex(SQL, r'(?im)^\s*(?:GRANT|CREATE EXTENSION|CREATE FUNCTION|CREATE TRIGGER|ALTER DEFAULT PRIVILEGES)\b')

    def test_atomic_and_fail_closed(self):
        self.assertEqual(len(re.findall(r'^BEGIN;', SQL, re.M)), 1)
        self.assertTrue(SQL.rstrip().endswith('COMMIT;'))
        self.assertIn('i.indisvalid AND i.indisready', SQL)
        self.assertIn('puballtables', SQL)
        self.assertIn('rolbypassrls', SQL)

    def test_security(self):
        self.assertIn('FROM PUBLIC, anon, authenticated, service_role', SQL)
        self.assertIn('REVOKE ALL PRIVILEGES (%s)', SQL)
        self.assertIn('ENABLE ROW LEVEL SECURITY', SQL)
        self.assertIn('has_any_column_privilege', SQL)

    def test_uniqueness_and_ttl(self):
        self.assertIn("WHERE status='active'", SQL)
        self.assertIn("ON public.native_push_registration_challenges(installation_ref) WHERE status='pending'", SQL)
        self.assertIn('UNIQUE (source_event_id,event_type)', SQL)
        self.assertIn('UNIQUE (event_ref,installation_ref)', SQL)
        self.assertIn("expires_at=occurred_at+INTERVAL '5 minutes'", SQL)
        self.assertNotRegex(SQL, r'UNIQUE\s*\([^)]*candidate_fingerprint')
        self.assertNotRegex(SQL, r'CREATE UNIQUE INDEX[^;]*candidate_fingerprint')

    def test_new_files_have_no_trailing_whitespace(self):
        for path in ROOT.glob('2026101801_native_push*'):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                self.assertEqual(line, line.rstrip(), f'{path.name}:{number}')

    def test_verification_read_only(self):
        self.assertIn('BEGIN READ ONLY;', VERIFY)
        self.assertNotRegex(VERIFY, r'(?im)^\s*(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|REVOKE|DO)\b')


if __name__ == '__main__':
    unittest.main()
