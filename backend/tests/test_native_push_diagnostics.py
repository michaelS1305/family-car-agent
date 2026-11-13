"""Synthetic diagnostics only: no database, credentials or provider requests."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

import native_push_diagnostics as diag
from native_push_fcm import Fcm, Result
from native_push_process import Supervisor
from native_push_security import ConfigurationError
from native_push_worker import challenge_pass

ENV = {diag.FLAG: 'true', 'NATIVE_PUSH_ENVIRONMENT': 'dev',
       'SUPABASE_URL': 'https://jouhqvbxhsvkluwkqmdg.supabase.co'}
EVENT = dict(stage='fcm_request_response', result='configuration', http_status=401,
             fcm_code='THIRD_PARTY_AUTH_ERROR', cancelled=True)


class DiagnosticTests(unittest.TestCase):
    def test_cancellation_during_shutdown_closes_socket(self):
        async def check():
            entered = asyncio.Event()
            async def shutdown():
                entered.set()
                await asyncio.Event().wait()
            channel = diag.Channel.__new__(diag.Channel)
            channel.key = 'synthetic'
            channel.socket = Mock()
            channel.socket.getsockname.return_value = ('127.0.0.1', 12345)
            socket = channel.socket
            child = Mock(returncode=0)
            child.poll.return_value = 0
            supervisor = Supervisor()
            with patch('native_push_process.Channel', return_value=channel), \
                 patch('native_push_process.subprocess.Popen', return_value=child), \
                 patch.object(supervisor, 'close', side_effect=shutdown), \
                 patch.object(channel, 'report') as report:
                task = asyncio.create_task(supervisor.run(asyncio.Event()))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                socket.close.assert_called_once()
                self.assertIsNone(channel.socket)
                report.assert_not_called()
        asyncio.run(check())

    def test_spawn_failure_still_closes_channel(self):
        channel = Mock()
        with patch('native_push_process.Channel', return_value=channel), \
             patch('native_push_process.subprocess.Popen', side_effect=OSError('synthetic')):
            self.assertEqual(asyncio.run(Supervisor().run(asyncio.Event())), 'failed')
        channel.close.assert_called_once()

    def test_bad_packet_does_not_hide_following_valid_event(self):
        packets = [b'PRIVATE', b'\xff',
                   json.dumps({'key': 'wrong', 'event': EVENT}).encode(),
                   json.dumps({'key': 'test', 'event': {**EVENT, 'token': 'PRIVATE'}}).encode()]
        for packet in packets:
            channel = diag.Channel.__new__(diag.Channel)
            channel.key = 'test'
            channel.socket = Mock()
            channel.socket.recvfrom.side_effect = [
                (packet, ('127.0.0.1', 1)),
                (json.dumps({'key': 'test', 'event': EVENT}).encode(), ('127.0.0.1', 1))]
            with patch.dict(os.environ, ENV), self.assertLogs('native_push_diagnostics', level='WARNING') as logs:
                channel.report()
            self.assertEqual(channel.socket.recvfrom.call_count, 2)
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn('PRIVATE', logs.output[0])
            self.assertIn('THIRD_PARTY_AUTH_ERROR', logs.output[0])

    def test_gates(self):
        for env in ({}, {**ENV, diag.FLAG: 'false'}, {**ENV, 'NATIVE_PUSH_ENVIRONMENT': 'prod'},
                    {**ENV, 'SUPABASE_URL': 'https://production.invalid'}):
            with patch.dict(os.environ, env, clear=True), patch.object(diag.socket, 'socket') as socket:
                channel = diag.Channel()
                diag.emit(Mock(environment='dev'), 'ios', EVENT)
                channel.report(); channel.close()
                socket.assert_not_called()
        with patch.dict(os.environ, ENV, clear=True), patch.object(diag.socket, 'socket') as socket:
            diag.emit(Mock(environment='dev'), 'android', EVENT)
            diag.emit(Mock(environment='prod'), 'ios', EVENT)
            socket.assert_not_called()

    def test_schema_rejects_sensitive_or_unknown_fields(self):
        self.assertTrue(diag.valid(EVENT))
        for event in ({**EVENT, 'token': 'PRIVATE'}, {**EVENT, 'result': 'PRIVATE'},
                      {**EVENT, 'fcm_code': 'PRIVATE'}, {**EVENT, 'http_status': 'PRIVATE'},
                      {**EVENT, 'stage': 'PRIVATE'}, {**EVENT, 'cancelled': 1}):
            self.assertFalse(diag.valid(event))

    def test_real_subprocess_safe_channel(self):
        code = ("from types import SimpleNamespace; import native_push_diagnostics as d; "
                "print('PRIVATE_RAW_STDOUT'); "
                f"d.emit(SimpleNamespace(environment='dev'),'ios',{EVENT!r})")
        with patch.dict(os.environ, ENV), self.assertLogs('native_push_diagnostics', level='WARNING') as logs:
            result = asyncio.run(Supervisor([sys.executable, '-B', '-c', code], seconds=5).run(asyncio.Event()))
        self.assertEqual(result, 'complete')
        self.assertEqual(len(logs.output), 1)
        self.assertIn('THIRD_PARTY_AUTH_ERROR', logs.output[0])
        self.assertNotIn('PRIVATE', logs.output[0])

    def test_channel_failure_is_best_effort(self):
        with patch.dict(os.environ, ENV), patch.object(diag.socket, 'socket', side_effect=OSError('PRIVATE')):
            channel = diag.Channel()
            diag.emit(Mock(environment='dev'), 'ios', EVENT)
            channel.report(); channel.close()
            self.assertNotIn(diag.PORT, channel.environment())

    def test_channel_address_failure_does_not_block_spawn(self):
        channel = diag.Channel.__new__(diag.Channel)
        channel.key = 'synthetic'
        channel.socket = Mock()
        channel.socket.getsockname.side_effect = OSError('PRIVATE')
        env = channel.environment()
        self.assertNotIn(diag.PORT, env)
        self.assertNotIn(diag.KEY, env)
        self.assertIsNone(channel.socket)

    def test_parent_rejects_untrusted_packets_and_bounds_reads(self):
        with patch.dict(os.environ, ENV):
            for packet in (b'PRIVATE', b'x' * 1025,
                           json.dumps({'key': 'wrong', 'event': EVENT}).encode(),
                           json.dumps({'key': 'test', 'event': {**EVENT, 'token': 'PRIVATE'}}).encode()):
                channel = diag.Channel.__new__(diag.Channel)
                channel.key = 'test'
                channel.socket = Mock()
                channel.socket.recvfrom.return_value = (packet, ('127.0.0.1', 1))
                with patch.object(diag.logging, 'getLogger') as logger:
                    channel.report()
                    logger.assert_not_called()
                self.assertLessEqual(channel.socket.recvfrom.call_count, 4)

    def test_provider_metadata_does_not_change_payload_or_result(self):
        http = Mock(); http.post.return_value.status_code = 401
        http.post.return_value.json.return_value = {'error': {'message': 'PRIVATE', 'details': [
            {'@type': 'type.googleapis.com/google.firebase.fcm.v1.FcmError', 'errorCode': 'THIRD_PARTY_AUTH_ERROR'}]}}
        config = Mock(environment='dev', android_package='test', project='test')
        payloads = []
        for enabled in ('false', 'true'):
            provider = Fcm(config, transport=http, clock=lambda: 1000)
            provider._token, provider._until = 'PRIVATE', 2000
            with patch.dict(os.environ, {**ENV, diag.FLAG: enabled}):
                result = provider.send('PRIVATE', {'kind': 'registration_challenge'},
                                       expires_at=datetime.fromtimestamp(2000, timezone.utc), platform='ios')
            payloads.append(http.post.call_args.kwargs['json'])
            self.assertEqual(result.code, 'configuration')
            self.assertEqual(provider.diagnostic_http_status, 401 if enabled == 'true' else None)
            self.assertEqual(provider.diagnostic_fcm_code, 'THIRD_PARTY_AUTH_ERROR' if enabled == 'true' else None)
        self.assertEqual(*payloads)
        provider._token, provider._until = 'PRIVATE', 2000
        with patch.dict(os.environ, ENV):
            provider.send('PRIVATE', {'kind': 'refresh'}, expires_at=datetime.fromtimestamp(2000, timezone.utc), platform='android')
        self.assertIsNone(provider.diagnostic_http_status)

    def worker_event(self, result='configuration', failure=None, affected=1, platform='ios', real_transport=False):
        conn = Mock()
        row = ('challenge', 'installation', 1, b'PRIVATE', 'key', b'PRIVATE',
               datetime.now(timezone.utc), platform, 1)
        conn.execute.return_value.fetchone.side_effect = [row, None if failure == 'eligibility_validation' else (1,)] if failure not in ('credentials_preparation', 'token_decryption') else [row]
        conn.execute.return_value.rowcount = affected
        @contextmanager
        def connection():
            yield conn
        pool = Mock(); pool.connection = connection
        config = Mock(environment='dev', project='test'); config.open.return_value = 'PRIVATE'
        provider = Mock(diagnostic_http_status=401, diagnostic_fcm_code='THIRD_PARTY_AUTH_ERROR')
        provider.send.return_value = Result(result)
        if failure == 'credentials_preparation':
            provider.prepare.side_effect = ConfigurationError()
        if failure == 'token_decryption':
            config.open.side_effect = ConfigurationError()
        with patch.object(diag, 'emit', wraps=diag.emit if real_transport else None) as emit:
            self.assertTrue(challenge_pass(pool, config, provider))
        event = emit.call_args.args[2]
        self.assertNotIn('PRIVATE', json.dumps(event))
        return event

    def test_worker_stages_and_cancellation_rowcount(self):
        for stage in ('credentials_preparation', 'token_decryption'):
            event = self.worker_event(failure=stage)
            self.assertEqual(event['stage'], stage)
            self.assertIsNone(event['http_status'])
            self.assertTrue(event['cancelled'])
        self.assertEqual(self.worker_event(failure='eligibility_validation')['stage'], 'eligibility_validation')
        self.assertEqual(self.worker_event()['stage'], 'fcm_request_response')
        self.assertFalse(self.worker_event(affected=0)['cancelled'])
        for result in ('accepted', 'transport_uncertain', 'rate_limited', 'provider_unavailable'):
            self.assertFalse(self.worker_event(result=result)['cancelled'])

    def test_transport_failure_does_not_change_worker(self):
        # Exercise the real guarded emitter with a failing socket via an adapter.
        real_emit = diag.emit
        with patch.dict(os.environ, {**ENV, diag.KEY: 'synthetic', diag.PORT: '1'}), \
             patch.object(diag.socket, 'socket', side_effect=OSError('PRIVATE')):
            real_emit(Mock(environment='dev'), 'ios', EVENT)
            self.assertTrue(self.worker_event(real_transport=True)['cancelled'])
