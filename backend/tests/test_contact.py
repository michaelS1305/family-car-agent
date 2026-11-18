import asyncio
from dataclasses import replace
from email import policy
from email.parser import BytesParser
import os
import smtplib
import struct
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
import requests

import contact_api as api
import contact_mail as mail
import contact_security as security

CONFIG = mail.Config('smtp.example.test', 465, 'smtp-user', 'synthetic-password',
                     'sender@example.test', 'support@example.test', 5, 'synthetic-secret', 'example.test')
FIELDS = dict(name='בדיקה', email='reader@example.test', subject='תקלה', description='תוכן בעברית', turnstile_token='synthetic-token')
PDF = b'%PDF-1.7\nsynthetic\n%%EOF'


class ContactTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(api.router)
        self.client = TestClient(app)
        for target, value in [('Config.load', CONFIG), ('verify_turnstile', 'verified'), ('deliver', 'accepted')]:
            mock = self.enterContext(patch('contact_api.' + target, return_value=value))
            setattr(self, target.split('.')[-1], mock)
        self.enterContext(patch.object(api, 'limits', security.Limits()))

    def post(self, fields=None, files=None, headers=None):
        parts = [(key, (None, value)) for key, value in (FIELDS if fields is None else fields).items()]
        parts += [('attachments', file) for file in (files or [])]
        return self.client.post('/api/contact', files=parts, headers=headers or {})

    def test_success_fixed_data_and_no_personal_logs(self):
        with self.assertLogs('contact', 'INFO') as logs:
            result = self.post(files=[('../../test.pdf', PDF, 'application/pdf')])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['request_id']), 32)
        args = self.deliver.call_args.args
        self.assertEqual(args[0], CONFIG)
        self.assertEqual(args[1]['email'], FIELDS['email'])
        self.assertNotIn('turnstile_token', args[1])
        self.assertEqual(args[2], [('test.pdf', 'application/pdf', PDF)])
        for secret in [*FIELDS.values(), 'test.pdf', CONFIG.password, CONFIG.turnstile_secret]:
            self.assertNotIn(secret, ''.join(logs.output))
            self.assertNotIn(secret, result.text)

    def test_field_validation(self):
        cases = [dict(FIELDS, name=''), dict(FIELDS, name='x'*101), dict(FIELDS, email='a@b'),
                 dict(FIELDS, email='a@example.test,b@example.test'), dict(FIELDS, subject='other'),
                 dict(FIELDS, description='x'*1001), dict(FIELDS, turnstile_token=''),
                 dict(FIELDS, name='x\r\nBcc: x@example.test'), dict(FIELDS, email='x@example.test\n')]
        cases += [{key: value for key, value in FIELDS.items() if key != missing} for missing in FIELDS]
        for fields in cases:
            with self.subTest(fields=list(fields)):
                api.limits = security.Limits()
                self.assertEqual(self.post(fields).status_code, 422)
        self.deliver.assert_not_called()

    def test_extra_and_duplicate_fields(self):
        self.assertEqual(self.post(dict(FIELDS, to='other@example.test')).status_code, 422)
        parts = [(k, (None, v)) for k, v in FIELDS.items()] + [('email', (None, 'second@example.test'))]
        self.assertEqual(self.client.post('/api/contact', files=parts).status_code, 422)

    def test_file_count_sizes_and_cleanup(self):
        handles = []
        original = tempfile.SpooledTemporaryFile
        def tracked(*args, **kwargs):
            handle = original(*args, **kwargs)
            handles.append(handle)
            return handle
        cases = [([('a.pdf', PDF, 'application/pdf')]*6, 422),
                 ([('a.pdf', b'x'*5_000_001, 'application/pdf')], 413),
                 ([('a.pdf', b'x'*3_400_000, 'application/pdf')]*3, 413),
                 ([('a.pdf', b'x'*3_333_334, 'application/pdf')]*3, 413),
                 ([('a.exe', PDF, 'application/pdf')], 415),
                 ([('a.pdf', PDF, 'image/png')], 415),
                 ([('a.png', PDF, 'image/png')], 415),
                 ([('a.pdf', b'', 'application/pdf')], 415),
                 ([('a.pdf', PDF, 'application/pdf')], 200)]
        with patch('starlette.formparsers.SpooledTemporaryFile', side_effect=tracked), patch.object(api.tempfile, 'SpooledTemporaryFile', side_effect=tracked):
            for files, expected in cases:
                api.limits = security.Limits()
                self.assertEqual(self.post(files=files).status_code, expected)
                self.assertTrue(all(handle.closed for handle in handles))

    def test_turnstile_failure_and_disabled(self):
        for outcome, status in [('verification_failed', 422), ('verification_unavailable', 503)]:
            self.verify_turnstile.return_value = outcome
            self.assertEqual(self.post().status_code, status)
        self.load.return_value = None
        self.assertEqual(self.post().status_code, 503)
        self.deliver.assert_not_called()

    def test_exact_file_boundaries_and_five_files(self):
        large = b'%PDF-1.7\n' + b' '* (5_000_000 - 14) + b'%%EOF'
        self.assertEqual(len(large), 5_000_000)
        self.assertEqual(self.post(files=[('a.pdf', large, 'application/pdf')]*2).status_code, 200)
        self.assertEqual(self.post(files=[('a.pdf', PDF, 'application/pdf')]*5).status_code, 200)

    def test_malformed_and_oversized_field_cleanup(self):
        handles = []
        original = tempfile.SpooledTemporaryFile
        def tracked(*args, **kwargs):
            result = original(*args, **kwargs)
            handles.append(result)
            return result
        with patch('starlette.formparsers.SpooledTemporaryFile', side_effect=tracked), patch.object(api.tempfile, 'SpooledTemporaryFile', side_effect=tracked):
            self.assertEqual(self.post(dict(FIELDS, description='x'*9000)).status_code, 422)
            body = b'--edge\r\nContent-Disposition: form-data; name="attachments"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.7\n'
            result = self.client.post('/api/contact', content=body, headers={'Content-Type': 'multipart/form-data; boundary=edge'})
            self.assertIn(result.status_code, (422, 503))
            self.assertTrue(all(handle.closed for handle in handles))

    def test_send_and_verification_exceptions_release_resources(self):
        self.deliver.side_effect = RuntimeError('sensitive diagnostic')
        result = self.post(files=[('a.pdf', PDF, 'application/pdf')])
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('sensitive', result.text)
        self.assertEqual(api.limits.smtp, 0)
        self.assertEqual(api.limits.uploads, 0)

    def test_limiter_does_not_trust_forwarded_headers(self):
        for index in range(5):
            self.assertEqual(self.post(headers={'X-Forwarded-For': f'192.0.2.{index}'}).status_code, 200)
        result = self.post(headers={'X-Forwarded-For': '192.0.2.99'})
        self.assertEqual(result.status_code, 429)
        self.assertIn('Retry-After', result.headers)

    def test_concurrent_smtp_limit_and_failure_release(self):
        api.limits.smtp = 2
        self.assertEqual(self.post().status_code, 429)
        self.deliver.assert_not_called()
        api.limits.smtp = 0
        self.deliver.return_value = 'delivery_uncertain'
        self.assertEqual(self.post().json()['code'], 'delivery_uncertain')
        self.assertEqual(api.limits.smtp, 0)
        self.assertEqual(api.limits.uploads, 0)
        self.deliver.assert_called_once()

    def test_streaming_limit_false_length_and_disconnect(self):
        async def run(chunks):
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/contact', 'headers':
                     [(b'content-type', b'multipart/form-data; boundary=x'), (b'content-length', b'1')],
                     'client': ('192.0.2.1', 1)}
            iterator = iter(chunks)
            async def receive():
                return next(iterator)
            return await api.submit(Request(scope, receive))
        chunks = [{'type': 'http.request', 'body': b'x'*1_000_000, 'more_body': True}]*11
        self.assertEqual(asyncio.run(run(chunks)).status_code, 413)
        self.assertEqual(asyncio.run(run([{'type': 'http.disconnect'}])).status_code, 503)
        self.assertEqual(api.limits.uploads, 0)
        self.verify_turnstile.assert_not_called()

    def test_parser_cancellation_closes_partial_file(self):
        handles = []
        original = tempfile.SpooledTemporaryFile
        def tracked(*args, **kwargs):
            handle = original(*args, **kwargs)
            handles.append(handle)
            return handle
        async def run():
            async def stream():
                yield b'--x\r\nContent-Disposition: form-data; name="attachments"; filename="a.pdf"\r\n\r\ndata'
                raise asyncio.CancelledError()
            from starlette.datastructures import Headers
            parser = api.ContactParser(Headers({'content-type': 'multipart/form-data; boundary=x'}), stream())
            try:
                await parser.parse()
            finally:
                for file in parser.opened_files:
                    file.close()
        with patch('starlette.formparsers.SpooledTemporaryFile', side_effect=tracked):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(run())
        self.assertTrue(handles)
        self.assertTrue(all(handle.closed for handle in handles))


class ServiceTests(unittest.TestCase):
    def test_mime_and_both_tls_modes(self):
        for port in (465, 587):
            with patch.object(mail.smtplib, 'SMTP_SSL') as implicit, patch.object(mail.smtplib, 'SMTP') as explicit:
                smtp = (implicit if port == 465 else explicit).return_value
                smtp.sendmail.return_value = {}
                self.assertEqual(mail.deliver(replace(CONFIG, port=port), FIELDS, [('a.pdf', 'application/pdf', PDF)]), 'accepted')
                sender, recipients, wire = smtp.sendmail.call_args.args
                self.assertEqual((sender, recipients), (CONFIG.sender, [CONFIG.recipient]))
                message = BytesParser(policy=policy.default).parsebytes(wire)
                self.assertEqual(str(message['Reply-To']), FIELDS['email'])
                self.assertEqual(str(message['From']), CONFIG.sender)
                self.assertEqual(str(message['To']), CONFIG.recipient)
                self.assertIn(FIELDS['description'], message.get_body().get_content())
                self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True), PDF)
                if port == 587:
                    smtp.starttls.assert_called_once()
                smtp.close.assert_called_once()

    def test_smtp_failures_no_retry(self):
        for stage, error, expected in [('login', smtplib.SMTPAuthenticationError(535, b'secret'), 'smtp_unavailable'),
                                       ('login', TimeoutError(), 'smtp_unavailable'),
                                       ('sendmail', TimeoutError(), 'delivery_uncertain'),
                                       ('sendmail', RuntimeError('private'), 'delivery_uncertain'),
                                       ('sendmail', smtplib.SMTPServerDisconnected(), 'delivery_uncertain'),
                                       ('sendmail', smtplib.SMTPRecipientsRefused({'private': (550, b'private')}), 'smtp_unavailable'),
                                       ('sendmail', smtplib.SMTPDataError(554, b'private'), 'smtp_unavailable')]:
            with patch.object(mail.smtplib, 'SMTP_SSL') as factory:
                smtp = factory.return_value
                getattr(smtp, stage).side_effect = error
                self.assertEqual(mail.deliver(CONFIG, FIELDS, []), expected)
                self.assertLessEqual(smtp.sendmail.call_count, 1)
                smtp.close.assert_called_once()

    def test_configuration_closed_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(mail.Config.load())
            os.environ['CONTACT_ENABLED'] = 'true'
            self.assertIsNone(mail.Config.load())
            env = {'CONTACT_SMTP_HOST': CONFIG.host, 'CONTACT_SMTP_PORT': '465',
                   'CONTACT_SMTP_USERNAME': CONFIG.username, 'CONTACT_SMTP_PASSWORD': CONFIG.password,
                   'CONTACT_FROM_EMAIL': CONFIG.sender, 'CONTACT_TO_EMAIL': CONFIG.recipient,
                   'CONTACT_TURNSTILE_SECRET': CONFIG.turnstile_secret}
            os.environ.update(env)
            self.assertIsNotNone(mail.Config.load())
            for port in ('25', 'invalid', '0'):
                os.environ['CONTACT_SMTP_PORT'] = port
                self.assertIsNone(mail.Config.load())

    def test_turnstile_response_hostname_errors_and_bounds(self):
        for body, expected in [(b'{"success":true,"hostname":"example.test"}', 'verified'),
                               (b'{"success":true,"hostname":"attacker.test"}', 'verification_failed'),
                               (b'{"success":false}', 'verification_failed'),
                               (b'invalid', 'verification_unavailable'),
                               (b'x'*17000, 'verification_unavailable')]:
            with patch.object(security.requests, 'post') as post:
                response = post.return_value.__enter__.return_value
                response.status_code = 200
                response.iter_content.return_value = [body]
                self.assertEqual(security.verify_turnstile(CONFIG, 'synthetic'), expected)
                self.assertFalse(post.call_args.kwargs['allow_redirects'])
        with patch.object(security.requests, 'post', side_effect=requests.Timeout('secret')):
            self.assertEqual(security.verify_turnstile(CONFIG, 'synthetic'), 'verification_unavailable')

    def test_heic_and_signatures(self):
        def box(kind, body):
            return struct.pack('>I4s', len(body)+8, kind) + body
        heic = box(b'ftyp', b'heic\0\0\0\0mif1') + box(b'meta', b'\0'*4 + b''.join(box(kind, b'\0'*4) for kind in (b'iinf', b'iloc', b'pitm'))) + box(b'mdat', b'synthetic')
        self.assertEqual(security.attachment_type('a.heic', 'image/heic', heic), 'image/heic')
        for invalid in (b'', box(b'ftyp', b'mp42\0\0\0\0isom'), heic.replace(b'heic', b'mp42'), heic[:-1], box(b'ftyp', b'heic\0\0\0\0')):
            self.assertIsNone(security.attachment_type('a.heic', 'image/heic', invalid))
        self.assertIsNone(security.attachment_type('a.pdf', 'application/pdf', b'not a PDF'))

    def test_global_quota_and_upload_slots(self):
        now = [0]
        limits = security.Limits(lambda: now[0])
        for _ in range(30):
            self.assertEqual(limits.start_send(), 0)
            limits.finish_send()
        self.assertGreater(limits.start_send(), 0)
        now[0] = 3601
        self.assertEqual(limits.start_send(), 0)
        for index in range(4):
            self.assertEqual(limits.enter(str(index)), 0)
        self.assertGreater(limits.enter('fifth'), 0)


if __name__ == '__main__':
    unittest.main()
