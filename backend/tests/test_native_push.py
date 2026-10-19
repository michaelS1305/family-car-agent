"""Offline Native Push security/provider tests and isolated PostgreSQL tests.

Only explicitly supplied loopback test_gemini databases are permitted. Schema
fixtures use the exact P2 table DDL, not execution of the manual migration.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
import requests

from identity import CurrentUser
from native_push_security import Config, ConfigurationError, nonce_context, token_context
from native_push_fcm import Fcm, Result
import native_push_outbox as outbox
import native_push_registration as registration
import native_push_worker as worker


CONFIG = Config('test-fca-project','/test-only/unused.json','test',b'e'*32,b'f'*32)


class SecurityTests(unittest.TestCase):
    def test_config_fails_closed(self):
        with patch.dict(os.environ,{},clear=True), self.assertRaises(ConfigurationError):
            Config.load()

    def test_cipher_context_and_key_isolation(self):
        value = CONFIG.seal('secret-token','owner-one')
        self.assertNotIn(b'secret-token',value)
        self.assertEqual(CONFIG.open(value,'test','owner-one'),'secret-token')
        for context,key in [('owner-two','test'),('owner-one','wrong')]:
            with self.assertRaises(ConfigurationError):
                CONFIG.open(value,key,context)
        with self.assertRaises(ConfigurationError):
            CONFIG.open(value[:-1]+bytes([value[-1]^1]),'test','owner-one')

    def test_separate_keys_and_repr(self):
        self.assertNotIn('eeee',repr(CONFIG))
        self.assertNotIn('ffff',repr(CONFIG))
        self.assertEqual(len(CONFIG.fingerprint('token')),32)
        self.assertNotEqual(CONFIG.fingerprint('token'),CONFIG.fingerprint('token2'))

    def test_fcm_remaining_ttl_and_no_retry(self):
        transport = Mock()
        transport.post.return_value.status_code=200
        provider = Fcm(CONFIG,transport=transport,clock=lambda:1000)
        provider._token,provider._until='mock-access',2000
        deadline=datetime.fromtimestamp(1032,timezone.utc)
        self.assertEqual(provider.send('mock-token',{'kind':'vehicle_taken'},expires_at=deadline,platform='android').code,'accepted')
        call=transport.post.call_args
        self.assertEqual(call.kwargs['json']['message']['android']['ttl'],'32s')
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertEqual(call.kwargs['timeout'],(3,5))
        transport.post.side_effect=requests.Timeout('private-value')
        self.assertEqual(provider.send('mock-token',{},expires_at=deadline,platform='android').code,'transport_uncertain')
        self.assertEqual(transport.post.call_count,2)

    def test_fcm_expired_never_sends(self):
        transport=Mock()
        provider=Fcm(CONFIG,transport=transport,clock=lambda:1000)
        provider._token,provider._until='mock-access',2000
        self.assertEqual(provider.send('x',{},expires_at=datetime.fromtimestamp(999,timezone.utc),platform='ios').code,'expired')
        transport.post.assert_not_called()

    def test_wrong_project_never_sends(self):
        transport=Mock()
        provider=Fcm(CONFIG,transport=transport,loader=lambda p:{'project_id':'wrong'})
        self.assertEqual(provider.send('x',{},expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),platform='ios').code,'configuration')
        transport.post.assert_not_called()

    def test_provider_classification(self):
        for status,code in [(429,'rate_limited'),(503,'provider_unavailable'),(401,'configuration'),(400,'invalid_payload')]:
            with self.subTest(status=status):
                transport=Mock()
                transport.post.return_value.status_code=status
                transport.post.return_value.json.return_value={}
                provider=Fcm(CONFIG,transport=transport)
                provider._token,provider._until='mock-access',float('inf')
                self.assertEqual(provider.send('x',{},expires_at=datetime.now(timezone.utc)+timedelta(minutes=1),platform='android').code,code)

    def test_outer_commit_error_never_wakes(self):
        outbox.wakeup.clear()
        with self.assertRaises(RuntimeError),outbox.commit_boundary():
            outbox._committed_work.get().append(True)
            raise RuntimeError('outer commit failure')
        self.assertFalse(outbox.wakeup.is_set())

    def test_oauth_scoped_signed_assertion_and_cache(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        transport=Mock()
        transport.post.return_value.status_code=200
        transport.post.return_value.json.return_value={'access_token':'mock-access','expires_in':3600}
        loader=Mock(return_value={'type':'service_account','project_id':CONFIG.project,
            'token_uri':'https://oauth2.googleapis.com/token','client_email':'test@test.iam.gserviceaccount.com','private_key':pem})
        provider=Fcm(CONFIG,transport=transport,loader=loader)
        self.assertEqual(provider._access_token(),'mock-access')
        assertion=transport.post.call_args.kwargs['data']['assertion']
        claims=jwt.decode(assertion,key.public_key(),algorithms=['RS256'],audience='https://oauth2.googleapis.com/token')
        self.assertEqual(claims['scope'],'https://www.googleapis.com/auth/firebase.messaging')
        self.assertEqual(claims['exp']-claims['iat'],3600)
        self.assertEqual(provider._access_token(),'mock-access')
        self.assertEqual(transport.post.call_count,1)

    def test_disabled_producer_never_touches_db(self):
        with patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'false'}):
            self.assertFalse(outbox.produce(None,uuid4(),fast=True,transition='opened'))

    def test_disabled_lifespan_never_loads_credentials_or_pool(self):
        import asyncio
        async def check():
            async with worker.native_lifespan(None):
                pass
        with patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'false'}),patch.object(worker.Config,'load') as load:
            asyncio.run(check())
        load.assert_not_called()


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'),'Requires disposable local PostgreSQL')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['GEMINI_TEST_DATABASE_URL']
        url=urlsplit(self.dsn)
        if url.hostname not in ('127.0.0.1','localhost','::1') or url.path!='/test_gemini':
            raise RuntimeError('Only disposable local test_gemini allowed')
        self.schema='native_push_test_'+uuid4().hex
        with psycopg.connect(self.dsn) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup)
        with self.connection() as conn:
            conn.execute('CREATE TABLE auth_users(id uuid PRIMARY KEY)')
            conn.execute('CREATE TABLE account_deletion_jobs(auth_user_id uuid PRIMARY KEY)')
            conn.execute('CREATE TABLE users(id integer PRIMARY KEY,family_id integer,auth_user_id uuid UNIQUE REFERENCES auth_users)')
            conn.execute('CREATE TABLE vehicles(id integer PRIMARY KEY,family_id integer,vehicle_ref uuid NOT NULL UNIQUE)')
            conn.execute('CREATE TABLE vehicle_events(event_id uuid PRIMARY KEY,user_id integer NOT NULL,vehicle_id integer NOT NULL,'
                'family_id integer NOT NULL,occurred_at timestamptz NOT NULL,event_type text,admission_outcome text,'
                'UNIQUE(event_id,user_id,vehicle_id,family_id))')
            source=(Path(__file__).resolve().parents[2]/'supabase/manual_migrations/2026101801_native_push_foundation.sql').read_text()
            ddl='CREATE TABLE public.native_push_installations ('+source.split('CREATE TABLE public.native_push_installations (',1)[1].split('-- Remove inherited default grants',1)[0]
            conn.execute(ddl.replace('public.',self.schema+'.'))
        self.users={}
        for ident,family in [(1,10),(2,10),(3,20)]:
            auth=uuid4()
            self.query('INSERT INTO auth_users VALUES(%s)',(auth,))
            self.query('INSERT INTO users VALUES(%s,%s,%s)',(ident,family,auth))
            self.users[ident]=CurrentUser(ident,'Test',family,auth_user_id=str(auth))
        self.query('INSERT INTO vehicles VALUES(1,10,%s)',(uuid4(),))
        self.patch=patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'true'})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        outbox.wakeup.clear()

    def cleanup(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn,connect_timeout=3) as raw:
            raw.execute(sql.SQL('SET search_path TO {},pg_catalog').format(sql.Identifier(self.schema)))
            raw.execute("SET statement_timeout='5s'")
            raw.commit()
            class Connection:
                conn=raw
                def execute(self,query,params=None):
                    return raw.execute(query.replace('auth.users','auth_users'),params)
                def transaction(self):
                    return raw.transaction()
            yield Connection()

    def query(self,query,params=None):
        with self.connection() as conn:
            cursor=conn.execute(query,params)
            return cursor.fetchall() if cursor.description else []

    def begin(self,user=2,installation=None,token='test-token-abcdefghijklmnopqrstuvwxyz',request=None):
        installation=installation or uuid4()
        with self.connection() as conn:
            result=registration.begin(conn,self.users[user],CONFIG,installation_ref=installation,
                request_id=request or uuid4(),platform='android',token=token)
        return installation,result

    def nonce(self,ref,user=2):
        cipher=self.query('SELECT nonce_ciphertext FROM native_push_registration_challenges WHERE challenge_ref=%s',(ref,))[0][0]
        return CONFIG.open(cipher,CONFIG.key_id,nonce_context(user,ref))

    def confirm(self,installation,ref,nonce,user=2):
        with self.connection() as conn:
            return registration.confirm(conn,self.users[user],CONFIG,installation_ref=installation,challenge_ref=ref,nonce=nonce)

    def activate(self,user=2,token=None):
        installation,result=self.begin(user,token=token or 'test-token-'+uuid4().hex)
        self.assertEqual(result['code'],'CHALLENGE_PENDING')
        ref=result['challenge_ref']
        self.assertEqual(self.confirm(installation,ref,self.nonce(ref,user),user)['code'],'ACTIVE')
        return installation

    def event(self,conn,age=0,kind='take'):
        ref=uuid4()
        conn.execute("INSERT INTO vehicle_events VALUES(%s,1,1,10,clock_timestamp()-(%s * interval '1 second'),%s,'accepted')",(ref,age,kind))
        return ref

    def produce(self,age=0,kind='take'):
        with outbox.commit_boundary(),self.connection() as conn:
            ref=self.event(conn,age,kind)
            result=outbox.produce(conn,ref,fast=True,transition='opened' if kind=='take' else 'returned')
        return ref,result

    def test_atomic_commit_and_family_actor_exclusion(self):
        for user in (1,2,3): self.activate(user)
        ref,produced=self.produce()
        self.assertTrue(produced)
        self.assertTrue(outbox.wakeup.is_set())
        self.assertEqual(self.query('SELECT recipient_user_id FROM native_push_deliveries'),[(2,)])
        self.assertEqual(self.query('SELECT source_event_id,expires_at-occurred_at FROM native_push_events'),[(ref,timedelta(minutes=5))])

    def test_outbox_partial_failure_savepoint_business_commits(self):
        self.activate()
        # Force failure after event insertion, at delivery insertion.
        self.query('ALTER TABLE native_push_deliveries ADD CONSTRAINT test_failure CHECK(false) NOT VALID')
        with self.assertLogs('native_push_outbox',level='ERROR') as captured:
            ref,produced=self.produce()
        self.assertEqual(captured.records[0].sqlstate,'23514')
        self.assertEqual(captured.records[0].getMessage(),'native_push_outbox_write_failed')
        self.assertTrue(captured.records[0].notification_may_be_lost)
        self.assertFalse(produced)
        self.assertEqual(self.query('SELECT event_id FROM vehicle_events'),[(ref,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_deliveries'),[(0,)])
        self.assertFalse(outbox.wakeup.is_set())

    def test_outer_rollback_no_event_outbox_or_signal(self):
        self.activate()
        with self.assertRaises(ValueError),outbox.commit_boundary(),self.connection() as conn:
            ref=self.event(conn)
            self.assertTrue(outbox.produce(conn,ref,fast=True,transition='opened'))
            raise ValueError('business failure')
        for table in ('vehicle_events','native_push_events','native_push_deliveries'):
            self.assertEqual(self.query(f'SELECT count(*) FROM {table}'),[(0,)])
        self.assertFalse(outbox.wakeup.is_set())

    def test_unrecoverable_error_propagates(self):
        with self.assertRaises(psycopg.errors.SerializationFailure),outbox.commit_boundary(),self.connection() as conn:
            ref=self.event(conn)
            execute=conn.execute
            def fail(query,params=None):
                if query.startswith('INSERT INTO native_push_events'):
                    raise psycopg.errors.SerializationFailure('mock private text')
                return execute(query,params)
            conn.execute=fail
            outbox.produce(conn,ref,fast=True,transition='opened')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'),[(0,)])
        self.assertFalse(outbox.wakeup.is_set())

    def test_connection_loss_propagates(self):
        with self.assertRaises(psycopg.OperationalError),outbox.commit_boundary(),self.connection() as conn:
            ref=self.event(conn)
            conn.conn.close()
            outbox.produce(conn,ref,fast=True,transition='opened')
        self.assertFalse(outbox.wakeup.is_set())

    def test_actual_outer_commit_failure_propagates(self):
        self.query('CREATE TABLE commit_failure(value integer UNIQUE DEFERRABLE INITIALLY DEFERRED)')
        with self.assertRaises(psycopg.errors.UniqueViolation),outbox.commit_boundary(),self.connection() as conn:
            ref=self.event(conn)
            self.assertTrue(outbox.produce(conn,ref,fast=True,transition='opened'))
            conn.execute('INSERT INTO commit_failure VALUES(1),(1)')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'),[(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(0,)])
        self.assertFalse(outbox.wakeup.is_set())

    def test_failed_savepoint_recovery_is_not_swallowed(self):
        with self.connection() as conn:
            ref=self.event(conn)
            @contextmanager
            def unrecoverable():
                try:
                    yield
                finally:
                    raise psycopg.errors.ConnectionFailure('rollback failed')
            conn.transaction=unrecoverable
            with self.assertRaises(psycopg.errors.ConnectionFailure):
                outbox.produce(conn,ref,fast=True,transition='opened')

    def test_ineligible_future_expired_replay_redundant(self):
        for age in (-60,301):
            self.assertFalse(self.produce(age)[1])
        with self.connection() as conn:
            ref=self.event(conn)
            self.assertFalse(outbox.produce(conn,ref,fast=False,transition='opened'))
            self.assertFalse(outbox.produce(conn,ref,fast=True,transition='redundant'))
            self.assertTrue(outbox.produce(conn,ref,fast=True,transition='opened'))
            self.assertFalse(outbox.produce(conn,ref,fast=True,transition='opened'))

    def test_returned_event(self):
        self.assertTrue(self.produce(kind='return')[1])
        self.assertEqual(self.query('SELECT event_type FROM native_push_events'),[('vehicle_returned',)])

    def test_rotation_replay_and_material_erasure(self):
        installation,result=self.begin()
        ref=result['challenge_ref']; nonce=self.nonce(ref)
        self.assertEqual(self.confirm(installation,ref,nonce)['generation'],2)
        self.assertEqual(self.confirm(installation,ref,nonce)['generation'],2)
        self.assertEqual(self.query('SELECT nonce_hash,nonce_ciphertext,candidate_token_ciphertext FROM native_push_registration_challenges'),[(None,None,None)])
        _,next_result=self.begin(installation=installation,token='rotated-'+uuid4().hex)
        next_ref=next_result['challenge_ref']
        self.assertEqual(self.confirm(installation,next_ref,self.nonce(next_ref))['generation'],3)
        self.assertEqual(self.confirm(installation,ref,nonce)['code'],'REGISTRATION_UNAVAILABLE')

    def test_cross_owner_and_token_takeover_denied(self):
        token='shared-token-'+uuid4().hex
        installation=self.activate(2,token)
        self.assertEqual(self.begin(3,installation=installation)[1]['code'],'REGISTRATION_UNAVAILABLE')
        other,result=self.begin(3,token=token)
        ref=result['challenge_ref']
        self.assertEqual(self.confirm(other,ref,self.nonce(ref,3),3)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.query("SELECT user_id FROM native_push_installations WHERE status='active'"),[(2,)])

    def test_guesses_are_committed_and_bounded(self):
        installation,result=self.begin(); ref=result['challenge_ref']; nonce=self.nonce(ref)
        for _ in range(5):
            self.assertEqual(self.confirm(installation,ref,'wrong')['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.confirm(installation,ref,nonce)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.query('SELECT verify_attempts,status,nonce_hash FROM native_push_registration_challenges'),[(5,'cancelled',None)])

    def test_expired_challenge(self):
        installation,result=self.begin(); ref=result['challenge_ref']; nonce=self.nonce(ref)
        self.query("UPDATE native_push_registration_challenges SET created_at=clock_timestamp()-interval '3 minutes',"
            "next_attempt_at=clock_timestamp()-interval '2 minutes',expires_at=clock_timestamp()-interval '1 minute'")
        self.assertEqual(self.confirm(installation,ref,nonce)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.query('SELECT status,nonce_hash FROM native_push_registration_challenges'),[('expired',None)])

    def test_rate_limit_and_idempotent_begin(self):
        request=uuid4(); installation,result=self.begin(request=request)
        self.assertEqual(self.begin(installation=installation,request=request)[1]['challenge_ref'],result['challenge_ref'])
        for _ in range(9): self.begin(installation=installation)
        self.assertEqual(self.begin(installation=installation)[1]['code'],'RATE_LIMITED')
        self.assertEqual(self.query('SELECT count(*) FROM native_push_registration_challenges'),[(10,)])

    def test_revoke_is_owner_scoped_and_fences_generation(self):
        installation=self.activate()
        with self.connection() as conn: registration.revoke(conn,self.users[3],CONFIG,installation,2)
        self.assertEqual(self.query('SELECT status FROM native_push_installations'),[('active',)])
        with self.connection() as conn: registration.revoke(conn,self.users[2],CONFIG,installation,2)
        self.assertEqual(self.query('SELECT status,generation,token_ciphertext FROM native_push_installations'),[('revoked',3,None)])

    def test_stale_logout_cannot_revoke_new_generation(self):
        installation=self.activate()
        _,result=self.begin(installation=installation,token='rotated-'+uuid4().hex)
        self.confirm(installation,result['challenge_ref'],self.nonce(result['challenge_ref']))
        with self.connection() as conn:
            self.assertEqual(registration.revoke(conn,self.users[2],CONFIG,installation,2)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(self.query('SELECT status,generation FROM native_push_installations'),[('active',3)])

    def test_account_switch_requires_old_owner_revoke(self):
        token='switch-token-'+uuid4().hex
        installation=self.activate(2,token)
        with self.connection() as conn: registration.revoke(conn,self.users[2],CONFIG,installation,2)
        self.activate(3,token)
        self.assertEqual(self.query("SELECT user_id FROM native_push_installations WHERE status='active'"),[(3,)])

    def test_key_drift_cannot_bypass_token_uniqueness(self):
        from dataclasses import replace
        self.activate()
        for changed in (replace(CONFIG,fingerprint_key=b'x'*32),replace(CONFIG,encryption_key=b'x'*32),replace(CONFIG,key_id='other')):
            with self.assertRaises(ConfigurationError),self.connection() as conn:
                registration.begin(conn,self.users[3],changed,installation_ref=uuid4(),request_id=uuid4(),platform='android',token='mock-token-'+uuid4().hex)

    def test_changed_identity_fails_closed(self):
        from deletion_gate import IdentityUnavailable
        self.query('UPDATE users SET family_id=20 WHERE id=2')
        with self.assertRaises(IdentityUnavailable): self.begin()

    def test_deleting_identity_cannot_register(self):
        from deletion_gate import IdentityUnavailable
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(self.users[2].auth_user_id,))
        with self.assertRaises(IdentityUnavailable): self.begin()

    def test_pending_count_bounded(self):
        for _ in range(5): self.assertEqual(self.begin()[1]['code'],'CHALLENGE_PENDING')
        self.assertEqual(self.begin()[1]['code'],'RATE_LIMITED')

    def test_concurrent_token_activation_has_only_one_owner(self):
        token='concurrent-token-'+uuid4().hex
        one,a=self.begin(2,token=token); two,b=self.begin(3,token=token)
        calls=[(one,a['challenge_ref'],self.nonce(a['challenge_ref'],2),2),
               (two,b['challenge_ref'],self.nonce(b['challenge_ref'],3),3)]
        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(lambda args:self.confirm(*args),calls))
        self.assertEqual(sorted(r['code'] for r in results),['ACTIVE','REGISTRATION_UNAVAILABLE'])

    def test_concurrent_challenge_confirm(self):
        installation,result=self.begin(); ref=result['challenge_ref']; nonce=self.nonce(ref)
        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(lambda _:self.confirm(installation,ref,nonce),range(2)))
        self.assertEqual([r['generation'] for r in results],[2,2])

    def test_claims_are_exclusive_and_payload_scoped(self):
        self.activate(); self.produce()
        with ThreadPoolExecutor(2) as executor:
            claims=list(executor.map(lambda _:worker.claim_delivery(self,CONFIG.project),range(2)))
        self.assertEqual(sum(c is not None for c in claims),1)
        claim=next(c for c in claims if c)
        payload=worker.delivery_payload(self,CONFIG,claim)
        self.assertEqual(payload[1],{'kind':'refresh','version':'1'})
        self.query('UPDATE users SET family_id=20 WHERE id=2')
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))

    def test_revocation_before_send(self):
        installation=self.activate(); self.produce()
        claim=worker.claim_delivery(self,CONFIG.project)
        with self.connection() as conn: registration.revoke(conn,self.users[2],CONFIG,installation,2)
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        worker.finish_delivery(self,claim,Result('accepted'))
        self.assertEqual(self.query('SELECT status,last_error_code FROM native_push_deliveries'),[('cancelled','generation_changed')])

    def test_revocation_after_payload_read_sends_only_opaque_hint(self):
        installation=self.activate(); self.produce()
        original=worker.delivery_payload
        def read_then_revoke(*args):
            payload=original(*args)
            with self.connection() as conn:
                registration.revoke(conn,self.users[2],CONFIG,installation,2)
            return payload
        provider=Mock(); provider.send.return_value=Result('accepted')
        with patch.object(worker,'delivery_payload',side_effect=read_then_revoke):
            worker.run_once(self,CONFIG,provider)
        provider.send.assert_called_once()
        self.assertEqual(provider.send.call_args.args[1],{'kind':'refresh','version':'1'})
        self.assertEqual(self.query('SELECT status,last_error_code FROM native_push_deliveries'),
                         [('cancelled','generation_changed')])

    def test_deletion_between_send_and_completion_cancels(self):
        self.activate(); self.produce(); claim=worker.claim_delivery(self,CONFIG.project)
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)',(self.users[2].auth_user_id,))
        self.assertIsNone(worker.delivery_payload(self,CONFIG,claim))
        worker.finish_delivery(self,claim,Result('accepted'))
        self.assertEqual(self.query('SELECT status,last_error_code FROM native_push_deliveries'),[('cancelled','identity_unavailable')])

    def test_expiry_prevents_send(self):
        self.activate(); self.produce()
        self.query("UPDATE native_push_events SET occurred_at=now()-interval '6 minutes',"
                   "expires_at=now()-interval '1 minute'")
        provider=Mock()
        worker.run_once(self,CONFIG,provider)
        provider.send.assert_not_called()
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('expired',)])

    def test_stale_lease_completion_ignored(self):
        self.activate(); self.produce(); claim=worker.claim_delivery(self,CONFIG.project)
        worker.finish_delivery(self,(claim[0],uuid4()),Result('accepted'))
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('leased',)])

    def test_provider_acceptance_and_invalid_token(self):
        installation=self.activate(); self.produce()
        claim=worker.claim_delivery(self,CONFIG.project)
        worker.finish_delivery(self,claim,Result('accepted'))
        self.assertEqual(self.query('SELECT status,accepted_at IS NOT NULL FROM native_push_deliveries'),[('accepted',True)])
        self.produce(); claim=worker.claim_delivery(self,CONFIG.project)
        worker.finish_delivery(self,claim,Result('unregistered'))
        self.assertEqual(self.query('SELECT status,token_ciphertext FROM native_push_installations WHERE installation_ref=%s',(installation,)),[('invalid',None)])

    def test_retry_and_ambiguous_send_no_retry(self):
        self.activate(); self.produce()
        claim=worker.claim_delivery(self,CONFIG.project)
        worker.finish_delivery(self,claim,Result('provider_unavailable'))
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('retry_wait',)])
        self.assertIsNone(worker.claim_delivery(self,CONFIG.project))
        self.query('UPDATE native_push_deliveries SET next_attempt_at=created_at')
        claim=worker.claim_delivery(self,CONFIG.project)
        worker.finish_delivery(self,claim,Result('transport_uncertain'))
        self.assertEqual(self.query('SELECT status FROM native_push_deliveries'),[('failed',)])
        self.assertIsNone(worker.claim_delivery(self,CONFIG.project))

    def test_crash_recovery_does_not_replay_uncertain_send(self):
        self.activate(); self.produce(); worker.claim_delivery(self,CONFIG.project)
        self.query("UPDATE native_push_deliveries SET created_at=clock_timestamp()-interval '1 minute',"
                   "lease_until=clock_timestamp()-interval '1 second'")
        self.assertIsNone(worker.claim_delivery(self,CONFIG.project))
        self.assertEqual(self.query('SELECT status,last_error_code FROM native_push_deliveries'),[('failed','transport_uncertain')])

    def test_worker_never_calls_provider_inside_transaction(self):
        self.activate(); self.produce()
        provider=Mock()
        provider.send.return_value=Result('accepted')
        def send(*args,**kwargs):
            # Separate connection can observe the committed lease.
            self.assertEqual(self.query("SELECT count(*) FROM native_push_deliveries WHERE status='leased'"),[(1,)])
            return Result('accepted')
        provider.send.side_effect=send
        worker.run_once(self,CONFIG,provider)
        provider.send.assert_called_once()

    def test_challenge_dispatch_failure_erases_material(self):
        self.begin()
        provider=Mock(); provider.send.return_value=Result('unregistered')
        self.assertTrue(worker.challenge_pass(self,CONFIG,provider))
        self.assertEqual(self.query('SELECT status,nonce_ciphertext FROM native_push_registration_challenges'),[('cancelled',None)])

    def test_challenge_accepted_keeps_confirmable_no_resend(self):
        installation,result=self.begin(); ref=result['challenge_ref']; nonce=self.nonce(ref)
        provider=Mock(); provider.send.return_value=Result('accepted')
        self.assertTrue(worker.challenge_pass(self,CONFIG,provider))
        self.assertFalse(worker.challenge_pass(self,CONFIG,provider))
        self.assertEqual(self.confirm(installation,ref,nonce)['code'],'ACTIVE')

    def test_challenge_rechecks_revocation_after_oauth(self):
        installation,_=self.begin()
        provider=Mock()
        def prepare():
            with self.connection() as conn:
                registration.revoke(conn,self.users[2],CONFIG,installation,1)
        provider.prepare.side_effect=prepare
        worker.challenge_pass(self,CONFIG,provider)
        provider.send.assert_not_called()

    def test_delivery_rechecks_membership_after_oauth(self):
        self.activate(); self.produce()
        provider=Mock()
        provider.prepare.side_effect=lambda:self.query('UPDATE users SET family_id=20 WHERE id=2')
        worker.run_once(self,CONFIG,provider)
        provider.send.assert_not_called()

    def test_concurrent_challenge_claim(self):
        self.begin()
        provider=Mock(); provider.send.return_value=Result('accepted')
        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(lambda _:worker.challenge_pass(self,CONFIG,provider),range(2)))
        self.assertEqual(sorted(results),[False,True])
        provider.send.assert_called_once()


if __name__=='__main__':
    unittest.main()
