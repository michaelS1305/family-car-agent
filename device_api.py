"""JWT-authenticated Android installation/binding/TAKE surface."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, UUID4
from auth_service import get_current_user
from deletion_gate import IdentityUnavailable
from identity import CurrentUser
from vehicle_admission import NativeEvent
from vehicle_api import vehicle_pool, _call
import vehicle_lifecycle as lifecycle
import vehicle_bindings

router = APIRouter(prefix='/api/devices', tags=['devices'])


class Registration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID4


class Take(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID4
    vehicle_ref: UUID
    device_sequence: int = Field(strict=True, ge=1, le=9223372036854775807)
    occurred_at: AwareDatetime


def run(pool, response, operation):
    response.headers['Cache-Control'] = 'no-store'
    def execute():
        try:
            with pool.connection() as conn:
                return operation(conn)
        except IdentityUnavailable:
            raise HTTPException(403, detail={'code': 'IDENTITY_UNAVAILABLE', 'message': 'Identity unavailable'}) from None
    return _call(execute)


@router.post('')
def register(body: Registration, response: Response, user: CurrentUser = Depends(get_current_user),
             pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: lifecycle.register_device(c, user, {'platform': 'android'},
                                                                  request_id=body.request_id))


@router.get('')
def devices(response: Response, user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: [d for d in lifecycle.list_devices(c, user) if d.platform == 'android'])


@router.get('/{device_ref}/vehicle-bindings')
def list_bindings(device_ref: UUID, response: Response, user: CurrentUser = Depends(get_current_user),
                  pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: vehicle_bindings.bindings(c, user, device_ref))


@router.put('/{device_ref}/vehicle-bindings/{vehicle_ref}')
def put_binding(device_ref: UUID, vehicle_ref: UUID, response: Response,
                user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: vehicle_bindings.bindings(c, user, device_ref, vehicle_ref))


@router.delete('/{device_ref}/vehicle-bindings/{vehicle_ref}')
def delete_binding(device_ref: UUID, vehicle_ref: UUID, response: Response,
                   user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: vehicle_bindings.bindings(c, user, device_ref, vehicle_ref, remove=True))


@router.post('/{device_ref}/events/take')
def take(device_ref: UUID, body: Take, response: Response, user: CurrentUser = Depends(get_current_user),
         pool=Depends(vehicle_pool)):
    event = NativeEvent(body.event_id, device_ref, body.vehicle_ref, 'take', body.occurred_at, body.device_sequence)
    return run(pool, response, lambda c: vehicle_bindings.admit_take(c, user, event))
