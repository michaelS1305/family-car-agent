"""Authenticated PWA views over the existing vehicle lifecycle/authority."""
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import UUID4
from psycopg.errors import LockNotAvailable, QueryCanceled
from auth_service import get_current_user
from identity import CurrentUser
from vehicle_identity import VehicleDetailsView, VehicleIdentityError
from vehicle_admission import _bounded_connection
from vehicle_work import AdmissionDeadlineExceeded
import vehicle_lifecycle as lifecycle
import vehicle_maintenance as maintenance

router = APIRouter(prefix='/api/vehicles', tags=['vehicles'])


def vehicle_pool():
    from database import pool
    return pool


class CreateVehicleRequest(lifecycle.VehicleCreationMetadata):
    request_id: UUID4


class VehicleStatusView(VehicleDetailsView):
    current_driver: str | None
    in_use: bool
    started_at: datetime | None


def _read(conn, current_user, vehicle_ref=None, *, include_retired=False):
    # Revalidate membership and read status in the same family-serialized unit.
    with _bounded_connection(conn) as bounded, lifecycle._scope(bounded, current_user):
        vehicles = (lifecycle.list_vehicles(bounded, current_user) if vehicle_ref is None
                    else [lifecycle.get_vehicle(bounded, current_user, vehicle_ref)])
        active = [vehicle for vehicle in vehicles if vehicle.retired_at is None]
        selected = vehicles if include_retired or vehicle_ref is not None else active
        rows = bounded.execute(
            'SELECT v.vehicle_ref,u.name,s.started_at FROM vehicles v '
            'JOIN vehicle_driver_sessions s ON s.vehicle_id=v.id AND s.ended_at IS NULL '
            'JOIN users u ON u.id=s.user_id WHERE v.family_id=%s AND v.vehicle_ref=ANY(%s)',
            (current_user.family_id, [v.vehicle_ref for v in active])).fetchall() if active else []
        sessions = {ref: (name, started_at) for ref, name, started_at in rows}
        return [VehicleStatusView(**v.model_dump(), current_driver=sessions.get(v.vehicle_ref, (None, None))[0],
                                  in_use=v.vehicle_ref in sessions,
                                  started_at=sessions.get(v.vehicle_ref, (None, None))[1]) for v in selected]


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
                         pool=Depends(vehicle_pool), include_retired: bool = False):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return _read(conn, current_user, include_retired=include_retired)
    return _call(run)


@router.get('/{vehicle_ref}', response_model=VehicleStatusView)
def vehicle_detail(vehicle_ref: UUID, response: Response,
                   current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return _read(conn, current_user, vehicle_ref)[0]
    return _call(run)


@router.post('', response_model=VehicleDetailsView)
def add_vehicle(request: CreateVehicleRequest, response: Response,
                current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return lifecycle.create_vehicle(conn, current_user, request.model_dump(exclude={'request_id'}, exclude_none=True),
                                            request_id=request.request_id)
    return _call(run)


@router.put('/{vehicle_ref}', response_model=VehicleDetailsView)
def edit_vehicle(vehicle_ref: UUID, request: lifecycle.VehicleUpdateMetadata, response: Response,
                 current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return lifecycle.update_vehicle(conn, current_user, vehicle_ref, request)
    return _call(run)


@router.post('/{vehicle_ref}/retire', response_model=VehicleDetailsView)
def retire_vehicle(vehicle_ref: UUID, response: Response,
                   current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return lifecycle.retire_vehicle(conn, current_user, vehicle_ref)
    return _call(run)


@router.get('/{vehicle_ref}/maintenance', response_model=list[maintenance.MaintenanceView])
def list_maintenance(vehicle_ref: UUID, response: Response,
                     current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return maintenance.list_items(conn, current_user, vehicle_ref)
    return _call(run)


@router.post('/{vehicle_ref}/maintenance', response_model=maintenance.MaintenanceView)
def add_maintenance(vehicle_ref: UUID, request: maintenance.MaintenanceRequest, response: Response,
                    current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return maintenance.create_item(conn, current_user, vehicle_ref, request)
    return _call(run)


@router.put('/{vehicle_ref}/maintenance/{maintenance_ref}', response_model=maintenance.MaintenanceView)
def edit_maintenance(vehicle_ref: UUID, maintenance_ref: UUID, request: maintenance.MaintenanceRequest,
                     response: Response, current_user: CurrentUser = Depends(get_current_user),
                     pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return maintenance.update_item(conn, current_user, vehicle_ref, maintenance_ref, request)
    return _call(run)


@router.post('/{vehicle_ref}/maintenance/{maintenance_ref}/complete', response_model=maintenance.MaintenanceView)
def complete_maintenance(vehicle_ref: UUID, maintenance_ref: UUID, response: Response,
                         current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            return maintenance.complete_item(conn, current_user, vehicle_ref, maintenance_ref)
    return _call(run)


@router.delete('/{vehicle_ref}/maintenance/{maintenance_ref}', status_code=204)
def delete_maintenance(vehicle_ref: UUID, maintenance_ref: UUID, response: Response,
                       current_user: CurrentUser = Depends(get_current_user), pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'
    def run():
        with pool.connection() as conn:
            maintenance.delete_item(conn, current_user, vehicle_ref, maintenance_ref)
    _call(run)
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})
