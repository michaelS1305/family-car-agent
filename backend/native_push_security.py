"""Native-only configuration and domain-separated authenticated encryption."""
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ConfigurationError(Exception):
    def __init__(self):
        super().__init__('Native push configuration unavailable')


@dataclass(frozen=True)
class Config:
    project: str
    credentials_path: str = field(repr=False)
    key_id: str
    encryption_key: bytes = field(repr=False)
    fingerprint_key: bytes = field(repr=False)
    environment: str
    android_package: str

    @classmethod
    def load(cls):
        try:
            project = os.environ['NATIVE_PUSH_PROJECT']
            path = os.environ['NATIVE_PUSH_CREDENTIALS_FILE']
            key_id = os.environ['NATIVE_PUSH_KEY_ID']
            enc = base64.b64decode(os.environ['NATIVE_PUSH_ENCRYPTION_KEY'], validate=True)
            fp = base64.b64decode(os.environ['NATIVE_PUSH_FINGERPRINT_KEY'], validate=True)
            environment = os.environ['NATIVE_PUSH_ENVIRONMENT']
            package = os.environ['NATIVE_PUSH_ANDROID_PACKAGE']
            expected = {
                'dev': ('il.fca.companion.dev', 'https://jouhqvbxhsvkluwkqmdg.supabase.co'),
                'prod': ('il.fca.companion', 'https://xrgijytfigcuxmdktvmd.supabase.co'),
            }.get(environment)
            if (expected is None or package != expected[0]
                    or os.environ.get('SUPABASE_URL', '').rstrip('/') != expected[1]
                    or project != 'family-car-agent-dev'):
                raise ValueError()
            if (not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project)
                    or not os.path.isabs(path) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', key_id)
                    or len(enc) != 32 or len(fp) != 32 or hmac.compare_digest(enc, fp)):
                raise ValueError()
            return cls(project, path, key_id, enc, fp, environment, package)
        except (KeyError, ValueError, TypeError):
            raise ConfigurationError() from None

    def fingerprint(self, value):
        return hmac.digest(self.fingerprint_key, (self.project + '\0' + value).encode(), 'sha256')

    def seal(self, value, context):
        nonce = os.urandom(12)
        return nonce + AESGCM(self.encryption_key).encrypt(nonce, value.encode(), context.encode())

    def open(self, value, key_id, context):
        if key_id != self.key_id:
            raise ConfigurationError()
        try:
            return AESGCM(self.encryption_key).decrypt(bytes(value[:12]), bytes(value[12:]), context.encode()).decode()
        except Exception:
            raise ConfigurationError() from None


def nonce_hash(nonce):
    return hashlib.sha256(nonce.encode()).digest()


def token_context(user, installation):
    return f'fca-native-token:{user}:{installation}'


def nonce_context(user, challenge):
    return f'fca-native-challenge:{user}:{challenge}'
