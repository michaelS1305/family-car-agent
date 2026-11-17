"""Public contact endpoint. No account, database, background job or automatic retry."""
import asyncio
import logging
import tempfile
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from contact_mail import Config, deliver, valid_email
from contact_diagnostics import request_id as diagnostic_id, report
from contact_security import (BODY_LIMIT, FILE_LIMIT, TOTAL_LIMIT, Limits,
                              attachment_type, safe_filename, verify_turnstile)

router = APIRouter()
limits = Limits()
logger = logging.getLogger('contact')
FIELDS = {'name', 'email', 'subject', 'description', 'turnstile_token'}


class ContactParser(MultiPartParser):
    """Track incomplete file parts too: FormData only owns completed parts."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.opened_files = []
        self.complete = False

    def on_headers_finished(self):
        super().on_headers_finished()
        if self._current_part.file is not None:
            self.opened_files.append(self._current_part.file.file)

    def on_end(self):
        super().on_end()
        self.complete = True


@asynccontextmanager
async def contact_form(request):
    parser = ContactParser(request.headers, request.stream(), max_files=5,
                           max_fields=5, max_part_size=8192)
    try:
        form = await parser.parse()
        if not parser.complete:
            raise MultiPartException('Incomplete multipart')
        yield form
    finally:
        # Synchronous file close also works while task cancellation is pending.
        for file in parser.opened_files:
            file.close()


def reply(request_id, code, status, retry=0):
    logger.info('contact request_id=%s category=%s', request_id, code)
    return JSONResponse({'code': code, 'request_id': request_id}, status_code=status,
                        headers={'Retry-After': str(retry)} if retry else {})


def send_limited(config, fields, attachments):
    retry = limits.start_send()
    if retry:
        return 'rate_limited', retry
    try:
        return deliver(config, fields, attachments), 0
    finally:
        limits.finish_send()


@router.post('/api/contact')
async def submit(request: Request):
    request_id = uuid4().hex
    token = diagnostic_id.set(request_id)
    try:
        return await _submit(request, request_id)
    finally:
        diagnostic_id.reset(token)


async def _submit(request, request_id):
    config = Config.load()
    if config is None:
        report('configuration', 'configuration_invalid')
        return reply(request_id, 'service_unavailable', 503)
    # Only ASGI's peer address; forwarded-header trust belongs to the server's
    # explicit trusted-proxy configuration, never to arbitrary request headers.
    ip = request.client.host if request.client else 'unknown'
    retry = limits.enter(ip)
    if retry:
        return reply(request_id, 'rate_limited', 429, retry)
    try:
        if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'multipart/form-data':
            return reply(request_id, 'invalid_request', 422)
        # Bound and spool before invoking the framework multipart parser. Never
        # trust Content-Length; this also handles chunked uploads and false lengths.
        with tempfile.SpooledTemporaryFile(max_size=262144, mode='w+b') as body:
            total = 0
            async with asyncio.timeout(30):
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > BODY_LIMIT:
                        return reply(request_id, 'request_too_large', 413)
                    body.write(chunk)
            body.seek(0)

            async def receive():
                chunk = body.read(65536)
                return {'type': 'http.request', 'body': chunk, 'more_body': bool(chunk)}

            bounded = Request(request.scope, receive)
            async with contact_form(bounded) as form:
                fields = {}
                uploads = []
                for key, value in form.multi_items():
                    if key == 'attachments' and isinstance(value, UploadFile):
                        uploads.append(value)
                    elif key in FIELDS and isinstance(value, str) and key not in fields:
                        fields[key] = value
                    else:
                        return reply(request_id, 'invalid_fields', 422)
                if set(fields) != FIELDS:
                    return reply(request_id, 'invalid_fields', 422)
                # Reject header controls BEFORE trimming, rather than concealing them.
                if any(any(ord(c) < 32 or ord(c) == 127 for c in fields[key])
                       for key in ('name', 'email', 'subject', 'turnstile_token')):
                    return reply(request_id, 'invalid_fields', 422)
                fields = {key: value.strip() for key, value in fields.items()}
                if (not 1 <= len(fields['name']) <= 100 or not valid_email(fields['email'])
                        or fields['subject'] not in ('תקלה', 'הצעה', 'חוות דעת')
                        or not 1 <= len(fields['description']) <= 1000
                        or not 1 <= len(fields['turnstile_token']) <= 2048):
                    return reply(request_id, 'invalid_fields', 422)
                if any((item.size or 0) > FILE_LIMIT for item in uploads):
                    return reply(request_id, 'attachment_too_large', 413)
                if sum(item.size or 0 for item in uploads) > TOTAL_LIMIT:
                    return reply(request_id, 'attachments_too_large', 413)
                verified = await run_in_threadpool(verify_turnstile, config, fields.pop('turnstile_token'))
                if verified != 'verified':
                    return reply(request_id, verified, 422 if verified == 'verification_failed' else 503)
                attachments = []
                total = 0
                for upload in uploads:
                    content = await upload.read(FILE_LIMIT + 1)
                    total += len(content)
                    if len(content) > FILE_LIMIT or total > TOTAL_LIMIT:
                        return reply(request_id, 'attachment_too_large', 413)
                    filename = upload.filename or ''
                    mime = attachment_type(filename, upload.content_type, content)
                    if mime is None:
                        return reply(request_id, 'unsupported_attachment', 415)
                    attachments.append((safe_filename(filename), mime, content))
                code, retry = await run_in_threadpool(send_limited, config, fields, attachments)
                status = {'accepted': 200, 'rate_limited': 429, 'message_too_large': 413}.get(code, 503)
                return reply(request_id, code, status, retry)
    except (HTTPException, MultiPartException, ValueError):
        return reply(request_id, 'invalid_request', 422)
    except (TimeoutError, ClientDisconnect):
        report('request', 'request_incomplete')
        return reply(request_id, 'request_incomplete', 503)
    except Exception:
        report('request', 'unexpected_failure')
        # Never expose parser/provider exceptions or submitted data.
        return reply(request_id, 'service_unavailable', 503)
    finally:
        limits.leave()
