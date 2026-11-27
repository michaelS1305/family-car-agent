"""Self-only deletion endpoints and a restart-safe, bounded recovery loop."""
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, Response, Request
from fastapi.responses import JSONResponse
import deletion_receipts as receipts
import json
from pydantic import BaseModel, ConfigDict

import account_deletion as deletion
from auth_service import get_deletion_identity
from database import pool
from identity import AuthenticatedSupabaseUser


class DeletionProtocolMiddleware:
    """Cover routing, dependency, validation and unexpected errors, without logging inputs."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (path == '/api/account/deletion' or path.startswith('/api/account/deletion/')):
            return await self.app(scope, receive, send)
        started = False
        async def private_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = [(k,v) for k,v in message.get('headers',[]) if k.lower() != b'cache-control'] + [(b'cache-control',b'no-store')]
                started = True
            await send(message)
        try:
            await self.app(scope, receive, private_send)
        except Exception:
            # No raw exceptions, request bodies or credential-bearing traceback locals.
            if started:
                raise
            await private_error(500)(scope, receive, private_send)


router = APIRouter(prefix='/api/account/deletion')
APPLE_HELP_LINK = '</api/account/deletion/apple-instructions>; rel="help"'


@router.get('/apple-instructions')
def apple_instructions():
    # Generic public help only: no job lookup, account data or mutation. Remains
    # available after Auth deletion without a JWT or a bearer receipt secret.
    return {
        'instructions': 'אם נדרש ביטול ידני, פתחו את הגדרות חשבון Apple, בחרו התחברות באמצעות Apple ובטלו את הגישה של FCA. הוראות אלו אינן אישור למצב המחיקה או לביטול ההרשאה.',
        'url': 'https://support.apple.com/102571',
    }


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmation: Literal['DELETE_MY_ACCOUNT']


@router.get('/preview')
def preview(response: Response, identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    response.headers['Link'] = APPLE_HELP_LINK
    return deletion.preview(pool, identity.auth_user_id)


@router.get('')
def status(response: Response, identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    response.headers['Link'] = APPLE_HELP_LINK
    return deletion.status(pool, identity.auth_user_id)


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def private_error(status=401):
    return JSONResponse({'detail': 'DELETION_STATUS_UNAVAILABLE'}, status_code=status,
                        headers={'Cache-Control': 'no-store'})


@router.get('/capabilities')
def capabilities():
    if not receipts.enabled():
        return private_error(503)
    return JSONResponse({'protocol': 'deletion-status-v1', 'retention_days': 180},
                        headers={'Cache-Control': 'no-store'})


@router.post('/status')
def receipt_status(request: Request):
    if not receipts.limiter.allow():
        return private_error(429)
    value = request.headers.get('authorization', '')
    if len(value) > 128 or not value.startswith('DeletionStatus '):
        return private_error()
    parts = value.removeprefix('DeletionStatus ').split('.')
    if len(parts) != 2:
        return private_error()
    try:
        return JSONResponse(receipts.lookup(pool, *parts), headers={'Cache-Control': 'no-store'})
    except receipts.Rejected:
        return private_error()


@router.post('/request', status_code=202)
@router.post('', status_code=202)
async def confirm(request: Request, identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    # Bounded validation deliberately never echoes credentials in FastAPI errors.
    raw = bytearray()
    async for part in request.stream():
        if len(raw)+len(part)>1024:
            return private_error(422)
        raw.extend(part)
    try:
        body = json.loads(raw, object_pairs_hook=unique_fields)
        if not isinstance(body, dict) or set(body)-{'confirmation','status_credential'} or body.get('confirmation')!='DELETE_MY_ACCOUNT':
            return private_error(422)
        if request.url.path.endswith('/request') and 'status_credential' not in body:
            return private_error(422)
        if 'status_credential' in body:
            value=body['status_credential']
            if not isinstance(value,dict) or set(value)!={'operation_id','secret'}:
                return private_error(422)
            result=await asyncio.to_thread(receipts.initiate,pool,identity.auth_user_id,value['operation_id'],value['secret'])
        else:
            result=await asyncio.to_thread(deletion.confirm,pool,identity.auth_user_id)
        return JSONResponse(result,status_code=202,headers={'Link':APPLE_HELP_LINK,'Cache-Control':'no-store'})
    except (ValueError, TypeError, receipts.Rejected):
        return private_error(422)
    except receipts.Unavailable:
        return private_error(503)


async def _recover(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(deletion.run_due, pool, stop.is_set)
            await asyncio.to_thread(receipts.expire, pool)
        except Exception:
            deletion._log('worker_retry')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass


@asynccontextmanager
async def deletion_lifespan(app):
    stop = asyncio.Event()
    task = asyncio.create_task(_recover(stop))
    try:
        yield
    finally:
        stop.set()
        # Let any current bounded pass finish; never cancel a DB cleanup mid-commit.
        # Abrupt process termination is still safe via the durable phase/claim.
        await task
