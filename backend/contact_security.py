"""Bounded, process-local protections for anonymous contact submissions only."""
from collections import deque
import re
import struct
import threading
import time
import requests
from urllib3.exceptions import ReadTimeoutError
from contact_diagnostics import CLOUDFLARE_CODES, report

FILE_LIMIT = 5_000_000
TOTAL_LIMIT = 10_000_000
BODY_LIMIT = 10_100_000


class Limits:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.clients = {}
        self.sends = deque()
        self.uploads = 0
        self.smtp = 0

    def enter(self, ip):
        with self.lock:
            now = self.clock()
            self.clients = {key: values for key, values in self.clients.items() if values[-1] > now - 600}
            history = self.clients.get(ip, deque())
            while history and history[0] <= now - 600:
                history.popleft()
            if len(history) >= 5:
                return max(1, int(601 - (now - history[0])))
            if self.uploads >= 4 or (ip not in self.clients and len(self.clients) >= 4096):
                return 60
            history.append(now)
            self.clients[ip] = history
            self.uploads += 1
            return 0

    def leave(self):
        with self.lock:
            self.uploads -= 1

    def start_send(self):
        with self.lock:
            now = self.clock()
            while self.sends and self.sends[0] <= now - 3600:
                self.sends.popleft()
            if self.smtp >= 2:
                return 30
            if len(self.sends) >= 30:
                return max(1, int(3601 - (now - self.sends[0])))
            self.smtp += 1
            self.sends.append(now)
            return 0

    def finish_send(self):
        with self.lock:
            self.smtp -= 1


def _http_error_codes(response):
    """Best-effort diagnostics only; never change the non-200 failure result."""
    try:
        body = bytearray()
        for chunk in response.iter_content(4096):
            if len(body) + len(chunk) > 16384:
                return ()
            body.extend(chunk)
        import json
        result = json.loads(body)
        codes = result.get('error-codes') if isinstance(result, dict) else None
        if isinstance(codes, list):
            return tuple(sorted({code for code in codes
                                 if isinstance(code, str) and code in CLOUDFLARE_CODES}))
    except Exception:
        pass  # No response bodies or raw exceptions may escape diagnostic parsing.
    return ()


def verify_turnstile(config, token):
    try:
        # No redirects, retries, response-body logging or client-provided endpoint.
        with requests.post('https://challenges.cloudflare.com/turnstile/v0/siteverify',
                           data={'secret': config.turnstile_secret, 'response': token},
                           timeout=(3, 5), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                for code in _http_error_codes(response) or (None,):
                    report('turnstile', 'turnstile_http_non_200',
                           http_status=response.status_code, cloudflare_code=code)
                return 'verification_unavailable'
            body = bytearray()
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                if len(body) > 16384:
                    report('turnstile', 'turnstile_response_too_large')
                    return 'verification_unavailable'
            import json
            result = json.loads(body)
            if not isinstance(result, dict) or result.get('success') is not True:
                report('turnstile', 'turnstile_rejected')
                return 'verification_failed'
            if config.hostname and result.get('hostname') != config.hostname:
                report('turnstile', 'turnstile_rejected')
                return 'verification_failed'
            return 'verified'
    except (requests.RequestException, ValueError) as error:
        if isinstance(error, requests.exceptions.SSLError):
            code = 'turnstile_tls_failed'
        elif isinstance(error, requests.exceptions.ConnectTimeout):
            code = 'turnstile_connect_timeout'
        elif isinstance(error, requests.exceptions.ReadTimeout) or (
            isinstance(error, requests.exceptions.ConnectionError)
            and error.args and isinstance(error.args[0], ReadTimeoutError)
        ):
            # requests wraps streamed urllib3 read timeouts as ConnectionError.
            code = 'turnstile_read_timeout'
        elif isinstance(error, ValueError):
            code = 'turnstile_invalid_json'
        else:
            code = 'turnstile_connection_failed'
        report('turnstile', code)
        return 'verification_unavailable'


def heic_structure(data):
    # ISO BMFF alone is insufficient: require HEVC still-image brands, a meta
    # box containing item information/location, and actual media data.
    boxes = {}
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            return False
        size, kind = struct.unpack_from('>I4s', data, offset)
        if size < 8 or offset + size > len(data) or kind in boxes:
            return False
        boxes[kind] = data[offset + 8:offset + size]
        offset += size
    brand = boxes.get(b'ftyp', b'')
    if len(brand) < 8 or len(brand) % 4:
        return False
    brands = [brand[:4]] + [brand[i:i + 4] for i in range(8, len(brand), 4)]
    if not any(item in (b'heic', b'heix') for item in brands):
        return False
    meta = boxes.get(b'meta', b'')
    children = set()
    offset = 4  # FullBox version/flags
    while offset < len(meta):
        if offset + 8 > len(meta):
            return False
        size, kind = struct.unpack_from('>I4s', meta, offset)
        if size <= 8 or offset + size > len(meta):
            return False
        children.add(kind)
        offset += size
    return {b'iinf', b'iloc', b'pitm'} <= children and bool(boxes.get(b'mdat'))


def attachment_type(filename, declared, data):
    extension = filename.rsplit('.', 1)[-1].lower()
    types = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
             'webp': 'image/webp', 'heic': 'image/heic', 'pdf': 'application/pdf'}
    mime = types.get(extension)
    if not mime or declared != mime or not data:
        return None
    valid = {
        'image/png': lambda: (len(data) >= 45 and data[:8] == b'\x89PNG\r\n\x1a\n'
                              and data[8:16] == b'\x00\x00\x00\rIHDR' and data[-12:-4] == b'\x00\x00\x00\x00IEND'),
        'image/jpeg': lambda: data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'),
        'image/webp': lambda: (len(data) >= 20 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'
                               and data[12:16] in (b'VP8 ', b'VP8L', b'VP8X')
                               and int.from_bytes(data[4:8], 'little') + 8 == len(data)),
        'application/pdf': lambda: data.startswith((b'%PDF-1.', b'%PDF-2.')) and data.rstrip().endswith(b'%%EOF'),
        'image/heic': lambda: heic_structure(data),
    }[mime]()
    return mime if valid else None


def safe_filename(value):
    basename = value.replace('\\', '/').rsplit('/', 1)[-1]
    return re.sub(r'[^\w. -]', '_', basename, flags=re.UNICODE)[-120:] or 'attachment'
