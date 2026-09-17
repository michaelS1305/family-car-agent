"""Web Push destinations, not a general-purpose URL fetcher.

Provider sources and deployment caveats are recorded in SECURITY_HARDENING.md.
"""
import re
from urllib.parse import urlsplit

PUSH_DEVICE_LIMIT = 5
PUSH_DISPATCH_LIMIT = 50


class PushSubscriptionLimitError(Exception):
    pass


def validate_push_endpoint(value):
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or not value.isascii():
            raise ValueError()
        if any(ord(char) <= 32 or ord(char) == 127 for char in value) or '\\' in value:
            raise ValueError()
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        labels = host.split('.')
        apple = len(labels) == 4 and labels[1:] == ['push', 'apple', 'com'] and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', labels[0]))
        supported = (
            apple
            or (host == 'fcm.googleapis.com' and parsed.path.startswith(('/wp/', '/fcm/send/')))
            or (host == 'updates.push.services.mozilla.com' and parsed.path.startswith(('/wpush/v1/', '/wpush/v2/')))
        )
        if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.query or parsed.fragment
                or not supported or not re.fullmatch(r'/[A-Za-z0-9_/:+-]+={0,2}', parsed.path)
                or parsed.path.endswith('/') or '//' in parsed.path):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError('Unsupported Push endpoint') from None
