import unittest
from unittest.mock import patch, Mock
import requests
from push_security import validate_push_endpoint
from tests.test_push_service import load_push_service


class PushDestinationTests(unittest.TestCase):
    def test_supported_endpoints(self):
        for url in ('https://web.push.apple.com/QABC_123', 'https://fcm.googleapis.com/wp/abc:APA91'):
            self.assertEqual(validate_push_endpoint(url), url)
        for url in ('https://fcm.googleapis.com/wp/abc', 'https://fcm.googleapis.com/fcm/send/abc', 'https://updates.push.services.mozilla.com/wpush/v2/abc'):
            self.assertEqual(validate_push_endpoint(url), url)

    def test_bad_destinations(self):
        for url in ('http://web.push.apple.com/a', 'https://127.0.0.1/a', 'https://10.0.0.1/a',
                    'https://localhost/a', 'https://web.push.apple.com.attacker.test/a',
                    'https://user@web.push.apple.com/a', 'https://web.push.apple.com:444/a',
                    'https://attacker.test/a', 'https://web.push.apple.com./a',
                    'https://web.push.apple.com/a?x=1', 'https://web.push.apple.com/a#x',
                    'https://web.push.apple.com/../a'):
            with self.subTest(url=url), self.assertRaises(ValueError): validate_push_endpoint(url)

    def test_transport_disables_redirect_and_environment_proxy(self):
        service, _ = load_push_service()
        with service.PushTransport() as transport, patch.object(requests.Session, 'request', return_value=Mock(status_code=307)) as send:
            self.assertFalse(transport.trust_env)
            transport.post('https://web.push.apple.com/a', allow_redirects=True)
            self.assertFalse(send.call_args.kwargs['allow_redirects'])
            with self.assertRaises(ValueError): transport.post('https://attacker.test/a')
            self.assertEqual(send.call_count, 1)

    def test_legacy_invalid_endpoint_never_reaches_transport(self):
        service, _ = load_push_service()
        with patch.object(service, 'PushTransport') as transport:
            with self.assertRaises(ValueError):
                service._webpush({'endpoint': 'https://attacker.test/a'}, {}, {})
            transport.assert_not_called()
