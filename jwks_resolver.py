"""Bounded, thread-safe JWKS refresh per configured source/process."""
import threading
import time

import jwt
from jwt import InvalidTokenError, PyJWKClient


class JWKSUnavailable(RuntimeError):
    pass


class BoundedJWKSResolver:
    def __init__(self, url, *, client=None, clock=time.monotonic):
        self.client = client or PyJWKClient(url, timeout=5, cache_jwk_set=False)
        self.clock = clock
        self.lock = threading.Lock()
        self.keys = ()
        self.valid_until = 0.0
        self.refresh_after = 0.0
        self.failed = False

    def __call__(self, token):
        if not isinstance(token, str) or len(token) > 16384:
            raise InvalidTokenError('Invalid token')
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        if header.get('alg') != 'ES256' or type(kid) is not str or not 1 <= len(kid) <= 256:
            raise InvalidTokenError('Invalid token header')
        with self.lock:
            now = self.clock()
            key = next((key for key in self.keys if key.key_id == kid), None)
            if key is not None and now < self.valid_until:
                return key.key
            if now >= self.refresh_after:
                try:
                    keys = self.client.get_signing_keys(refresh=True)
                    if not 1 <= len(keys) <= 64:
                        raise ValueError('Invalid key set')
                    self.keys = tuple(keys)
                    self.valid_until = self.clock() + 300
                    self.failed = False
                except Exception:
                    self.failed = True
                    raise JWKSUnavailable('Signing keys unavailable') from None
                finally:
                    self.refresh_after = self.clock() + 30
                key = next((key for key in self.keys if key.key_id == kid), None)
                if key is not None:
                    return key.key
            if self.failed or self.clock() >= self.valid_until:
                raise JWKSUnavailable('Signing keys unavailable')
            raise InvalidTokenError('Unknown signing key')
