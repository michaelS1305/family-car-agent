"""Strict, self-only capture. Validation must never echo submitted credentials."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from auth_service import get_authenticated_supabase_user
from database import pool
from apple_credentials import Store, capture

router = APIRouter()


class Credential(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    code: str = Field(min_length=1, max_length=4096, repr=False)
    nonce: str = Field(min_length=16, max_length=256, repr=False)


@router.post('/api/account/apple-credential')
async def submit(request: Request, identity=Depends(get_authenticated_supabase_user)):
    try:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8192:
                return JSONResponse({'status': 'invalid_request'}, status_code=422)
        body = Credential.model_validate_json(data)
    except (ValidationError, ValueError):
        return JSONResponse({'status': 'invalid_request'}, status_code=422)
    result = await run_in_threadpool(capture, Store(pool), identity.auth_user_id, body.code, body.nonce)
    return JSONResponse(result, status_code=200 if result['status'] == 'stored' else 503)
