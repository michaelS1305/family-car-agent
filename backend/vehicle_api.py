"""Authenticated PWA views over the existing vehicle lifecycle/authority."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, StrictStr, UUID4
from psycopg.errors import LockNotAvailable, QueryCanceled
from auth_service import get_current_user
from identity import CurrentUser
from vehicle_identity import VehicleView, VehicleIdentityError
from vehicle_admission import _bounded_connection
from vehicle_work import AdmissionDeadlineExceeded
import vehicle_lifecycle as lifecycle

router = APIRouter(prefix='/api/vehicles', tags=['vehicles'])


def vehicle_pool():
    from database import pool
    return pool


class CreateVehicleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    display_name: StrictStr
    request_id: UUID4


class VehicleStatusView(VehicleView):
    current_driver: str | None
    in_use: bool


def _read(conn, current_user, vehicle_ref=None):
    # Revalidate membership and read status in the same family-serialized unit.
    with _bounded_connection(conn) as bounded, lifecycle._scope(bounded, current_user):
        vehicles = (lifecycle.list_vehicles(bounded, current_user) if vehicle_ref is None
                    else [lifecycle.get_vehicle(bounded, current_user, vehicle_ref)])
        if vehicle_ref is not None and vehicles[0].retired_at is not None:
            raise VehicleIdentityError('VEHICLE_NOT_FOUND_OR_UNAVAILABLE', 'Vehicle unavailable')
        active = [vehicle for vehicle in vehicles if vehicle.retired_at is None]
        rows = bounded.execute(
            'SELECT v.vehicle_ref,u.name,s.id FROM vehicles v '
            'JOIN vehicle_driver_sessions s ON s.vehicle_id=v.id AND s.ended_at IS NULL '
            'JOIN users u ON u.id=s.user_id WHERE v.family_id=%s AND v.vehicle_ref=ANY(%s)',
            (current_user.family_id, [v.vehicle_ref for v in active])).fetchall() if active else []
        drivers = {ref: name for ref, name, _ in rows}
        return [VehicleStatusView(**v.model_dump(), current_driver=drivers.get(v.vehicle_ref),
                                  in_use=v.vehicle_ref in drivers) for v in active]


def _call(operation):
    try:
        return operation()
    except VehicleIdentityError as error:
        raise HTTPException(error.status_code, detail={'code': error.code, 'message': error.message}) from error
    except (LockNotAvailable, QueryCanceled, AdmissionDeadlineExceeded) as error:
        raise HTTPException(503, detail={'code': 'VEHICLES_BUSY', 'message': 'Try again'},
                            headers={'Retry-After': '1'}) from error


@router.get('', response_model=list[VehicleStatusView])
def list_family_vehicles(response: Response, current_user: CurrentUser = Depends(get_current_user),
                         pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return _read(conn, current_user)
    return _call(run)


@router.get('/{vehicle_ref}', response_model=VehicleStatusView)
def vehicle_detail(vehicle_ref: UUID, response: Response,
                   current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return _read(conn, current_user, vehicle_ref)[0]
    return _call(run)


@router.post('', response_model=VehicleView)
def add_vehicle(request: CreateVehicleRequest, response: Response,
                current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return lifecycle.create_vehicle(conn, current_user, {'display_name': request.display_name},
                                            request_id=request.request_id)
    return _call(run)
