"""Bounded, best-effort diagnostic channel; Production iOS registration only.

Never forward child stdout/stderr. Both ends validate the entire event schema.
One worker pass handles at most one registration challenge.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID
import json
import logging
import os
import re
import secrets
import socket

FLAG = 'NATIVE_PUSH_IOS_DEV_DIAGNOSTICS'
PORT = '_FCA_PUSH_DIAGNOSTIC_PORT'
KEY = '_FCA_PUSH_DIAGNOSTIC_KEY'
PASS = '_FCA_PUSH_DIAGNOSTIC_PASS'
STAGES = {'credentials_preparation', 'token_decryption', 'eligibility_validation', 'fcm_request_response'}
RESULTS = {'configuration', 'expired', 'invalid_payload', 'unregistered', 'accepted',
           'rate_limited', 'provider_unavailable', 'transport_uncertain', 'identity_unavailable'}
FCM_CODES = {'UNREGISTERED', 'INVALID_ARGUMENT', 'SENDER_ID_MISMATCH',
             'QUOTA_EXCEEDED', 'UNAVAILABLE', 'INTERNAL', 'THIRD_PARTY_AUTH_ERROR', 'UNSPECIFIED_ERROR'}


def production_enabled():
    return os.environ.get('NATIVE_PUSH_ENVIRONMENT') == 'prod'


def capture(config, platform):
    return platform == 'ios' and ((production_enabled() and config.environment == 'prod')
                                 or (enabled() and config.environment == 'dev'))


REASONS = {'selected', 'delivery_result', 'terminal_delivery_failure', 'registration_replacement',
           'explicit_revocation', 'capability_revocation', 'generation_mismatch',
           'verification_limit', 'token_conflict', 'verification_expired', 'verified'}
STATES = {'pending', 'cancelled', 'expired', 'consumed', 'unavailable'}
_pending = ContextVar('push_diagnostic_events', default=None)


def production_valid(event):
    if type(event) is not dict or set(event) != {'stage', 'result', 'http_status', 'fcm_code',
                                              'reason', 'state', 'challenge_ref', 'installation_ref'}:
        return False
    for field in ('challenge_ref', 'installation_ref'):
        value = event[field]
        if type(value) is not str or len(value) != 36:
            return False
        try:
            if str(UUID(value)) != value:
                return False
        except ValueError:
            return False
    return (type(event['stage']) is str
            and event['stage'] in STAGES | {'selection', 'transition', 'final_state'}
            and type(event['result']) is str and event['result'] in RESULTS | {'observed'}
            and type(event['reason']) is str and event['reason'] in REASONS
            and type(event['state']) is str and event['state'] in STATES
            and (event['http_status'] is None or type(event['http_status']) is int and 100 <= event['http_status'] <= 599)
            and (event['fcm_code'] is None or type(event['fcm_code']) is str and event['fcm_code'] in FCM_CODES))


def trace(config, platform, challenge_ref, installation_ref, *, reason, state,
          stage='transition', result='observed', http_status=None, fcm_code=None):
    try:
        if not production_enabled() or config.environment != 'prod' or platform != 'ios':
            return
        event = dict(stage=stage, result=result, reason=reason, state=state,
                     challenge_ref=str(challenge_ref), installation_ref=str(installation_ref),
                     http_status=http_status, fcm_code=fcm_code if fcm_code in FCM_CODES else None)
        if not production_valid(event):
            return
        pending = _pending.get()
        if pending is not None:
            if len(pending) < 32:
                pending.append(event)
        else:
            _publish(event)
    except Exception:
        pass


@contextmanager
def committed():
    # API transitions are emitted only after the caller's DB context commits.
    pending = []
    token = _pending.set(pending)
    try:
        yield
    except BaseException:
        raise
    else:
        for event in pending:
            _publish(event)
    finally:
        _pending.reset(token)


def transitions(cursor, config, platform, installation_ref, reason):
    try:
        for row in cursor.fetchall():
            trace(config, platform, row[0], installation_ref, reason=reason, state='cancelled')
    except Exception:
        pass


def _publish(event):
    try:
        if not production_valid(event):
            return
        if PORT not in os.environ:
            logging.getLogger(__name__).warning('native_push_ios_challenge_diagnostic %s',
                                               json.dumps(event, sort_keys=True))
            return
        packet = json.dumps({'key': os.environ[KEY], 'pass_id': os.environ.get(PASS), 'event': event}).encode()
        if len(packet) <= 1024:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
                channel.setblocking(False)
                channel.sendto(packet, ('127.0.0.1', int(os.environ[PORT])))
    except Exception:
        pass


def enabled():
    return (os.environ.get(FLAG) == 'true'
            and os.environ.get('NATIVE_PUSH_ENVIRONMENT') == 'dev'
            and os.environ.get('SUPABASE_URL', '').rstrip('/') == 'https://jouhqvbxhsvkluwkqmdg.supabase.co')


def valid(event):
    return (type(event) is dict and set(event) == {'stage', 'result', 'http_status', 'fcm_code', 'cancelled'}
            and type(event['stage']) is str and event['stage'] in STAGES
            and type(event['result']) is str and event['result'] in RESULTS
            and (event['http_status'] is None or type(event['http_status']) is int and 100 <= event['http_status'] <= 599)
            and (event['fcm_code'] is None or type(event['fcm_code']) is str and event['fcm_code'] in FCM_CODES)
            and type(event['cancelled']) is bool)


def emit(config, platform, event):
    try:
        if not enabled() or config.environment != 'dev' or platform != 'ios' or not valid(event):
            return
        packet = json.dumps({'key': os.environ[KEY], 'event': event}).encode()
        if len(packet) > 1024:
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
            channel.setblocking(False)
            channel.sendto(packet, ('127.0.0.1', int(os.environ[PORT])))
    except Exception:
        pass  # Diagnostics must never change delivery or transaction outcomes.


class Channel:
    def __init__(self):
        self.socket = None
        self.key = None
        self.pass_id = secrets.token_hex(16)
        self.initialization = 'disabled'
        self.valid_messages = 0
        self.transport = 'ok'
        try:
            if enabled() or production_enabled():
                self.key = secrets.token_hex(16)
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setblocking(False)
                self.socket.bind(('127.0.0.1', 0))
                self.initialization = 'ready'
        except Exception:
            self.initialization = 'failed'
            self.close()

    def environment(self):
        env = dict(os.environ)
        env.pop(PORT, None)
        env.pop(KEY, None)
        env.pop(PASS, None)
        if self.socket is not None:
            try:
                port = self.socket.getsockname()[1]
                env[PORT] = str(port)
                env[KEY] = self.key
                if production_enabled():
                    env[PASS] = self.pass_id
            except Exception:
                self.initialization = 'failed'
                self.close()
        return env

    def report(self):
        try:
            if self.socket is None or not (enabled() or production_enabled()):
                return
            # Bounded reads, no waiting, no raw datagram logging.
            for _ in range(4):
                try:
                    packet, _ = self.socket.recvfrom(1025)
                except BlockingIOError:
                    break
                if len(packet) > 1024:
                    continue
                try:
                    value = json.loads(packet)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                if (type(value) is dict and set(value) == ({'key', 'pass_id', 'event'} if production_enabled() else {'key', 'event'})
                        and (not production_enabled() or value['pass_id'] == self.pass_id)
                        and value['key'] == self.key
                        and (production_valid(value['event']) if production_enabled() else valid(value['event']))):
                    self.valid_messages = getattr(self, 'valid_messages', 0) + 1
                    event = dict(value['event'])
                    if production_enabled():
                        event['pass_id'] = self.pass_id
                    logging.getLogger(__name__).warning('native_push_ios_challenge_diagnostic %s',
                                                        json.dumps(event, sort_keys=True))
                    if not production_enabled():
                        break
        except Exception:
            self.transport = 'failed'

    def summary(self, termination):
        # Parent-owned, closed schema. Never serialize exceptions or child output.
        try:
            if not production_enabled():
                return
            if (termination not in {'completed', 'shutdown', 'deadline', 'child_failed'}
                    or not re.fullmatch(r'[0-9a-f]{32}', self.pass_id)
                    or self.initialization not in {'ready', 'failed', 'disabled'}
                    or self.transport not in {'ok', 'failed'}
                    or type(self.valid_messages) is not int or not 0 <= self.valid_messages <= 4):
                return
            abnormal = termination != 'completed' or self.initialization != 'ready' or self.transport != 'ok'
            # Idle healthy passes remain quiet. One bounded summary per interesting pass.
            if abnormal or self.valid_messages:
                event = dict(pass_id=self.pass_id, initialization=self.initialization,
                             valid_messages=self.valid_messages, termination=termination,
                             transport=self.transport, missing_diagnostics=abnormal and self.valid_messages == 0)
                logging.getLogger(__name__).warning('native_push_pass_diagnostic %s', json.dumps(event, sort_keys=True))
        except Exception:
            pass

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
