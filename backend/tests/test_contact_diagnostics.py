import asyncio
import contextlib
import io
import json
import logging
import smtplib
import unittest
from unittest.mock import patch
import requests
import contact_diagnostics as diag
import contact_mail as mail
import contact_security as security
from tests.test_contact import CONFIG, FIELDS, ContactTests


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.token = diag.request_id.set('a' * 32)
        self.addCleanup(diag.request_id.reset, self.token)
        self.enterContext(patch.object(diag.logger, 'handlers', [diag.SafeHandler()]))
        self.enterContext(patch.object(diag.logger, 'level', logging.INFO))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_smtp_categories_preserve_results(self):
        for stage, error, code, result in [
            ('connect', OSError('PRIVATE'), 'smtp_connect_failed', 'smtp_unavailable'),
            ('login', smtplib.SMTPAuthenticationError(535, b'PRIVATE'), 'smtp_auth_failed', 'smtp_unavailable'),
            ('sendmail', smtplib.SMTPSenderRefused(550, b'PRIVATE', 'private@example.test'), 'smtp_rejected', 'smtp_unavailable'),
            ('sendmail', TimeoutError('PRIVATE'), 'delivery_uncertain', 'delivery_uncertain'),
            ('login', RuntimeError('PRIVATE'), 'unexpected_failure', 'smtp_unavailable'),
        ]:
            self.output.seek(0); self.output.truncate()
            with patch.object(mail.smtplib, 'SMTP_SSL') as factory:
                if stage == 'connect': factory.side_effect = error
                else: getattr(factory.return_value, stage).side_effect = error
                self.assertEqual(mail.deliver(CONFIG, FIELDS, []), result)
            self.assertIn('code=' + code, self.output.getvalue())
            self.assertNotIn('PRIVATE', self.output.getvalue())
            self.assertNotIn('example.test', self.output.getvalue())

    def test_turnstile_and_transport_failure(self):
        with patch.object(security.requests, 'post', side_effect=requests.Timeout('PRIVATE')):
            self.assertEqual(security.verify_turnstile(CONFIG, 'PRIVATE'), 'verification_unavailable')
        self.assertIn('code=turnstile_connection_failed', self.output.getvalue())
        with patch.object(diag.logger, 'info', side_effect=RuntimeError('PRIVATE')):
            diag.report('request', 'unexpected_failure')
        self.assertNotIn('PRIVATE', self.output.getvalue())

    def test_turnstile_categories(self):
        from urllib3.exceptions import ReadTimeoutError
        cases = [
            ('tls_failed', requests.exceptions.SSLError('PRIVATE')),
            ('connect_timeout', requests.ConnectTimeout('PRIVATE')),
            ('read_timeout', requests.ReadTimeout('PRIVATE')),
            ('read_timeout', requests.ConnectionError(ReadTimeoutError(None, '/', 'PRIVATE'))),
            ('connection_failed', requests.ConnectionError('PRIVATE')),
        ]
        for code, error in cases:
            with self.subTest(code=code), patch.object(security.requests, 'post', side_effect=error):
                self.output.seek(0); self.output.truncate()
                self.assertEqual(security.verify_turnstile(CONFIG, 'PRIVATE'), 'verification_unavailable')
                self.assertEqual(self.output.getvalue().strip(), 'CONTACT_DIAG request_id=' + 'a'*32 + ' stage=turnstile code=turnstile_' + code)
        for status, body, code in [(403, b'PRIVATE', 'http_non_200'), (200, b'x'*16385, 'response_too_large'), (200, b'PRIVATE', 'invalid_json')]:
            with patch.object(security.requests, 'post') as post:
                response = post.return_value.__enter__.return_value
                response.status_code = status
                response.iter_content.return_value = [body]
                self.output.seek(0); self.output.truncate()
                self.assertEqual(security.verify_turnstile(CONFIG, 'PRIVATE'), 'verification_unavailable')
                suffix = ' http_status=403' if status == 403 else ''
                self.assertEqual(self.output.getvalue().strip(), 'CONTACT_DIAG request_id=' + 'a'*32 + ' stage=turnstile code=turnstile_' + code + suffix)
                self.assertEqual(post.call_args.kwargs, dict(data={'secret': CONFIG.turnstile_secret, 'response': 'PRIVATE'}, timeout=(3, 5), allow_redirects=False, stream=True))

    def test_http_status_allowlist(self):
        for invalid in ['403 PRIVATE', '403', True, 99, 600, 200, None]:
            self.output.seek(0); self.output.truncate()
            diag.report('turnstile', 'turnstile_http_non_200', http_status=invalid)
            self.assertEqual(self.output.getvalue(), '')
        diag.report('request', 'unexpected_failure', http_status=403)
        self.assertEqual(self.output.getvalue(), '')

    def test_http_400_safe_codes(self):
        cases = [
            (json.dumps({'error-codes': [code]}).encode(), [code])
            for code in sorted(diag.CLOUDFLARE_CODES)
        ] + [
            (b'{"error-codes":["bad-request","invalid-input-secret","bad-request"]}', ['bad-request', 'invalid-input-secret']),
            (b'{"error-codes":["PRIVATE"]}', []),
            (b'not JSON PRIVATE', []),
            (b' ' * 16385, []),
            (b'{"error-codes":["bad-request","PRIVATE",{}],"secret":"PRIVATE","email":"PRIVATE","success":true}', ['bad-request']),
            (b'{"error-codes":"bad-request"}', []),
            (b'[]', []),
        ]
        prefix = 'CONTACT_DIAG request_id=' + 'a'*32 + ' stage=turnstile code=turnstile_http_non_200 http_status=400'
        for body, codes in cases:
            with self.subTest(codes=codes), patch.object(security.requests, 'post') as post:
                response = post.return_value.__enter__.return_value
                response.status_code = 400
                response.iter_content.return_value = [body]
                self.output.seek(0); self.output.truncate()
                self.assertEqual(security.verify_turnstile(CONFIG, 'PRIVATE'), 'verification_unavailable')
                self.assertEqual(self.output.getvalue().splitlines(),
                                 [prefix + (' cloudflare_code=' + code if code else '') for code in codes or [None]])
                post.assert_called_once()
                response.iter_content.assert_called_once_with(4096)

    def test_http_400_stream_failure_and_limit(self):
        for chunks in [iter([b'x'*16384, b'x', b'PRIVATE']), None]:
            with patch.object(security.requests, 'post') as post:
                response = post.return_value.__enter__.return_value
                response.status_code = 400
                if chunks is None:
                    response.iter_content.side_effect = requests.ReadTimeout('PRIVATE')
                else:
                    response.iter_content.return_value = chunks
                self.output.seek(0); self.output.truncate()
                self.assertEqual(security.verify_turnstile(CONFIG, 'PRIVATE'), 'verification_unavailable')
                self.assertTrue(self.output.getvalue().strip().endswith('http_status=400'))
                if chunks is not None:
                    self.assertEqual(next(chunks), b'PRIVATE')

    def test_provider_code_log_allowlist(self):
        for invalid in ['PRIVATE', 'bad-request\nPRIVATE', ['bad-request'], 1, '']:
            diag.report('turnstile', 'turnstile_http_non_200', http_status=400, cloudflare_code=invalid)
        diag.report('request', 'unexpected_failure', cloudflare_code='bad-request')
        self.assertEqual(self.output.getvalue(), '')

    def test_strict_schema_ignores_message_and_exception(self):
        record = logging.LogRecord('x', 20, '', 0, 'PRIVATE', (), None)
        record.contact_id = 'a' * 32
        record.contact_stage = 'smtp_auth'
        record.contact_code = 'smtp_auth_failed'
        self.assertEqual(diag.safe_line(record), 'CONTACT_DIAG request_id=' + 'a'*32 + ' stage=smtp_auth code=smtp_auth_failed')
        record.contact_code = 'PRIVATE'
        self.assertIsNone(diag.safe_line(record))
        record.contact_code = 'smtp_auth_failed'
        record.contact_id = 'private@example.test'
        self.assertIsNone(diag.safe_line(record))

    def test_request_context_propagates_to_thread_and_resets(self):
        from starlette.concurrency import run_in_threadpool
        async def check():
            await run_in_threadpool(diag.report, 'request', 'unexpected_failure')
        asyncio.run(check())
        self.assertIn('request_id=' + 'a'*32, self.output.getvalue())


class ApiDiagnosticTests(ContactTests):
    def test_http_400_preserves_api_and_never_sends_mail(self):
        self.verify_turnstile.side_effect = security.verify_turnstile
        with patch.object(security.requests, 'post') as post:
            upstream = post.return_value.__enter__.return_value
            upstream.status_code = 400
            upstream.iter_content.return_value = [b'{"error-codes":["invalid-input-secret"],"success":true}']
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'verification_unavailable')
        self.deliver.assert_not_called()

    def test_configuration_and_unexpected_match_response_id(self):
        with patch.object(diag.logger, 'handlers', [diag.SafeHandler()]), patch.object(diag.logger, 'level', logging.INFO):
            for configuration, code in [(None, 'configuration_invalid'), (CONFIG, 'unexpected_failure')]:
                self.load.return_value = configuration
                self.verify_turnstile.side_effect = RuntimeError('PRIVATE')
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    response = self.post()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['code'], 'service_unavailable')
                self.assertIn(response.json()['request_id'], output.getvalue())
                self.assertIn('code=' + code, output.getvalue())
                self.assertNotIn('PRIVATE', output.getvalue())
                self.assertEqual(diag.request_id.get(), '')
