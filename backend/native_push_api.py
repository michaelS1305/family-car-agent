"""Separate Native Push surface. Never return secret input or provider errors."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field, UUID4

from auth_service import get_current_user
from identity import CurrentUser
from native_push_outbox import enabled, wakeup
from native_push_security import Config, ConfigurationError
from vehicle_api import vehicle_pool, _call
import native_push_registration as registration
import native_push_refresh as refresh

router = APIRouter(prefix='/api/native-push', tags=['native-push'])


class Begin(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    installation_ref: UUID4
    request_id: UUID4
    platform: Literal['android','ios']
    token: str = Field(min_length=20,max_length=4096,pattern=r'^[A-Za-z0-9_:\-.]+$',repr=False)


class Confirm(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    challenge_ref: UUID4
    nonce: str = Field(min_length=43,max_length=43,pattern=r'^[A-Za-z0-9_-]+$',repr=False)


class Revoke(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_generation: int = Field(strict=True,ge=1,lt=9223372036854775807)


def configuration():
    try:
        if not enabled():
            raise ConfigurationError()
        return Config.load()
    except ConfigurationError:
        raise HTTPException(503,detail={'code':'NATIVE_PUSH_UNAVAILABLE'}) from None


def run(pool, operation):
    def execute():
        try:
            with pool.connection() as conn:
                conn.execute("SET LOCAL lock_timeout='1s'")
                conn.execute("SET LOCAL statement_timeout='3s'")
                result = operation(conn)
        except refresh.RefreshError as error:
            raise HTTPException(error.status, detail={'code': error.code}) from None
        except ConfigurationError:
            raise HTTPException(503,detail={'code':'NATIVE_PUSH_UNAVAILABLE'}) from None
        # Real commit has completed; failed guesses must commit their attempt count.
        if result.get('code') == 'CHALLENGE_PENDING':
            wakeup.set()
        return result
    return _call(execute)


@router.post('/registrations',status_code=202)
def begin(body: Begin, response: Response, user: CurrentUser=Depends(get_current_user),
          config=Depends(configuration), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control']='no-store'
    return run(pool,lambda conn:registration.begin(conn,user,config,**body.model_dump()))


@router.post('/installations/{installation_ref}/confirm')
def confirm(installation_ref: UUID, body: Confirm, response: Response, user: CurrentUser=Depends(get_current_user),
            config=Depends(configuration), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control']='no-store'
    return run(pool,lambda conn:registration.confirm(conn,user,config,installation_ref=installation_ref,**body.model_dump()))


@router.post('/installations/{installation_ref}/revoke')
def revoke(installation_ref: UUID, body: Revoke, response: Response,user: CurrentUser=Depends(get_current_user),
           config=Depends(configuration),pool=Depends(vehicle_pool)):
    response.headers['Cache-Control']='no-store'
    return run(pool,lambda conn:registration.revoke(conn,user,config,installation_ref,body.expected_generation))


@router.get('/installations/{installation_ref}/events')
def events(installation_ref: UUID, response: Response,
           expected_generation: int = Query(ge=1, lt=9223372036854775807),
           limit: int = Query(default=20, ge=1, le=50), cursor: UUID | None = None,
           user: CurrentUser = Depends(get_current_user), config=Depends(configuration), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    return run(pool, lambda conn: refresh.events(conn, user, config, installation_ref, expected_generation, limit, cursor))
