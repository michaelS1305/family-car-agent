import base64
import concurrent.futures
import hashlib
import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from apple_credentials import Store, capture, exchange, linked_subject, _log_failure
from apple_credentials_security import Config, CaptureUnavailable


def configuration():
    return Config('ABCDEFGHIJ', 'KLMNOPQRST', 'com.familycaragent.app.dev', 'dev',
                  ec.generate_private_key(ec.SECP256R1()), 'v1', {'v1': os.urandom(32)})


class MemoryStore:
    """Deterministic persistence boundary double; SQL boundaries tested separately."""
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = {}
        self.subject = 'synthetic-apple-sub'
        self.value = b'previous-encrypted-value'
        self.fail = False
        self.live = True

    def begin(self, owner, digest):
        with self.lock:
            if not self.live or not self.subject:
                raise CaptureUnavailable()
            key = owner, digest
            if key in self.attempts:
                return None, self.subject, self.attempts[key][1]
            generation = len(self.attempts) + 1
            self.attempts[key] = generation, 'pending'
            return generation, self.subject, 'pending'

    def finish(self, owner, generation, subject, config, ciphertext):
        with self.lock:
            if self.fail or not self.live or self.subject != subject or generation != len(self.attempts):
                raise CaptureUnavailable()
            self.value = ciphertext
            for key, value in self.attempts.items():
                if value[0] == generation:
                    self.attempts[key] = generation, 'stored'


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.store = MemoryStore()
        self.nonce = 'synthetic-nonce-only'
        self.owner = '00000000-0000-0000-0000-000000000001'

    def capture(self, code='synthetic-code', exchanger=None):
        return capture(self.store, self.owner, code, self.nonce, config=self.config,
                       exchanger=exchanger or (lambda *args: 'synthetic-refresh'))

    def test_encrypted_persistence_and_duplicate(self):
        self.assertEqual(self.capture(), {'status': 'stored'})
        self.assertNotIn(b'synthetic-refresh', self.store.value)
        self.assertEqual(self.config.open(self.store.value, 'v1', self.owner, self.store.subject, 1), 'synthetic-refresh')
        self.assertEqual(self.capture(exchanger=lambda *args: self.fail('duplicate exchange')), {'status': 'stored'})

    def test_exchange_failure_is_not_retried_and_preserves_old_token(self):
        before = self.store.value
        def fail(*args):
            raise requests.Timeout('sensitive-provider-error')
        self.assertEqual(self.capture(exchanger=fail), {'status': 'unavailable'})
        self.assertEqual(self.capture(exchanger=lambda *args: self.fail('replay')), {'status': 'unavailable'})
        self.assertEqual(before, self.store.value)

    def test_write_failure_after_exchange_preserves_old_token_and_attempt(self):
        before = self.store.value
        self.store.fail = True
        self.assertEqual(self.capture(), {'status': 'unavailable'})
        self.assertEqual(before, self.store.value)
        self.store.fail = False
        self.assertEqual(self.capture(exchanger=lambda *args: self.fail('consumed code')), {'status': 'unavailable'})

    def test_missing_identity_never_exchanges(self):
        self.store.subject = None
        self.assertEqual(self.capture(exchanger=lambda *args: self.fail('exchange')), {'status': 'unavailable'})

    def test_failed_attempt_commit_never_contacts_apple(self):
        self.store.begin = MagicMock(side_effect=RuntimeError('PRIVATE_DB_SENTINEL'))
        self.assertEqual(self.capture(exchanger=lambda *args: self.fail('exchange before commit')), {'status': 'unavailable'})

    def test_provider_exception_never_reaches_logs_or_response(self):
        import logging
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logging.getLogger().addHandler(handler)
        try:
            def fail(*args):
                raise RuntimeError('PRIVATE_PROVIDER_SENTINEL')
            self.assertEqual(self.capture(exchanger=fail), {'status': 'unavailable'})
            self.assertNotIn('PRIVATE_PROVIDER_SENTINEL', '\n'.join(records))
        finally:
            logging.getLogger().removeHandler(handler)

    def test_concurrent_duplicate_exchanges_once(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return 'synthetic-refresh'
        with concurrent.futures.ThreadPoolExecutor() as executor:
            first = executor.submit(self.capture, exchanger=slow)
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.capture(exchanger=lambda *args: self.fail('duplicate')), {'status': 'unavailable'})
            release.set()
            self.assertEqual(first.result(), {'status': 'stored'})

    def test_late_exchange_cannot_overwrite_new_generation(self):
        def older(*args):
            self.assertEqual(self.capture('new-code'), {'status': 'stored'})
            return 'older-refresh'
        self.assertEqual(self.capture(exchanger=older), {'status': 'unavailable'})
        self.assertEqual(self.config.open(self.store.value, 'v1', self.owner, self.store.subject, 2), 'synthetic-refresh')

    def test_deletion_or_identity_change_during_exchange(self):
        for action in (lambda: setattr(self.store, 'live', False), lambda: setattr(self.store, 'subject', 'other')):
            self.store = MemoryStore()
            before = self.store.value
            def changing(*args):
                action()
                return 'synthetic-refresh'
            self.assertEqual(self.capture(exchanger=changing), {'status': 'unavailable'})
            self.assertEqual(self.store.value, before)

    def test_tamper_aad_and_rotation(self):
        self.capture()
        for data, owner, sub, version in ((self.store.value[:-1]+bytes([self.store.value[-1]^1]), self.owner,self.store.subject,1),
                                        (self.store.value,'other',self.store.subject,1),
                                        (self.store.value,self.owner,'other',1),
                                        (self.store.value,self.owner,self.store.subject,2)):
            with self.assertRaises(CaptureUnavailable):
                self.config.open(data,'v1',owner,sub,version)
        rotated = Config(self.config.team,self.config.kid,self.config.client,'dev',self.config.private_key,
                         'v2',dict(self.config.keys,v2=os.urandom(32)))
        self.assertEqual(rotated.open(self.store.value,'v1',self.owner,self.store.subject,1),'synthetic-refresh')


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.config = configuration()
        self.nonce = 'synthetic-nonce'
        self.claims = dict(iss='https://appleid.apple.com',aud=self.config.client,sub='apple-sub',
                          exp=int(time.time())+300,iat=int(time.time()),nonce=hashlib.sha256(self.nonce.encode()).hexdigest())
        self.http = MagicMock()
        self.http.__enter__.return_value = self.http
        self.response = self.http.post.return_value.__enter__.return_value
        self.response.status_code = 200

    def run_exchange(self, claims=None, key=None):
        token = jwt.encode(claims or self.claims,key or self.key,algorithm='RS256',headers={'kid':'test'})
        self.response.iter_content.return_value = [json.dumps(dict(id_token=token,refresh_token='synthetic-refresh')).encode()]
        return exchange(self.config,'synthetic-code',self.nonce,'apple-sub',resolver=lambda _: self.key.public_key(),http=self.http)

    def test_success_and_exact_request(self):
        self.assertEqual(self.run_exchange(),'synthetic-refresh')
        args, kwargs = self.http.post.call_args
        self.assertEqual(args,('https://appleid.apple.com/auth/token',))
        self.assertFalse(kwargs['allow_redirects'])
        self.assertFalse(self.http.trust_env)
        self.assertEqual(kwargs['data']['grant_type'],'authorization_code')
        secret = jwt.decode(kwargs['data']['client_secret'],self.config.private_key.public_key(),
                            algorithms=['ES256'],audience='https://appleid.apple.com')
        self.assertEqual(secret['sub'],self.config.client)
        self.assertEqual(secret['iss'],self.config.team)

    def test_invalid_claims_and_missing_nonce(self):
        for key, value in [('iss','other'),('aud','other'),('sub','other'),('exp',1),('nonce','wrong')]:
            with self.subTest(key=key), self.assertRaises(CaptureUnavailable) as error:
                self.run_exchange(dict(self.claims,**{key:value}))
            self.assertEqual(error.exception.category,
                             'identity_mismatch' if key == 'sub' else 'token_validation_failed')
        claims = dict(self.claims); del claims['nonce']
        with self.assertRaises(CaptureUnavailable) as error:
            self.run_exchange(claims)
        self.assertEqual(error.exception.category, 'token_validation_failed')

    def test_invalid_signature(self):
        with self.assertRaises(CaptureUnavailable) as error:
            self.run_exchange(key=rsa.generate_private_key(public_exponent=65537,key_size=2048))
        self.assertEqual(error.exception.category, 'token_validation_failed')

    def test_used_code_and_provider_errors(self):
        for status in (400,401,429,500,302):
            self.response.status_code = status
            with self.subTest(status=status), self.assertRaises(CaptureUnavailable):
                self.run_exchange()

    def test_timeout(self):
        self.http.post.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            self.run_exchange()


class DiagnosticTests(unittest.TestCase):
    def test_failure_categories_and_no_sensitive_logging(self):
        from deletion_gate import IdentityUnavailable
        config = configuration()
        cases = [
            ('config', RuntimeError('PRIVATE_CONFIG'), 'configuration_invalid'),
            ('begin', RuntimeError('PRIVATE_DATABASE'), 'persistence_failed'),
            ('begin', CaptureUnavailable('identity_mismatch'), 'identity_mismatch'),
            ('begin', IdentityUnavailable(), 'identity_unavailable'),
            ('begin', CaptureUnavailable('attempt_limited'), 'attempt_limited'),
            ('exchange', requests.Timeout('PRIVATE_PROVIDER'), 'apple_exchange_failed'),
            ('exchange', CaptureUnavailable('token_validation_failed'), 'token_validation_failed'),
            ('exchange', CaptureUnavailable('identity_mismatch'), 'identity_mismatch'),
            ('seal', RuntimeError('PRIVATE_KEY'), 'encryption_failed'),
            ('finish', RuntimeError('PRIVATE_DATABASE'), 'persistence_failed'),
            ('finish', CaptureUnavailable('attempt_superseded'), 'attempt_superseded'),
        ]
        for stage, failure, expected in cases:
            with self.subTest(stage=stage, category=expected):
                store = MagicMock()
                store.begin.return_value = (1, 'PRIVATE_SUBJECT', 'pending')
                exchanger = MagicMock(return_value='PRIVATE_REFRESH')
                with patch('apple_credentials.Config.load', return_value=config) as load, \
                     patch.object(Config, 'seal', return_value=b'PRIVATE_CIPHERTEXT') as seal:
                    target = {'config':load,'begin':store.begin,'exchange':exchanger,'seal':seal,'finish':store.finish}[stage]
                    target.side_effect = failure
                    with self.assertLogs('apple_credentials', level='WARNING') as logs:
                        result = capture(store, 'PRIVATE_OWNER', 'PRIVATE_CODE', 'PRIVATE_NONCE', exchanger=exchanger)
                self.assertEqual(result, {'status':'unavailable'})
                self.assertEqual(len(logs.records), 1)
                record = logs.records[0]
                self.assertEqual(record.getMessage(), f'operation=apple_credential_capture category={expected}')
                self.assertIsNone(record.exc_info)
                self.assertIsNone(record.stack_info)

    def test_success_duplicates_and_logging_failure_preserve_results(self):
        store = MemoryStore()
        config = configuration()
        with self.assertNoLogs('apple_credentials', level='WARNING'):
            for _ in range(2):
                self.assertEqual(capture(store,'owner','code','nonce',config=config,
                    exchanger=lambda *args: 'refresh'), {'status':'stored'})
        store.begin('owner',hashlib.sha256(b'pending-code').digest())
        with self.assertLogs('apple_credentials', level='WARNING') as logs:
            self.assertEqual(capture(store,'owner','pending-code','nonce',config=config),{'status':'unavailable'})
        self.assertEqual(logs.records[0].getMessage(),
                         'operation=apple_credential_capture category=attempt_unresolved')
        with patch('apple_credentials.logging.getLogger') as logger:
            logger.return_value.warning.side_effect = RuntimeError('broken sink')
            self.assertEqual(capture(store,'owner','pending-code','nonce',config=config),{'status':'unavailable'})

    def test_unknown_category_cannot_reach_logs(self):
        for value in ('PRIVATE_SENTINEL', ['PRIVATE_SENTINEL']):
            with self.assertLogs('apple_credentials', level='WARNING') as logs:
                _log_failure(value)
            self.assertEqual(logs.records[0].getMessage(),
                             'operation=apple_credential_capture category=apple_exchange_failed')


class ConfigTests(unittest.TestCase):
    def test_valid_config_and_malformed_variants(self):
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        env = dict(APPLE_CREDENTIAL_ENVIRONMENT='dev',APPLE_NATIVE_CLIENT_ID='com.familycaragent.app.dev',
                   SUPABASE_URL='https://jouhqvbxhsvkluwkqmdg.supabase.co',APPLE_TEAM_ID='ABCDEFGHIJ',APPLE_KEY_ID='KLMNOPQRST',
                   APPLE_PRIVATE_KEY_BASE64=base64.b64encode(pem).decode(),APPLE_CREDENTIAL_ACTIVE_KEY_ID='v1',
                   APPLE_CREDENTIAL_KEYS_JSON=json.dumps({'v1':base64.b64encode(os.urandom(32)).decode()}))
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(Config.load().client,env['APPLE_NATIVE_CLIENT_ID'])
        for key in env:
            with self.subTest(key=key), patch.dict(os.environ,dict(env,**{key:'invalid'}),clear=True), self.assertRaises(CaptureUnavailable):
                Config.load()
        with patch.dict(os.environ,{},clear=True), self.assertRaises(CaptureUnavailable):
            Config.load()
        with patch.dict(os.environ,dict(env,NATIVE_PUSH_ENCRYPTION_KEY=json.loads(env['APPLE_CREDENTIAL_KEYS_JSON'])['v1']),clear=True), self.assertRaises(CaptureUnavailable):
            Config.load()


class SQLBoundaryTests(unittest.TestCase):
    def test_attempt_transaction_exits_before_external_exchange(self):
        pool, conn = MagicMock(), MagicMock()
        pool.connection.return_value.__enter__.return_value = conn
        events = []
        conn.transaction.return_value.__exit__.side_effect = lambda *args: events.append('commit') or False
        conn.execute.return_value.fetchone.side_effect = [None, (0,), (1,)]
        with patch('apple_credentials.lock_identity'), patch('apple_credentials.require_auth'), patch('apple_credentials.linked_subject',return_value='sub'):
            self.assertEqual(Store(pool).begin('owner',b'digest'),(1,'sub','pending'))
        self.assertEqual(events,['commit'])

    def test_final_write_and_success_marker_share_one_transaction(self):
        pool, conn = MagicMock(), MagicMock()
        pool.connection.return_value.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = (8,)
        with patch('apple_credentials.lock_identity'), patch('apple_credentials.require_auth'), patch('apple_credentials.linked_subject',return_value='sub'):
            Store(pool).finish('owner',8,'sub',configuration(),b'ciphertext')
        conn.transaction.assert_called_once()
        calls = conn.execute.call_args_list
        self.assertIn('INSERT INTO apple_credentials', calls[1].args[0])
        self.assertEqual(calls[1].args[1][-1],b'ciphertext')
        self.assertIn("SET status='stored'",calls[2].args[0])
        self.assertEqual(conn.transaction.return_value.__exit__.call_args.args,(None,None,None))

    def test_migration_server_only_and_retains_revocation_material(self):
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[2] / 'supabase/manual_migrations/2026111401_apple_credentials.sql').read_text()
        for table in ('apple_credentials','apple_credential_attempts'):
            self.assertIn(f'ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY',sql)
        self.assertIn('FROM PUBLIC, anon, authenticated',sql)
        self.assertNotIn('REFERENCES auth.users',sql)
        self.assertIn('UNIQUE(auth_user_id, code_digest)',sql)
        self.assertIn('BEGIN;',sql)
        self.assertIn('COMMIT;',sql)

    def test_identity_lookup_requires_exact_server_binding(self):
        conn = MagicMock()
        for rows in ([],[('one','two')],[('one','one'),('two','two')]):
            conn.execute.return_value.fetchall.return_value = rows
            with self.assertRaises(CaptureUnavailable):
                linked_subject(conn,'owner')
        conn.execute.return_value.fetchall.return_value = [('one','one')]
        self.assertEqual(linked_subject(conn,'owner'),'one')
        self.assertEqual(conn.execute.call_args.args[1],('owner',))

    def test_claim_committed_before_exchange_and_rate_limit(self):
        pool, conn = MagicMock(), MagicMock()
        pool.connection.return_value.__enter__.return_value = conn
        store = Store(pool)
        with patch('apple_credentials.lock_identity') as lock, patch('apple_credentials.require_auth') as live, patch('apple_credentials.linked_subject',return_value='sub'):
            conn.execute.return_value.fetchone.side_effect = [None,(5,)]
            with self.assertRaises(CaptureUnavailable):
                store.begin('owner',b'digest')
            lock.assert_called_once_with(conn,'owner',exclusive=True)
            live.assert_called_once_with(conn,'owner')
            self.assertFalse(any('INSERT' in c.args[0] for c in conn.execute.call_args_list))

    def test_stale_generation_cannot_write_credentials(self):
        pool, conn = MagicMock(), MagicMock()
        pool.connection.return_value.__enter__.return_value = conn
        with patch('apple_credentials.lock_identity'), patch('apple_credentials.require_auth'), patch('apple_credentials.linked_subject',return_value='sub'):
            conn.execute.return_value.fetchone.return_value = (9,)
            with self.assertRaises(CaptureUnavailable):
                Store(pool).finish('owner',8,'sub',configuration(),b'ciphertext')
            self.assertFalse(any('INSERT' in c.args[0] for c in conn.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
