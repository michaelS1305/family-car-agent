"""Vehicle-scoped scheduled maintenance. No completion, reminders or direct client DB access."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

import vehicle_lifecycle as lifecycle
from vehicle_identity import VehicleIdentityError


class MaintenanceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    description: StrictStr
    scheduled_date: date

    @field_validator('scheduled_date', mode='before')
    @classmethod
    def date_only(cls, value):
        # Do not coerce epoch numbers or midnight timestamps into calendar dates.
        if type(value) is date:
            return value
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError('Expected YYYY-MM-DD')
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError('Expected YYYY-MM-DD')
        return parsed


class MaintenanceView(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    maintenance_ref: UUID
    description: str
    scheduled_date: date
    created_at: datetime


def _view(row):
    return MaintenanceView(maintenance_ref=row[0], description=row[1], scheduled_date=row[2], created_at=row[3])


def list_items(conn, current_user, vehicle_ref):
    with lifecycle._creation_scope(conn, current_user) as conn:
        vehicle = lifecycle._vehicle(conn, current_user, vehicle_ref)
        return [_view(row) for row in conn.execute(
            'SELECT maintenance_ref,description,scheduled_date,created_at FROM vehicle_maintenance '
            'WHERE vehicle_id=%s ORDER BY scheduled_date ASC,id ASC', (vehicle[0],)).fetchall()]


def create_item(conn, current_user, vehicle_ref, request):
    with lifecycle._creation_scope(conn, current_user) as conn:
        vehicle = lifecycle._vehicle(conn, current_user, vehicle_ref)
        lifecycle._require_creator(conn, current_user)
        lifecycle._require_active(vehicle)
        request = MaintenanceRequest.model_validate(request)
        if not conn.execute("SELECT %s::text !~ '^[[:space:]]*$'", (request.description,)).fetchone()[0]:
            raise VehicleIdentityError('INVALID_MAINTENANCE_DESCRIPTION', 'Description must not be blank', 422)
        return _view(conn.execute(
            'INSERT INTO vehicle_maintenance(vehicle_id,description,scheduled_date,created_by_user_id) '
            'VALUES(%s,%s,%s,%s) RETURNING maintenance_ref,description,scheduled_date,created_at',
            (vehicle[0], request.description, request.scheduled_date, current_user.user_id)).fetchone())
