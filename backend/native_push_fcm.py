"""FCM HTTP v1; injected transport/credential loader make tests offline.

No implicit retry of an ambiguous send. Acceptance means provider acceptance,
never proof of phone delivery. No provider response/exception text is logged.
"""
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import json
import threading
import time

import jwt
import requests

from native_push_security import ConfigurationError

TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'


@dataclass(frozen=True)
class Result:
    code: str
    retry_after: int = 0


def _retry_after(response, now):
    value = response.headers.get('Retry-After', '')
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        try:
            seconds = int(parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, AttributeError, OverflowError):
            seconds = 0
    return max(0, min(seconds, 86400))


def _load(path):
    with open(path, encoding='utf-8') as source:
        return json.load(source)


class Fcm:
    def __init__(self, config, *, transport=None, loader=_load, clock=time.time):
        self.config, self.loader, self.clock = config, loader, clock
        self.http = transport or requests.Session()
        if transport is None:
            self.http.trust_env = False
        self._lock = threading.Lock()
        self._token, self._until = None, 0

    def _access_token(self):
        with self._lock:
            now = self.clock()
            if self._token and now < self._until:
                return self._token
            try:
                credential = self.loader(self.config.credentials_path)
                if (credential.get('type') != 'service_account'
                        or credential.get('project_id') != self.config.project
                        or credential.get('token_uri') != TOKEN_URL
                        or not credential.get('client_email', '').endswith('.iam.gserviceaccount.com')):
                    raise ConfigurationError()
                assertion = jwt.encode({'iss': credential['client_email'], 'scope': SCOPE,
                    'aud': TOKEN_URL, 'iat': int(now), 'exp': int(now) + 3600},
                    credential['private_key'], algorithm='RS256')
                response = self.http.post(TOKEN_URL, data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion},
                    timeout=(3, 5), allow_redirects=False)
                body = response.json()
                if response.status_code != 200 or not isinstance(body.get('access_token'), str):
                    raise ConfigurationError()
                lifetime = min(int(body['expires_in']), 3600)
                if lifetime <= 60:
                    raise ConfigurationError()
                self._token, self._until = body['access_token'], now + lifetime - 60
                return self._token
            except Exception:
                raise ConfigurationError() from None

    def send(self, token, data, *, expires_at, platform):
        # Never let an untrusted platform select an unrestricted send path.
        if platform != 'android':
            return Result('configuration')
        try:
            access = self._access_token()
            remaining = int(expires_at.timestamp() - self.clock())
            if remaining <= 0:
                return Result('expired')
            message = {'token': token, 'data': data,
                'android': {'ttl': f'{remaining}s', 'priority': 'high',
                            'restricted_package_name': self.config.android_package}}
            response = self.http.post(
                f'https://fcm.googleapis.com/v1/projects/{self.config.project}/messages:send',
                json={'message': message}, headers={'Authorization': 'Bearer ' + access},
                timeout=(3, 5), allow_redirects=False)
            if response.status_code == 200:
                return Result('accepted')
            try:
                details = response.json().get('error', {}).get('details', [])
                codes = {item.get('errorCode') for item in details if isinstance(item, dict)
                         and item.get('@type') == 'type.googleapis.com/google.firebase.fcm.v1.FcmError'}
            except (ValueError, AttributeError, TypeError):
                codes = set()
            if 'UNREGISTERED' in codes:
                return Result('unregistered')
            if response.status_code in (401, 403):
                self._until = 0
                return Result('configuration')
            if response.status_code == 429:
                return Result('rate_limited', _retry_after(response, self.clock()))
            if response.status_code in (500, 503):
                return Result('provider_unavailable', _retry_after(response, self.clock()))
            return Result('invalid_payload')
        except ConfigurationError:
            return Result('configuration')
        except requests.RequestException:
            return Result('transport_uncertain')

    def prepare(self):
        """Refresh OAuth before the worker's last short authorization read."""
        self._access_token()

    def close(self):
        self.http.close()
