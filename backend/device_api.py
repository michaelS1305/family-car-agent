"""JWT-authenticated native installation/binding/event surface."""
from typing import Literal
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
from native_push_outbox import commit_boundary
import return_recovery
from vehicle_identity import VehicleIdentityError

router = APIRouter(prefix='/api/devices', tags=['devices'])


class Registration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID4
    platform: Literal['android', 'ios'] = 'android'


class Take(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID4
    vehicle_ref: UUID
    device_sequence: int = Field(strict=True, ge=1, le=9223372036854775807)
    occurred_at: AwareDatetime


class Return(Take):
    take_event_id: UUID4
    latitude: float = Field(strict=True, ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(strict=True, ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float = Field(strict=True, gt=0, le=100, allow_inf_nan=False)
    location_at: AwareDatetime


class ReturnVerification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    invoked_at: AwareDatetime
    location_at: AwareDatetime
    latitude: float = Field(strict=True, ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(strict=True, ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float = Field(strict=True, gt=0, le=100, allow_inf_nan=False)


class ReturnRecovery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recovery_id: UUID4
    original_return: Return
    verification: ReturnVerification


def run(pool, response, operation):
    response.headers['Cache-Control'] = 'no-store'
    def execute():
        try:
            with commit_boundary(), pool.connection() as conn:
                result = operation(conn)
            # Refusal records must commit before the public HTTP error is raised.
            if isinstance(result, return_recovery.Refusal):
                raise VehicleIdentityError(result.code, result.message, result.status_code)
            return result
        except IdentityUnavailable:
            raise HTTPException(403, detail={'code': 'IDENTITY_UNAVAILABLE', 'message': 'Identity unavailable'}) from None
    return _call(execute)


@router.post('')
def register(body: Registration, response: Response, user: CurrentUser = Depends(get_current_user),
             pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: lifecycle.register_device(c, user, {'platform': body.platform},
                                                                  request_id=body.request_id))


@router.get('')
def devices(response: Response, user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool),
            platform: Literal['android', 'ios'] = 'android'):
    return run(pool, response, lambda c: [d for d in lifecycle.list_devices(c, user) if d.platform == platform])


@router.get('/{device_ref}/vehicle-bindings')
def list_bindings(device_ref: UUID, response: Response, user: CurrentUser = Depends(get_current_user),
                  pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: vehicle_bindings.bindings(c, user, device_ref))


@router.get('/{device_ref}/return-home')
def return_home(device_ref: UUID, response: Response, user: CurrentUser = Depends(get_current_user),
                pool=Depends(vehicle_pool)):
    return run(pool, response, lambda c: vehicle_bindings.return_home(c, user, device_ref))


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


@router.post('/{device_ref}/events/return')
def return_event(device_ref: UUID, body: Return, response: Response,
                 user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    event = NativeEvent(body.event_id, device_ref, body.vehicle_ref, 'return', body.occurred_at,
                        body.device_sequence, body.take_event_id)
    return run(pool, response, lambda c: vehicle_bindings.admit_return(c, user, event, body, record_rejection=True))


@router.post('/{device_ref}/events/return/{event_id}/recovery')
def recover_return(device_ref: UUID, event_id: UUID4, body: ReturnRecovery, response: Response,
                   user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    original = body.original_return
    if original.event_id != event_id:
        raise HTTPException(409, detail={'code': 'RETURN_RECOVERY_EVIDENCE_MISMATCH',
                                        'message': 'Return recovery could not be completed'})
    event = NativeEvent(original.event_id, device_ref, original.vehicle_ref, 'return',
                        original.occurred_at, original.device_sequence, original.take_event_id)
    return run(pool, response, lambda c: return_recovery.recover(
        c, user, event, original, body.recovery_id, body.verification))
