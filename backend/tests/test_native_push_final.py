"""Focused refresh/retention database tests using the existing disposable fixture."""
from datetime import timedelta
import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from deletion_gate import IdentityUnavailable
from native_push_refresh import events, RefreshError
from native_push_cleanup import cleanup
from native_push_fcm import Result
import native_push_worker as worker
from tests import test_native_push as fixture


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'Requires disposable local PostgreSQL')
class InboxTests(unittest.TestCase):
    connection = fixture.PostgresTests.connection
    query = fixture.PostgresTests.query
    cleanup = fixture.PostgresTests.cleanup
    begin = fixture.PostgresTests.begin
    nonce = fixture.PostgresTests.nonce
    confirm = fixture.PostgresTests.confirm
    activate = fixture.PostgresTests.activate
    event = fixture.PostgresTests.event
    produce = fixture.PostgresTests.produce

    def setUp(self):
        fixture.PostgresTests.setUp(self)
        self.query('CREATE TABLE families(id integer PRIMARY KEY)')
        self.query('INSERT INTO families VALUES(10),(20)')
        self.query("ALTER TABLE users ADD COLUMN name text NOT NULL DEFAULT 'Actor'")
        self.query("ALTER TABLE vehicles ADD COLUMN display_name text NOT NULL DEFAULT 'Car'")
        self.installation = self.activate()
        self.ref, _ = self.produce()

    def fetch(self, **kwargs):
        with self.connection() as conn:
            return events(conn, kwargs.pop('user', self.users[2]), fixture.CONFIG,
                          kwargs.pop('installation', self.installation), kwargs.pop('generation', 2), **kwargs)

    def test_valid_exact_response_and_delivery_status_independence(self):
        item = self.fetch()['items'][0]
        self.assertEqual(set(item), {'event_ref','type','occurred_at','expires_at','actor_name','vehicle_ref','vehicle_name'})
        self.assertEqual(item['type'], 'vehicle_taken')
        claim = worker.claim_delivery(self, fixture.CONFIG.project)
        worker.finish_delivery(self, claim, Result('transport_uncertain'))
        self.assertEqual(len(self.fetch()['items']), 1)
        self.query("UPDATE native_push_events SET status='complete'")
        self.assertEqual(len(self.fetch()['items']), 1)

    def test_foreign_missing_stale_and_revoked_have_same_error(self):
        errors = []
        for args in ({'user':self.users[3]}, {'installation':uuid4()}, {'generation':1}):
            with self.assertRaises(RefreshError) as caught:
                self.fetch(**args)
            errors.append(caught.exception.code)
        with self.connection() as conn:
            fixture.registration.revoke(conn,self.users[2],fixture.CONFIG,self.installation,2)
        with self.assertRaises(RefreshError) as caught:
            self.fetch()
        self.assertEqual(errors + [caught.exception.code], ['NATIVE_PUSH_ACCESS_DENIED']*4)

    def test_recipient_family_change_and_deletion_denied(self):
        self.query('UPDATE users SET family_id=20 WHERE id=2')
        with self.assertRaises(IdentityUnavailable): self.fetch()
        self.query('UPDATE users SET family_id=10 WHERE id=2')
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(self.users[2].auth_user_id,))
        with self.assertRaises(IdentityUnavailable): self.fetch()

    def test_deleting_recipient_fences_payload_and_cascades_installations(self):
        # The account-deletion job is the immediate gate; eventual user cleanup
        # removes installations/deliveries without deleting a different member.
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)', (self.users[2].auth_user_id,))
        with self.assertRaises(IdentityUnavailable):
            self.fetch()
        self.query('DELETE FROM users WHERE id=2')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_installations WHERE user_id=2'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries WHERE recipient_user_id=2'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM users WHERE id=1'), [(1,)])

    def test_actor_changes_hide_event(self):
        self.query('UPDATE users SET family_id=20 WHERE id=1')
        self.assertEqual(self.fetch()['items'], [])
        self.query('UPDATE users SET family_id=10 WHERE id=1')
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(self.users[1].auth_user_id,))
        self.assertEqual(self.fetch()['items'], [])

    def test_source_and_user_deletion_cascades(self):
        self.query('DELETE FROM vehicle_events WHERE user_id=1')
        self.query('DELETE FROM users WHERE id=1')
        self.assertEqual(self.fetch()['items'], [])
        self.query('DELETE FROM users WHERE id=2')
        with self.assertRaises(IdentityUnavailable): self.fetch()
        self.assertEqual(self.query('SELECT count(*) FROM native_push_installations'),[(0,)])

    def test_accepted_delivery_is_fetchable(self):
        claim=worker.claim_delivery(self,fixture.CONFIG.project)
        worker.finish_delivery(self,claim,Result('accepted'))
        self.assertEqual(len(self.fetch()['items']),1)

    def test_rotated_generation_cannot_fetch_old_delivery(self):
        _,result=self.begin(installation=self.installation,token='rotated-'+uuid4().hex)
        self.confirm(self.installation,result['challenge_ref'],self.nonce(result['challenge_ref']))
        with self.assertRaises(RefreshError): self.fetch()
        self.assertEqual(self.fetch(generation=3)['items'],[])

    def test_vehicle_mismatch_cancelled_and_expired_hidden(self):
        self.query('UPDATE vehicles SET family_id=20')
        self.assertEqual(self.fetch()['items'], [])
        self.query('UPDATE vehicles SET family_id=10')
        self.query("UPDATE native_push_events SET status='cancelled'")
        self.assertEqual(self.fetch()['items'], [])
        self.query("UPDATE native_push_events SET status='complete',occurred_at=statement_timestamp()-interval '5 minutes',expires_at=statement_timestamp()")
        self.assertEqual(self.fetch()['items'], [])

    def test_cursor_and_late_first_page(self):
        self.produce(age=10)
        first = self.fetch(limit=1)
        second = self.fetch(limit=1,cursor=first['next_cursor'])
        self.assertNotEqual(first['items'][0]['event_ref'],second['items'][0]['event_ref'])
        with self.assertRaises(RefreshError) as caught: self.fetch(cursor=uuid4())
        self.assertEqual(caught.exception.code,'INVALID_NATIVE_PUSH_CURSOR')
        self.produce(age=1)
        self.assertEqual(len(self.fetch()['items']),3)

    def test_new_installation_cannot_inherit_events_or_cursor(self):
        other = self.activate()
        self.assertEqual(self.fetch(installation=other)['items'],[])
        cursor=self.fetch()['items'][0]['event_ref']
        with self.assertRaises(RefreshError): self.fetch(installation=other,cursor=cursor)
        self.produce()
        self.assertEqual(len(self.fetch(installation=other)['items']),1)

    def test_cleanup_preserves_recent_and_installation(self):
        cleanup(self)
        self.assertEqual(len(self.fetch()['items']),1)
        self.assertEqual(self.query('SELECT status,token_ciphertext IS NOT NULL FROM native_push_installations'),[('active',True)])

    def age_event(self, days):
        self.query("UPDATE native_push_events SET occurred_at=statement_timestamp()-(%s*interval '1 day')-interval '5 minutes',"
                   "expires_at=statement_timestamp()-(%s*interval '1 day')", (days,days))

    def test_cleanup_seven_days_and_terminal_time(self):
        claim=worker.claim_delivery(self,fixture.CONFIG.project)
        worker.finish_delivery(self,claim,Result('transport_uncertain'))
        self.age_event(8)
        cleanup(self)  # recent terminal transition protects row
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(1,)])
        self.query("UPDATE native_push_deliveries SET created_at=clock_timestamp()-interval '10 days',updated_at=clock_timestamp()-interval '8 days'")
        cleanup(self)
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(0,)])

    def test_inside_retention_boundary_is_preserved(self):
        claim=worker.claim_delivery(self,fixture.CONFIG.project)
        worker.finish_delivery(self,claim,Result('transport_uncertain'))
        self.age_event(6)
        self.query("UPDATE native_push_deliveries SET created_at=clock_timestamp()-interval '10 days',updated_at=clock_timestamp()-interval '6 days'")
        cleanup(self)
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(1,)])

    def test_cleanup_keeps_live_lease(self):
        worker.claim_delivery(self,fixture.CONFIG.project)
        self.age_event(8)
        cleanup(self)
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('leased',)])

    def test_replay_and_revoked_tombstones_survive(self):
        request=uuid4()
        installation,result=self.begin(request=request)
        self.query("UPDATE native_push_registration_challenges SET created_at=clock_timestamp()-interval '9 days',"
                   "expires_at=clock_timestamp()-interval '8 days',next_attempt_at=clock_timestamp()-interval '9 days' WHERE challenge_ref=%s", (result['challenge_ref'],))
        cleanup(self)
        self.assertEqual(self.begin(installation=installation,request=request)[1]['code'],'CHALLENGE_EXISTS')
        with self.connection() as conn:
            fixture.registration.revoke(conn,self.users[2],fixture.CONFIG,self.installation,2)
        cleanup(self)
        self.assertEqual(self.query('SELECT status,generation FROM native_push_installations WHERE installation_ref=%s',(self.installation,)),[('revoked',3)])

    def test_cleanup_batch_and_concurrency(self):
        from concurrent.futures import ThreadPoolExecutor
        self.produce(); self.produce()
        self.age_event(8)
        with patch.dict(os.environ,{'NATIVE_PUSH_CLEANUP_BATCH':'1'}):
            cleanup(self)
            self.assertEqual(self.query("SELECT count(*) FROM native_push_deliveries WHERE status='expired'"),[(1,)])
            with ThreadPoolExecutor(2) as executor:
                list(executor.map(lambda _:cleanup(self),range(2)))
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(3,)])

    def test_uncertain_challenge_lease_is_not_replayed(self):
        self.begin()
        self.query("UPDATE native_push_registration_challenges SET created_at=clock_timestamp()-interval '1 minute',"
                   "lease_token=%s,lease_until=clock_timestamp()-interval '1 second' WHERE status='pending'", (uuid4(),))
        provider=fixture.Mock()
        worker.challenge_pass(self,fixture.CONFIG,provider)
        provider.send.assert_not_called()
