"""Real PostgreSQL join/evidence transactions; disposable loopback schemas only."""
import os
import threading
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

from deletion_gate import require_auth, IdentityUnavailable
from tests import test_family_address_confirmations as fixtures
database, LEGAL_ACCEPTANCE = fixtures.database, fixtures.LEGAL_ACCEPTANCE

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'supabase/manual_migrations/2026112601_join_location_verification.sql'

@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Isolated PostgreSQL not configured')
class SharedJoinPostgresTests(unittest.TestCase):
    connection = fixtures.FamilyAddressPostgresTests.connection
    drop_schema = fixtures.FamilyAddressPostgresTests.drop_schema
    query = fixtures.FamilyAddressPostgresTests.query
    auth = fixtures.FamilyAddressPostgresTests.auth
    issue = fixtures.FamilyAddressPostgresTests.issue
    create = fixtures.FamilyAddressPostgresTests.create
    family = fixtures.FamilyAddressPostgresTests.family
    update = fixtures.FamilyAddressPostgresTests.update

    def setUp(self):
        fixtures.FamilyAddressPostgresTests.setUp(self)
        self.query('CREATE TABLE account_deletion_jobs(auth_user_id uuid PRIMARY KEY)')
        gate = patch.object(database, 'require_auth', require_auth)
        gate.start(); self.addCleanup(gate.stop)
        baseline = (ROOT / 'supabase/schema_baseline/current_schema.sql').read_text(encoding='utf-8')
        ddl = 'CREATE TABLE public."pwa_join_sessions" (' + baseline.split('CREATE TABLE public."pwa_join_sessions" (',1)[1].split(';',1)[0] + ';'
        self.query(ddl.replace('public.', ''))
        self.query('ALTER TABLE pwa_join_sessions ADD PRIMARY KEY(auth_user_id), ADD FOREIGN KEY(auth_user_id) REFERENCES auth_users(id) ON DELETE CASCADE, ADD FOREIGN KEY(family_id) REFERENCES families(id) ON DELETE SET NULL')
        self.query('ALTER TABLE pwa_join_sessions ENABLE ROW LEVEL SECURITY')
        self.legacy = self.auth()
        self.query("INSERT INTO pwa_join_sessions(auth_user_id,step,family_name,family_code_attempts) VALUES(%s,'family_code','family',2)",(self.legacy,))
        before=self.query("SELECT relrowsecurity,relacl FROM pg_class WHERE oid='pwa_join_sessions'::regclass")
        self.query(MIGRATION.read_text().replace('public.', self.schema+'.').replace('BEGIN;', '').replace('COMMIT;', ''))
        self.assertEqual(before,self.query("SELECT relrowsecurity,relacl FROM pg_class WHERE oid='pwa_join_sessions'::regclass"))
        self.a, self.b = self.family(0,0), self.family(0,0)

    def code(self, family):
        return self.query('SELECT family_code FROM families WHERE id=%s',(family,))[0][0]

    def address(self, auth, lat=0, lon=0):
        database.start_pwa_join_session(auth)
        database.submit_pwa_join_family_name(auth,'family')
        return self.readdress(auth,lat,lon)

    def readdress(self, auth, lat=0, lon=0):
        context=database.precheck_pwa_join_address(auth)
        result=database.submit_pwa_join_address(auth,'typed','resolved',lat,lon,context)
        self.assertTrue(result['success'])
        self.assertIsNone(result['session']['family_id'])
        return database.confirm_pwa_join_address(auth,True)

    def verify(self, auth, family):
        result=database.verify_pwa_join_family_code(auth,self.code(family))
        self.assertTrue(result['success'])
        return result

    def complete(self, auth):
        return database.complete_pwa_join(auth,'member',legal_acceptance=LEGAL_ACCEPTANCE)

    def expire(self, auth):
        self.query("UPDATE pwa_join_sessions SET location_verified_at=statement_timestamp()-INTERVAL '16 minutes', location_verification_expires_at=statement_timestamp()-INTERVAL '1 minute' WHERE auth_user_id=%s",(auth,))

    def test_same_name_same_location_join_each_unique_code(self):
        for family in (self.a[2],self.b[2]):
            auth=self.auth(); state=self.address(auth)
            self.assertIsNone(state['family_id'])
            self.verify(auth,family)
            self.assertEqual(self.complete(auth)['family_id'],family)
            self.assertEqual(self.query('SELECT family_id FROM users WHERE auth_user_id=%s',(auth,)),[(family,)])
            self.assertEqual(self.query('SELECT count(*) FROM pwa_join_sessions WHERE auth_user_id=%s',(auth,)),[(0,)])

    def test_valid_unrelated_codes_and_wrong_code_do_not_grant_membership(self):
        other=self.family(1,1)
        named=self.family(0,0)
        self.query("UPDATE families SET name='other' WHERE id=%s",(named[2],))
        auth=self.auth(); self.address(auth)
        for code in (self.code(other[2]), self.code(named[2]),'!!!!!!'):
            result=database.verify_pwa_join_family_code(auth,code)
            self.assertFalse(result['success'])
        self.assertEqual(result['attempts_remaining'],0)
        with self.assertRaises(database.JoinSessionLockedError): self.complete(auth)
        self.assertEqual(self.query('SELECT count(*) FROM users WHERE auth_user_id=%s',(auth,)),[(0,)])

    def test_expiry_and_reverification_preserve_failed_attempts(self):
        auth=self.auth(); self.address(auth)
        database.verify_pwa_join_family_code(auth,'!!!!!!')
        self.expire(auth)
        with self.assertRaises(database.InvalidJoinStepError): self.verify(auth,self.a[2])
        state=database.start_pwa_join_session(auth)
        self.assertEqual((state['step'],state['family_code_attempts']),('address',1))
        self.assertIsNone(state['verified_latitude'])
        self.readdress(auth)
        self.assertEqual(database.verify_pwa_join_family_code(auth,'!!!!!!')['attempts_remaining'],1)
        self.verify(auth,self.b[2]); self.complete(auth)

    def test_legacy_session_reverifies_without_resetting_attempts(self):
        with self.assertRaises(database.InvalidJoinStepError): self.verify(self.legacy,self.a[2])
        state=database.start_pwa_join_session(self.legacy)
        self.assertEqual((state['step'],state['family_code_attempts']),('address',2))
        self.readdress(self.legacy)
        result=database.verify_pwa_join_family_code(self.legacy,'!!!!!!')
        self.assertEqual(result['attempts_remaining'],0)

    def test_expired_after_code_rejects_completion_and_recovers(self):
        auth=self.auth(); self.address(auth); self.verify(auth,self.a[2]); self.expire(auth)
        with self.assertRaises(database.InvalidJoinStepError): self.complete(auth)
        self.assertEqual(database.start_pwa_join_session(auth)['step'],'address')
        self.readdress(auth); self.verify(auth,self.b[2]); self.complete(auth)

    def test_family_name_or_location_change_revalidated_at_completion(self):
        for field,value in [('name','changed'),('home_latitude',1)]:
            with self.subTest(field=field):
                auth=self.auth(); self.address(auth); self.verify(auth,self.a[2])
                original=self.query(f'SELECT {field} FROM families WHERE id=%s',(self.a[2],))[0][0]
                self.query(f'UPDATE families SET {field}=%s WHERE id=%s',(value,self.a[2]))
                with self.assertRaises(database.InvalidJoinStepError): self.complete(auth)
                self.assertEqual(database.start_pwa_join_session(auth)['step'],'address')
                self.assertEqual(self.query('SELECT count(*) FROM users WHERE auth_user_id=%s',(auth,)),[(0,)])
                self.query(f'UPDATE families SET {field}=%s WHERE id=%s',(original,self.a[2]))

    def test_name_or_location_change_before_code_rejected(self):
        auth=self.auth(); self.address(auth)
        self.query("UPDATE families SET home_latitude=1 WHERE id=%s",(self.a[2],))
        self.assertFalse(database.verify_pwa_join_family_code(auth,self.code(self.a[2]))['success'])

    def test_concurrent_code_verification_and_completion_do_not_duplicate(self):
        auth=self.auth(); self.address(auth)
        barrier=threading.Barrier(2)
        def verify():
            barrier.wait(); return self.verify(auth,self.b[2])
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertTrue(all(r['success'] for r in workers.map(lambda _:verify(),range(2))))
        barrier=threading.Barrier(2)
        def complete():
            barrier.wait()
            try: self.complete(auth); return 'created'
            except database.AuthUserAlreadyMappedError: return 'mapped'
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(lambda _:complete(),range(2))),['created','mapped'])
        self.assertEqual(self.query('SELECT count(*) FROM users WHERE auth_user_id=%s',(auth,)),[(1,)])
        with self.assertRaises(database.AuthUserAlreadyMappedError): self.complete(auth)

    def test_failure_after_membership_insert_rolls_back_and_retry_succeeds(self):
        auth=self.auth(); self.address(auth); self.verify(auth,self.b[2])
        with patch.object(database,'record_legal_acceptance',side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): self.complete(auth)
        self.assertEqual(self.query('SELECT count(*) FROM users WHERE auth_user_id=%s',(auth,)),[(0,)])
        self.assertEqual(self.query('SELECT step FROM pwa_join_sessions WHERE auth_user_id=%s',(auth,)),[('user_name',)])
        self.assertEqual(self.complete(auth)['family_id'],self.b[2])

    def test_deleted_or_deleting_identity_cannot_join(self):
        for deleted in (False, True):
            auth=self.auth(); self.address(auth); self.verify(auth,self.a[2])
            if deleted: self.query('DELETE FROM auth_users WHERE id=%s',(auth,))
            else: self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(auth,))
            with self.assertRaises(IdentityUnavailable): self.complete(auth)

    def test_stale_geocoder_result_cannot_replace_new_context(self):
        auth=self.auth(); self.address(auth)
        context=database.precheck_pwa_join_address(auth)
        database.confirm_pwa_join_address(auth,False)
        with self.assertRaises(database.InvalidJoinStepError):
            database.submit_pwa_join_address(auth,'old','old',0,0,context)

    def test_code_rotation_invalidates_verification(self):
        auth=self.auth(); self.address(auth); self.verify(auth,self.a[2])
        database.regenerate_family_code(self.a[1],self.a[2])
        with self.assertRaises(database.InvalidJoinStepError): self.complete(auth)
        self.assertEqual(database.start_pwa_join_session(auth)['step'],'family_code')
        self.verify(auth,self.a[2]); self.complete(auth)

    def test_start_returns_current_session_when_cleanup_expires_loaded_evidence(self):
        auth = self.auth()
        self.address(auth)
        self.query("UPDATE pwa_join_sessions SET family_code_attempts=2 WHERE auth_user_id=%s", (auth,))
        original = database._lock_pwa_join_session

        def expire_after_loading(conn, identity):
            session = original(conn, identity)
            conn.execute("""UPDATE pwa_join_sessions
                SET location_verified_at=statement_timestamp()-INTERVAL '16 minutes',
                    location_verification_expires_at=statement_timestamp()-INTERVAL '1 minute'
                WHERE auth_user_id=%s""", (identity,))
            return session

        with patch.object(database, '_lock_pwa_join_session', side_effect=expire_after_loading):
            result = database.start_pwa_join_session(auth)
        self.assertEqual(result['step'], 'address')
        self.assertEqual(result['family_code_attempts'], 2)
        self.assertIsNone(result['verified_latitude'])
        self.assertIsNone(result['family_id'])
        self.assertEqual(result, database.start_pwa_join_session(auth))

    def test_expiry_cleanup_keeps_attempts_and_lockout(self):
        auth=self.auth(); self.address(auth); self.expire(auth)
        self.query("UPDATE pwa_join_sessions SET step='locked',family_code_attempts=3,locked_until=clock_timestamp()+INTERVAL '15 minutes' WHERE auth_user_id=%s",(auth,))
        database.start_pwa_join_session(self.auth())
        row=self.query('SELECT step,family_code_attempts,locked_until>clock_timestamp(),verified_latitude FROM pwa_join_sessions WHERE auth_user_id=%s',(auth,))[0]
        self.assertEqual(row,('locked',3,True,None))
        with self.assertRaises(database.JoinSessionLockedError): database.start_pwa_join_session(auth)

    def test_migration_constraints_and_existing_rows(self):
        self.assertEqual(self.query('SELECT family_code_attempts,verified_latitude FROM pwa_join_sessions WHERE auth_user_id=%s',(self.legacy,)),[(2,None)])
        auth=self.auth(); self.address(auth)
        self.assertEqual(self.query("SELECT location_verification_expires_at-location_verified_at=INTERVAL '15 minutes',location_verified_at<=clock_timestamp() FROM pwa_join_sessions WHERE auth_user_id=%s",(auth,)),[(True,True)])
        for assignment in ['verified_latitude=91','verified_longitude=181',"verified_latitude='NaN'",'location_verified_at=NULL',"location_verification_expires_at='infinity'", "location_verification_expires_at=location_verified_at+INTERVAL '16 minutes'"]:
            with self.subTest(assignment=assignment),self.assertRaises(self.psycopg.errors.CheckViolation):
                self.query('UPDATE pwa_join_sessions SET '+assignment+' WHERE auth_user_id=%s',(auth,))

    def test_negative_confirmation_and_name_edit_clear_evidence(self):
        auth=self.auth(); self.address(auth)
        self.assertIsNone(database.confirm_pwa_join_address(auth,False)['verified_latitude'])
        self.readdress(auth)
        self.assertIsNone(database.submit_pwa_join_family_name(auth,'family')['session']['verified_latitude'])

    def test_evidence_columns_are_not_readable_by_client_roles(self):
        for role in ('anon','authenticated'):
            self.query(f'GRANT USAGE ON SCHEMA {self.schema} TO {role}')
            with self.connection() as conn:
                conn.execute(f'SET LOCAL ROLE {role}')
                with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    conn.execute('SELECT verified_latitude FROM pwa_join_sessions')

    def test_cleanup_is_bounded_and_preserves_failed_attempt_history(self):
        self.query("""WITH identities AS (
            INSERT INTO auth_users SELECT gen_random_uuid() FROM generate_series(1,102) RETURNING id
        ) INSERT INTO pwa_join_sessions(auth_user_id,step,family_name,family_code_attempts,
            verified_latitude,verified_longitude,location_verified_at,location_verification_expires_at)
            SELECT id,'family_code','family',2,0,0,statement_timestamp()-INTERVAL '16 minutes',
                   statement_timestamp()-INTERVAL '1 minute' FROM identities""")
        database.start_pwa_join_session(self.auth())
        self.assertEqual(self.query('SELECT count(*) FROM pwa_join_sessions WHERE verified_latitude IS NOT NULL'),[(2,)])
        self.assertEqual(self.query("SELECT count(*) FROM pwa_join_sessions WHERE step='address' AND family_code_attempts=2"),[(100,)])

    def test_concurrent_geocoding_callbacks_only_one_context_is_applied(self):
        auth=self.auth(); database.start_pwa_join_session(auth)
        database.submit_pwa_join_family_name(auth,'family')
        context=database.precheck_pwa_join_address(auth)
        barrier=threading.Barrier(2)
        def apply():
            barrier.wait()
            try:
                database.submit_pwa_join_address(auth,'typed','resolved',0,0,context)
                return 'applied'
            except database.InvalidJoinStepError: return 'stale'
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sorted(workers.map(lambda _:apply(),range(2))),['applied','stale'])
        self.assertIsNone(database.start_pwa_join_session(auth)['family_id'])
