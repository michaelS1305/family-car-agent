"""Fixed operational categories; enabled only by the local contact entry point."""
from contextvars import ContextVar
import logging
import re
import sys

request_id = ContextVar('contact_request_id', default='')
CLOUDFLARE_CODES = frozenset({
    'missing-input-secret', 'invalid-input-secret', 'missing-input-response',
    'invalid-input-response', 'bad-request', 'timeout-or-duplicate', 'internal-error',
})
EVENTS = {
    ('configuration', 'configuration_invalid'),
    ('turnstile', 'turnstile_tls_failed'),
    ('turnstile', 'turnstile_connect_timeout'),
    ('turnstile', 'turnstile_read_timeout'),
    ('turnstile', 'turnstile_connection_failed'),
    ('turnstile', 'turnstile_http_non_200'),
    ('turnstile', 'turnstile_response_too_large'),
    ('turnstile', 'turnstile_invalid_json'),
    ('turnstile', 'turnstile_rejected'),
    ('smtp_connect', 'smtp_connect_failed'),
    ('smtp_auth', 'smtp_auth_failed'),
    ('smtp_send', 'smtp_rejected'),
    ('smtp_send', 'delivery_uncertain'),
    ('request', 'unexpected_failure'),
    ('request', 'request_incomplete'),
}
logger = logging.getLogger('contact.local_diagnostics')
logger.propagate = False
logger.addHandler(logging.NullHandler())


def safe_line(record):
    identifier = getattr(record, 'contact_id', '')
    stage = getattr(record, 'contact_stage', '')
    code = getattr(record, 'contact_code', '')
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
        return None
    if not isinstance(stage, str) or not isinstance(code, str) or (stage, code) not in EVENTS:
        return None
    status = getattr(record, 'contact_http_status', None)
    provider_code = getattr(record, 'contact_cloudflare_code', None)
    suffix = ''
    if code == 'turnstile_http_non_200':
        if type(status) is not int or not 100 <= status <= 599 or status == 200:
            return None
        suffix = f' http_status={status}'
        if provider_code is not None:
            if not isinstance(provider_code, str) or provider_code not in CLOUDFLARE_CODES:
                return None
            suffix += f' cloudflare_code={provider_code}'
    elif status is not None:
        return None
    elif provider_code is not None:
        return None
    return f'CONTACT_DIAG request_id={identifier} stage={stage} code={code}' + suffix


class SafeHandler(logging.Handler):
    def emit(self, record):
        try:
            line = safe_line(record)
            if line:
                sys.stdout.write(line + '\n')
                sys.stdout.flush()
        except Exception:
            pass  # Diagnostics must never affect delivery; never print raw exceptions.


def enable_local():
    logger.handlers = [SafeHandler()]
    logger.setLevel(logging.INFO)


def report(stage, code, *, http_status=None, cloudflare_code=None):
    try:
        if (stage, code) in EVENTS:
            logger.info('', extra={'contact_id': request_id.get(),
                                  'contact_stage': stage, 'contact_code': code,
                                  'contact_http_status': http_status,
                                  'contact_cloudflare_code': cloudflare_code})
    except Exception:
        pass
