"""Authenticated, read-only shared manufacturer catalogue."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from auth_service import get_current_user
from identity import CurrentUser
from vehicle_api import _call, vehicle_pool
from vehicle_admission import _bounded_connection
from vehicle_lifecycle import _scope

router = APIRouter(prefix='/api/reference', tags=['vehicle-reference'])


class ManufacturerView(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    id: int
    name_he: str


def _read(conn, user):
    with _bounded_connection(conn) as bounded, _scope(bounded, user):
        return [ManufacturerView(id=row[0], name_he=row[1]) for row in bounded.execute(
            'SELECT id,name_he FROM vehicle_manufacturers WHERE is_active '
            'ORDER BY name_he COLLATE "C" ASC,id ASC').fetchall()]


@router.get('/manufacturers', response_model=list[ManufacturerView])
def manufacturers(response: Response, user: CurrentUser = Depends(get_current_user),
                  pool=Depends(vehicle_pool)):
    response.headers['Cache-Control'] = 'no-store'

    def run():
        with pool.connection() as conn:
            return _read(conn, user)

    return _call(run)
