"""Production diagnostics: synthetic provider/database; no external services."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import native_push_diagnostics as d
from native_push_fcm import Fcm, Result
from native_push_process import Supervisor
from native_push_worker import challenge_pass

ENV = {'NATIVE_PUSH_ENVIRONMENT': 'prod'}
CONFIG = SimpleNamespace(environment='prod')


class ProductionDiagnosticsTests(unittest.TestCase):
    def event(self, **overrides):
        return dict(stage='transition', result='observed', reason='explicit_revocation',
                    state='cancelled', challenge_ref=str(uuid4()), installation_ref=str(uuid4()),
                    http_status=None, fcm_code=None, **overrides)

    def test_closed_schema_and_no_raw_values(self):
        event = self.event()
        self.assertTrue(d.production_valid(event))
        for field in event:
            with self.subTest(field=field):
                self.assertFalse(d.production_valid({**event, field: 'PRIVATE_TOKEN_NONCE'}))
        for value in ([], {}, True, 2000):
            self.assertFalse(d.production_valid({**event, 'stage': value}))
        with patch.object(d.logging, 'getLogger') as logger:
            d._publish({**event, 'token': 'PRIVATE'})
            logger.assert_not_called()

    def test_commit_only_and_distinct_reasons(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(d, '_publish') as publish:
            for reason in ('registration_replacement', 'explicit_revocation', 'capability_revocation',
                           'generation_mismatch', 'verification_limit', 'token_conflict'):
                with d.committed():
                    d.trace(CONFIG, 'ios', uuid4(), uuid4(), reason=reason, state='cancelled')
                self.assertEqual(publish.call_args.args[0]['reason'], reason)
            publish.reset_mock()
            with self.assertRaises(RuntimeError):
                with d.committed():
                    d.trace(CONFIG, 'ios', uuid4(), uuid4(), reason='explicit_revocation', state='cancelled')
                    raise RuntimeError('PRIVATE')
            publish.assert_not_called()

    def test_production_subprocess_visible_without_raw_output(self):
        code = ("from types import SimpleNamespace; import native_push_diagnostics as d; "
                "print('PRIVATE_STDOUT'); import sys; print('PRIVATE_STDERR',file=sys.stderr); "
                f"d._publish({self.event()!r}); d._publish({self.event()!r})")
        with patch.dict(os.environ, ENV), self.assertLogs('native_push_diagnostics') as logs:
            result = asyncio.run(Supervisor([sys.executable, '-B', '-c', code], seconds=5).run(asyncio.Event()))
        self.assertEqual(result, 'complete')
        self.assertEqual(len(logs.output), 2)
        self.assertNotIn('PRIVATE', str(logs.output))

    def test_worker_outcomes_and_committed_state(self):
        for outcome, state in [('accepted', 'pending'), ('transport_uncertain', 'pending'),
                               ('rate_limited', 'pending'), ('provider_unavailable', 'pending'),
                               ('configuration', 'cancelled'), ('unregistered', 'cancelled')]:
            with self.subTest(outcome=outcome):
                conn = Mock()
                row = (uuid4(), uuid4(), 7, b'PRIVATE', 'PRIVATE', b'PRIVATE',
                       datetime.now(timezone.utc), 'ios', 1)
                conn.execute.return_value.fetchone.side_effect = [row, (1,), (state,)]
                conn.execute.return_value.rowcount = 1
                @contextmanager
                def connection():
                    yield conn
                pool = SimpleNamespace(connection=connection)
                config = Mock(environment='prod', project='family-car-agent')
                config.open.return_value = 'PRIVATE'
                provider = Mock(diagnostic_http_status=200 if outcome == 'accepted' else 401,
                                diagnostic_fcm_code=None)
                provider.send.return_value = Result(outcome)
                with patch.dict(os.environ, ENV, clear=True), self.assertLogs('native_push_diagnostics') as logs:
                    self.assertTrue(challenge_pass(pool, config, provider))
                events = [json.loads(line.split('diagnostic ', 1)[1]) for line in logs.output]
                self.assertEqual(events[0]['reason'], 'selected')
                self.assertEqual(events[-1]['state'], state)
                self.assertEqual(events[-1]['result'], outcome)
                self.assertEqual(events[-1]['reason'], 'terminal_delivery_failure' if state == 'cancelled' else 'delivery_result')
                self.assertNotIn('PRIVATE', str(logs.output))
                sql = ' '.join(call.args[0] for call in conn.execute.call_args_list)
                if outcome in ('accepted', 'transport_uncertain'):
                    self.assertIn('send_attempts=3', sql)
                if outcome in ('rate_limited', 'provider_unavailable'):
                    self.assertIn('next_attempt_at=LEAST', sql)

    def test_fcm_categories_sanitize_metadata(self):
        config = Mock(environment='prod', project='family-car-agent', ios_topic='com.familycaragent.app')
        for status, code, result in [(200, None, 'accepted'), (401, 'THIRD_PARTY_AUTH_ERROR', 'configuration'),
                                     (404, 'UNREGISTERED', 'unregistered'), (400, 'PRIVATE', 'invalid_payload'),
                                     (429, 'QUOTA_EXCEEDED', 'rate_limited'), (503, 'UNAVAILABLE', 'provider_unavailable')]:
            http = Mock()
            http.post.return_value.status_code = status
            http.post.return_value.headers = {}
            http.post.return_value.json.return_value = {'error': {'message': 'PRIVATE', 'details': [
                {'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode': code}]}}
            provider = Fcm(config, transport=http, clock=lambda: 1000)
            provider._token, provider._until = 'PRIVATE_AUTH', 2000
            with patch.dict(os.environ, ENV, clear=True):
                actual = provider.send('PRIVATE_TOKEN', {'kind': 'registration_challenge', 'nonce': 'PRIVATE_NONCE'},
                                       expires_at=datetime.fromtimestamp(2000, timezone.utc), platform='ios')
            self.assertEqual(actual.code, result)
            self.assertEqual(provider.diagnostic_http_status, status)
            self.assertEqual(provider.diagnostic_fcm_code, code if code in d.FCM_CODES else None)

    def test_registration_replacement_and_revocation_call_sites(self):
        import native_push_registration as registration
        import native_push_revocation as revocation
        config = Mock(environment='prod', project='family-car-agent', key_id='synthetic')
        config.fingerprint.return_value = b'synthetic'
        user = SimpleNamespace(user_id=1, family_id=2, auth_user_id=str(uuid4()))
        ref, challenge = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        conn = Mock()
        conn.execute.return_value.fetchone.side_effect = [(now,), None, (0,), (1, 'ios', config.project, 1, 'pending'), (0,)]
        conn.execute.return_value.fetchall.return_value = [(challenge,)]
        with patch.dict(os.environ, ENV), patch.object(registration, 'scope'), \
             patch.object(registration, 'key_cohort'), patch.object(revocation, 'permitted', return_value=True), \
             patch.object(d, '_publish') as publish:
            with d.committed():
                result = registration.begin(conn, user, config, installation_ref=ref,
                                            request_id=uuid4(), platform='ios', token='PRIVATE')
            self.assertEqual(result['code'], 'CHALLENGE_PENDING')
            self.assertEqual(publish.call_args.args[0]['reason'], 'registration_replacement')
            self.assertEqual(publish.call_args.args[0]['challenge_ref'], str(challenge))
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = (1, revocation.digest('a' * 64))
        conn.execute.return_value.fetchall.return_value = [(challenge,)]
        with patch.dict(os.environ, ENV), patch.object(d, '_publish') as publish:
            with d.committed():
                self.assertEqual(revocation.cancel(conn, config, ref, 'a' * 64)['code'], 'REVOKED')
            self.assertEqual(publish.call_args.args[0]['reason'], 'capability_revocation')
            self.assertNotIn('a' * 64, str(publish.call_args))
        conn = Mock()
        conn.execute.return_value.fetchone.side_effect = [(1,), (1,), (ref,)]
        conn.execute.return_value.fetchall.return_value = [(challenge,)]
        with patch.dict(os.environ, ENV), patch.object(registration, 'scope'), patch.object(d, '_publish') as publish:
            with d.committed():
                self.assertEqual(registration.revoke(conn, user, config, ref, 1)['code'], 'REVOKED')
            self.assertEqual(publish.call_args.args[0]['reason'], 'explicit_revocation')
