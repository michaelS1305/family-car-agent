"""Apple-only configuration and versioned encryption. Never log provider material."""
import base64
import json
import os
import re
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CaptureUnavailable(Exception):
    def __init__(self, category=None):
        super().__init__('APPLE_CAPTURE_UNAVAILABLE')
        self.category = category


@dataclass(frozen=True)
class Config:
    team: str
    kid: str
    client: str
    environment: str
    private_key: object = field(repr=False)
    active_key: str
    keys: dict = field(repr=False)

    @classmethod
    def load(cls):
        try:
            env = os.environ['APPLE_CREDENTIAL_ENVIRONMENT']
            client = os.environ['APPLE_NATIVE_CLIENT_ID']
            # Stage 1 is explicitly Development-only. No implicit production fallback.
            if (env != 'dev' or client != 'com.familycaragent.app.dev'
                    or os.environ.get('SUPABASE_URL', '').rstrip('/') !=
                    'https://jouhqvbxhsvkluwkqmdg.supabase.co'):
                raise ValueError()
            team, kid = os.environ['APPLE_TEAM_ID'], os.environ['APPLE_KEY_ID']
            if not all(re.fullmatch(r'[A-Z0-9]{10}', v) for v in (team, kid)):
                raise ValueError()
            private = serialization.load_pem_private_key(base64.b64decode(
                os.environ['APPLE_PRIVATE_KEY_BASE64'], validate=True), password=None)
            if not isinstance(private, ec.EllipticCurvePrivateKey) or not isinstance(private.curve, ec.SECP256R1):
                raise ValueError()
            raw = json.loads(os.environ['APPLE_CREDENTIAL_KEYS_JSON'])
            if not isinstance(raw, dict) or not 1 <= len(raw) <= 4:
                raise ValueError()
            keys = {k: base64.b64decode(v, validate=True) for k, v in raw.items()}
            if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', k) or len(v) != 32 for k, v in keys.items()):
                raise ValueError()
            active = os.environ['APPLE_CREDENTIAL_ACTIVE_KEY_ID']
            if active not in keys or len(set(keys.values())) != len(keys):
                raise ValueError()
            for name in ('NATIVE_PUSH_ENCRYPTION_KEY', 'NATIVE_PUSH_FINGERPRINT_KEY'):
                if os.environ.get(name) and base64.b64decode(os.environ[name], validate=True) in keys.values():
                    raise ValueError()
            return cls(team, kid, client, env, private, active, keys)
        except Exception:
            raise CaptureUnavailable() from None

    def context(self, owner, subject, version):
        return json.dumps(['fca-apple-refresh-v1', self.environment, owner, self.client, subject, version],
                          separators=(',', ':')).encode()

    def seal(self, token, owner, subject, version):
        nonce = os.urandom(12)
        return nonce + AESGCM(self.keys[self.active_key]).encrypt(
            nonce, token.encode(), self.context(owner, subject, version))

    def open(self, ciphertext, key_id, owner, subject, version):
        try:
            data = bytes(ciphertext)
            return AESGCM(self.keys[key_id]).decrypt(data[:12], data[12:],
                self.context(owner, subject, version)).decode()
        except Exception:
            raise CaptureUnavailable() from None
