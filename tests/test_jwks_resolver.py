import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import jwt
from jwks_resolver import BoundedJWKSResolver, JWKSUnavailable


def token(kid):
    # Only unverified headers are read here; signature verification stays in auth_service.
    import base64
    import json
    head = base64.urlsafe_b64encode(json.dumps({'alg': 'ES256', 'kid': kid}).encode()).rstrip(b'=')
    return head.decode() + '.e30.eA'


class JWKSResolverTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.client = Mock()
        self.client.get_signing_keys.return_value = [SimpleNamespace(key_id='current', key='key')]
        self.resolve = BoundedJWKSResolver('https://unused.test', client=self.client, clock=lambda: self.now)

    def test_cached_key_and_unknown_flood_share_refresh(self):
        self.assertEqual(self.resolve(token('current')), 'key')
        def invalid(index):
            with self.assertRaises(jwt.InvalidTokenError):
                self.resolve(token(str(index)))
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(invalid, range(100)))
        self.assertEqual(self.resolve(token('current')), 'key')
        self.client.get_signing_keys.assert_called_once()

    def test_rotation_after_refresh_cooldown(self):
        self.resolve(token('current'))
        self.client.get_signing_keys.return_value = [SimpleNamespace(key_id='new', key='new-key')]
        self.now += 31
        self.assertEqual(self.resolve(token('new')), 'new-key')

    def test_outage_is_bounded_and_private(self):
        self.client.get_signing_keys.side_effect = OSError('private provider details')
        for _ in range(10):
            with self.assertRaisesRegex(JWKSUnavailable, '^Signing keys unavailable$'):
                self.resolve(token('unknown'))
        self.client.get_signing_keys.assert_called_once()

    def test_bad_headers_do_not_fetch(self):
        for value in ('garbage', token([]), token('x' * 257)):
            with self.assertRaises(jwt.InvalidTokenError):
                self.resolve(value)
        self.client.get_signing_keys.assert_not_called()

    def test_real_signature_is_still_required_and_expired_cache_fails_closed(self):
        import time
        from uuid import uuid4
        from cryptography.hazmat.primitives.asymmetric import ec
        from auth_service import SupabaseJWTVerifier, SupabaseJWTSettings
        private = ec.generate_private_key(ec.SECP256R1())
        self.client.get_signing_keys.return_value = [SimpleNamespace(key_id='current', key=private.public_key())]
        verifier = SupabaseJWTVerifier(SupabaseJWTSettings('https://issuer.test', 'https://unused.test'), self.resolve)
        subject = str(uuid4())
        claims = {'iss': 'https://issuer.test', 'aud': 'authenticated', 'sub': subject, 'role': 'authenticated', 'exp': time.time() + 600}
        valid = jwt.encode(claims, private, algorithm='ES256', headers={'kid': 'current'})
        self.assertEqual(verifier.verify(valid), subject)
        forged = jwt.encode(claims, ec.generate_private_key(ec.SECP256R1()), algorithm='ES256', headers={'kid': 'current'})
        with self.assertRaises(jwt.InvalidTokenError):
            verifier.verify(forged)
        self.now += 301
        self.client.get_signing_keys.side_effect = OSError('secret detail')
        with self.assertRaises(JWKSUnavailable):
            verifier.verify(valid)
