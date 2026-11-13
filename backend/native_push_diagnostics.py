"""Temporary Dev-only, bounded, best-effort loopback diagnostic channel.

Never forward child stdout/stderr. Both ends validate the entire event schema.
One worker pass handles at most one registration challenge.
"""
import json
import logging
import os
import secrets
import socket

FLAG = 'NATIVE_PUSH_IOS_DEV_DIAGNOSTICS'
PORT = '_FCA_PUSH_DIAGNOSTIC_PORT'
KEY = '_FCA_PUSH_DIAGNOSTIC_KEY'
STAGES = {'credentials_preparation', 'token_decryption', 'eligibility_validation', 'fcm_request_response'}
RESULTS = {'configuration', 'expired', 'invalid_payload', 'unregistered', 'accepted',
           'rate_limited', 'provider_unavailable', 'transport_uncertain', 'identity_unavailable'}
FCM_CODES = {'UNREGISTERED', 'INVALID_ARGUMENT', 'SENDER_ID_MISMATCH',
             'QUOTA_EXCEEDED', 'UNAVAILABLE', 'INTERNAL', 'THIRD_PARTY_AUTH_ERROR', 'UNSPECIFIED_ERROR'}


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
        try:
            if enabled():
                self.key = secrets.token_hex(16)
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setblocking(False)
                self.socket.bind(('127.0.0.1', 0))
        except Exception:
            self.close()

    def environment(self):
        env = dict(os.environ)
        env.pop(PORT, None)
        env.pop(KEY, None)
        if self.socket is not None:
            try:
                port = self.socket.getsockname()[1]
                env[PORT] = str(port)
                env[KEY] = self.key
            except Exception:
                self.close()
        return env

    def report(self):
        try:
            if self.socket is None or not enabled():
                return
            # Bounded reads, no waiting, no raw datagram logging.
            for _ in range(4):
                packet, _ = self.socket.recvfrom(1025)
                if len(packet) > 1024:
                    continue
                try:
                    value = json.loads(packet)
                except (ValueError, UnicodeError, RecursionError):
                    continue
                if (type(value) is dict and set(value) == {'key', 'event'}
                        and value['key'] == self.key and valid(value['event'])):
                    logging.getLogger(__name__).warning('native_push_ios_challenge_diagnostic %s',
                                                        json.dumps(value['event'], sort_keys=True))
                    break
        except Exception:
            pass

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
