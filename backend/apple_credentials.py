"""Best-effort capture, with committed attempt fencing before single-use exchange.

No automatic retry of an exchange: a crash/timeout can consume Apple's code.
No network operation runs inside a database transaction.
"""
import hashlib
import hmac
import logging
import threading
import time
from functools import lru_cache

import jwt
import requests
from deletion_gate import IdentityUnavailable, lock_identity, require_auth
from apple_credentials_security import Config, CaptureUnavailable


def _log_failure(category):
    # Only fixed categories and an operation label, never exception formatting.
    allowed = {'configuration_invalid', 'identity_mismatch', 'identity_unavailable',
               'apple_exchange_failed', 'token_validation_failed', 'persistence_failed',
               'encryption_failed', 'attempt_limited', 'attempt_superseded', 'attempt_unresolved'}
    if not isinstance(category, str) or category not in allowed:
        category = 'apple_exchange_failed'
    try:
        logging.getLogger(__name__).warning('operation=apple_credential_capture category=%s', category)
    except Exception:
        pass  # A broken logging handler must not affect capture or its API response.


class AppleKeys:
    def __init__(self):
        self.client = jwt.PyJWKClient('https://appleid.apple.com/auth/keys', timeout=5, cache_jwk_set=False)
        self.lock = threading.Lock()
        self.keys = ()
        self.until = self.retry = 0

    def __call__(self, token):
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or len(header['kid']) > 256:
            raise CaptureUnavailable()
        with self.lock:
            now = time.monotonic()
            key = next((k for k in self.keys if k.key_id == header['kid']), None)
            if key and now < self.until:
                return key.key
            if now >= self.retry:
                self.retry = now + 30
                keys = self.client.get_signing_keys(refresh=True)
                if not 1 <= len(keys) <= 64:
                    raise CaptureUnavailable()
                self.keys, self.until = tuple(keys), now + 300
                key = next((k for k in self.keys if k.key_id == header['kid']), None)
                if key:
                    return key.key
            raise CaptureUnavailable()


@lru_cache(maxsize=1)
def apple_keys():
    return AppleKeys()


def exchange(config, code, nonce, subject, *, resolver=None, http=None):
    now = int(time.time())
    secret = jwt.encode({'iss': config.team, 'iat': now, 'exp': now + 300,
                         'aud': 'https://appleid.apple.com', 'sub': config.client},
                        config.private_key, algorithm='ES256', headers={'kid': config.kid})
    with (http or requests.Session()) as session:
        session.trust_env = False
        with session.post('https://appleid.apple.com/auth/token', data={
                'client_id': config.client, 'client_secret': secret, 'code': code,
                'grant_type': 'authorization_code'}, timeout=(5, 10), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise CaptureUnavailable()
            raw = bytearray()
            for chunk in response.iter_content(4096):
                raw.extend(chunk)
                if len(raw) > 32768:
                    raise CaptureUnavailable()
            import json
            value = json.loads(raw)
    token, refresh = value.get('id_token'), value.get('refresh_token')
    if not isinstance(token, str) or len(token) > 16384 or not isinstance(refresh, str) or not 1 <= len(refresh) <= 8192:
        raise CaptureUnavailable('token_validation_failed')
    try:
        claims = jwt.decode(token, (resolver or apple_keys())(token), algorithms=['RS256'],
            issuer='https://appleid.apple.com', audience=config.client,
            options={'require': ['iss', 'aud', 'sub', 'exp', 'iat', 'nonce'], 'strict_aud': True})
    except Exception:
        raise CaptureUnavailable('token_validation_failed') from None
    # Our native flow always requests a SHA256 nonce. Missing nonce fails closed.
    expected = hashlib.sha256(nonce.encode()).hexdigest()
    if claims['sub'] != subject:
        raise CaptureUnavailable('identity_mismatch')
    if not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], expected):
        raise CaptureUnavailable('token_validation_failed')
    return refresh


def linked_subject(conn, owner):
    rows = conn.execute("""SELECT provider_id, identity_data->>'sub' FROM auth.identities
        WHERE user_id = %s AND provider = 'apple'""", (owner,)).fetchall()
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0] or rows[0][0] != rows[0][1]:
        raise CaptureUnavailable('identity_mismatch')
    return rows[0][0]


class Store:
    def __init__(self, pool):
        self.pool = pool

    def begin(self, owner, digest):
        with self.pool.connection() as conn, conn.transaction():
            lock_identity(conn, owner, exclusive=True)
            require_auth(conn, owner)
            subject = linked_subject(conn, owner)
            row = conn.execute('''SELECT status FROM apple_credential_attempts
                WHERE auth_user_id=%s AND code_digest=%s''', (owner, digest)).fetchone()
            if row:
                return None, subject, row[0]
            count = conn.execute('''SELECT count(*) FROM apple_credential_attempts
                WHERE auth_user_id=%s AND created_at > now() - interval '1 hour' ''', (owner,)).fetchone()[0]
            if count >= 5:
                raise CaptureUnavailable('attempt_limited')
            # A fresh attempt after a process crash may supersede an older pending one;
            # finish() checks the latest generation so late responses cannot overwrite it.
            generation = conn.execute('''INSERT INTO apple_credential_attempts(auth_user_id,code_digest)
                VALUES (%s,%s) RETURNING generation''', (owner, digest)).fetchone()[0]
            return generation, subject, 'pending'

    def finish(self, owner, generation, subject, config, ciphertext):
        with self.pool.connection() as conn, conn.transaction():
            lock_identity(conn, owner, exclusive=True)
            require_auth(conn, owner)
            if linked_subject(conn, owner) != subject:
                raise CaptureUnavailable('identity_mismatch')
            latest = conn.execute('''SELECT max(generation) FROM apple_credential_attempts
                WHERE auth_user_id=%s''', (owner,)).fetchone()[0]
            if latest != generation:
                raise CaptureUnavailable('attempt_superseded')
            conn.execute('''INSERT INTO apple_credentials(auth_user_id,environment,client_id,apple_subject,
                generation,key_id,refresh_ciphertext) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(auth_user_id) DO UPDATE SET environment=excluded.environment,
                client_id=excluded.client_id,apple_subject=excluded.apple_subject,generation=excluded.generation,
                key_id=excluded.key_id,refresh_ciphertext=excluded.refresh_ciphertext,updated_at=now()''',
                (owner, config.environment, config.client, subject, generation, config.active_key, ciphertext))
            conn.execute("UPDATE apple_credential_attempts SET status='stored' WHERE auth_user_id=%s AND generation=%s",
                         (owner, generation))


def capture(store, owner, code, nonce, *, config=None, exchanger=exchange):
    category = 'configuration_invalid'
    try:
        config = config or Config.load()
        category = 'persistence_failed'
        generation, subject, status = store.begin(owner, hashlib.sha256(code.encode()).digest())
        if generation is None:
            if status != 'stored':
                _log_failure('attempt_unresolved')
            return {'status': 'stored' if status == 'stored' else 'unavailable'}
        category = 'apple_exchange_failed'
        refresh = exchanger(config, code, nonce, subject)
        category = 'encryption_failed'
        ciphertext = config.seal(refresh, owner, subject, generation)
        category = 'persistence_failed'
        store.finish(owner, generation, subject, config, ciphertext)
        return {'status': 'stored'}
    except Exception as error:
        # Pending is intentionally durable even on failure: do not replay a consumed code.
        # Never overwrite an existing credential or expose provider/DB exception contents.
        if isinstance(error, IdentityUnavailable):
            category = 'identity_unavailable'
        elif isinstance(error, CaptureUnavailable) and error.category is not None:
            category = error.category
        _log_failure(category)
        return {'status': 'unavailable'}
