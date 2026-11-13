"""Real local PostgreSQL transactions; reuse the loopback-only fixture guard."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import unittest
from uuid import uuid4

from tests import test_native_push as fixtures
CONFIG = fixtures.CONFIG
import native_push_registration as registration
import native_push_revocation as revocation
import native_push_worker as worker


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'),'Requires disposable local PostgreSQL')
class IosPostgresTests(unittest.TestCase):
    # Reuse setup, not the unrelated inherited test cases.
    connection=fixtures.PostgresTests.connection
    query=fixtures.PostgresTests.query
    cleanup=fixtures.PostgresTests.cleanup
    nonce=fixtures.PostgresTests.nonce
    confirm=fixtures.PostgresTests.confirm

    def setUp(self):
        fixtures.PostgresTests.setUp(self)
        source=(Path(__file__).resolve().parents[2]/'supabase/manual_migrations/2026111201_native_push_ios_revocation.sql').read_text()
        executor=self.query('SELECT current_user')[0][0]
        self.assertIn(executor,('postgres','gemini_test'))
        self.query("DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;"
                   "IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;"
                   "IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF; END $$")
        with self.connection() as conn:
            conn.execute(source.replace('public.',self.schema+'.').replace("'public'::regnamespace", "'"+self.schema+"'::regnamespace")
                         .replace("current_user <> 'postgres'", "current_user <> '"+executor+"'"))

    def test_migration_denies_client_access_and_enables_rls(self):
        self.assertTrue(self.query("SELECT relrowsecurity FROM pg_class WHERE oid='native_push_ios_revocations'::regclass")[0][0])
        for role in ('anon','authenticated','service_role'):
            self.assertFalse(self.query("SELECT has_table_privilege(%s,'native_push_ios_revocations','SELECT,INSERT,UPDATE,DELETE')",(role,))[0][0])

    def prepare(self,ref=None,secret='a'*64):
        ref=ref or uuid4()
        with self.connection() as conn:
            reply=revocation.prepare(conn,self.users[2],CONFIG,ref,secret)
        return ref,reply

    def begin(self,ref,request=None,token=None):
        with self.connection() as conn:
            return registration.begin(conn,self.users[2],CONFIG,installation_ref=ref,
                request_id=request or uuid4(),platform='ios',token=token or 'synthetic-'+uuid4().hex)

    def cancel(self,ref,secret='a'*64):
        with self.connection() as conn:
            return revocation.cancel(conn,CONFIG,ref,secret)

    def age_rate_window(self):
        # Simulated passage of time only in this isolated test schema.
        self.query("UPDATE native_push_ios_revocations SET created_at=clock_timestamp()-interval '11 minutes'")
        self.query("UPDATE native_push_registration_challenges SET created_at=clock_timestamp()-interval '11 minutes'")

    def test_repeated_login_logout_keeps_tombstones_without_exhausting_ios_quota(self):
        for _ in range(22):
            self.age_rate_window()
            ref,reply=self.prepare(); self.assertEqual(reply['code'],'PREPARED')
            reply=self.begin(ref); self.assertEqual(reply['code'],'CHALLENGE_PENDING')
            challenge=reply['challenge_ref']
            self.assertEqual(self.confirm(ref,challenge,self.nonce(challenge))['code'],'ACTIVE')
            self.assertEqual(self.cancel(ref)['code'],'REVOKED')
            self.assertEqual(self.begin(ref)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_installations')[0][0],22)
        self.assertEqual(self.query('SELECT count(*) FROM native_push_ios_revocations WHERE revoked_at IS NOT NULL')[0][0],22)
        with self.connection() as conn:
            # Android's original count of ALL rows is intentionally unchanged.
            reply=registration.begin(conn,self.users[2],CONFIG,installation_ref=uuid4(),request_id=uuid4(),
                                     platform='android',token='synthetic-android-token')
        self.assertEqual(reply['code'],'INSTALLATION_LIMIT')

    def test_prepare_rate_limit_survives_cancellation(self):
        for _ in range(10):
            ref,reply=self.prepare(); self.assertEqual(reply['code'],'PREPARED'); self.cancel(ref)
        self.assertEqual(self.prepare()[1]['code'],'RATE_LIMITED')
        self.age_rate_window()
        self.assertEqual(self.prepare()[1]['code'],'PREPARED')

    def test_prepared_and_active_installations_cannot_exceed_twenty(self):
        for _ in range(20):
            self.age_rate_window()
            ref,reply=self.prepare(); self.assertEqual(reply['code'],'PREPARED')
            result=self.begin(ref); challenge=result['challenge_ref']
            self.confirm(ref,challenge,self.nonce(challenge))
        self.age_rate_window()
        self.assertEqual(self.prepare()[1]['code'],'INSTALLATION_LIMIT')

    def test_cancel_before_begin_and_lost_cancel_reply(self):
        ref,_=self.prepare()
        for _ in range(2): self.assertEqual(self.cancel(ref)['code'],'REVOKED')
        self.assertEqual(self.begin(ref)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.prepare(ref)[1]['code'],'REGISTRATION_UNAVAILABLE')

    def test_cancel_vs_confirmation_and_rotation(self):
        for _ in range(5):
            self.age_rate_window()
            ref,_=self.prepare(); reply=self.begin(ref)
            challenge=reply['challenge_ref']; nonce=self.nonce(challenge)
            with ThreadPoolExecutor(max_workers=2) as executor:
                a=executor.submit(self.confirm,ref,challenge,nonce)
                b=executor.submit(self.cancel,ref)
                a.result(); self.assertEqual(b.result()['code'],'REVOKED')
            self.assertEqual(self.query('SELECT status FROM native_push_installations WHERE installation_ref=%s',(ref,))[0][0],'revoked')
            self.assertEqual(self.confirm(ref,challenge,nonce)['code'],'REGISTRATION_UNAVAILABLE')
            self.assertEqual(self.begin(ref,token='synthetic-rotated-token')['code'],'REGISTRATION_UNAVAILABLE')

    def test_capability_cannot_cancel_another_installation(self):
        ref,_=self.prepare()
        self.assertEqual(self.cancel(ref,'b'*64)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.begin(ref)['code'],'CHALLENGE_PENDING')

    def test_prepared_only_authorities_count_and_rotation_does_not_add_installations(self):
        ref,_=self.prepare()
        for token in ('synthetic-first-token','synthetic-rotated-token'):
            reply=self.begin(ref,token=token); challenge=reply['challenge_ref']
            self.assertEqual(self.confirm(ref,challenge,self.nonce(challenge))['code'],'ACTIVE')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_installations')[0][0],1)
        for _ in range(19):
            self.age_rate_window()
            self.assertEqual(self.prepare()[1]['code'],'PREPARED')
        self.age_rate_window()
        self.assertEqual(self.prepare()[1]['code'],'INSTALLATION_LIMIT')
        self.cancel(ref)
        self.assertEqual(self.prepare()[1]['code'],'PREPARED')

    def test_rich_delivery_is_authorized_and_revocation_blocks_claimed_payload(self):
        self.query("ALTER TABLE users ADD COLUMN name text NOT NULL DEFAULT 'Synthetic member'")
        self.query("ALTER TABLE vehicles ADD COLUMN display_name text NOT NULL DEFAULT 'Synthetic vehicle'")
        ref,_=self.prepare(); result=self.begin(ref); challenge=result['challenge_ref']
        self.confirm(ref,challenge,self.nonce(challenge))
        # Reuse the existing event producer, then exercise the real payload query.
        self.event = lambda conn, *args: fixtures.PostgresTests.event(self,conn,*args)
        fixtures.PostgresTests.produce(self)
        claim=worker.claim_delivery(self,CONFIG.project)
        self.assertIsNotNone(claim)
        payload=worker.delivery_payload(self,CONFIG,claim)
        self.assertEqual(payload[3],'ios')
        self.assertEqual(payload[1]['installation_ref'],str(ref))
        self.assertIn('Synthetic vehicle',payload[1]['alert']['body'])
        self.assertIn('Synthetic member',payload[1]['alert']['body'])
        self.cancel(ref)
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
