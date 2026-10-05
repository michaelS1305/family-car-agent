"""Self-only deletion endpoints and a restart-safe, bounded recovery loop."""
import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

import account_deletion as deletion
from auth_service import get_deletion_identity
from database import pool
from identity import AuthenticatedSupabaseUser


router = APIRouter(prefix='/api/account/deletion')


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    confirmation: Literal['DELETE_MY_ACCOUNT']


@router.get('/preview')
def preview(identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    return deletion.preview(pool, identity.auth_user_id)


@router.get('')
def status(identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    return deletion.status(pool, identity.auth_user_id)


@router.post('', status_code=202)
def confirm(body: Confirmation, identity: AuthenticatedSupabaseUser = Depends(get_deletion_identity)):
    return deletion.confirm(pool, identity.auth_user_id)


async def _recover(stop):
    while not stop.is_set():
        try:
            await asyncio.to_thread(deletion.run_due, pool, stop.is_set)
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
