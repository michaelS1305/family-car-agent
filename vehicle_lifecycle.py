"""Internal lifecycle services; no routes, pool, network or event activation.

Every operation owns a transaction/savepoint on the caller's connection. If an
outer transaction exists, the caller owns final commit. Lock order is shared
identity fence -> existing family car advisory lock -> family row -> target row.
Never acquire another member's identity lock. This serializes with admission
and account deletion, including membership revalidation after the family lock.

Registration creates a new identity each time: the schema has no installation
identity/idempotency key. Do not automatically retry a lost registration response.
Device platform is registration-time metadata, not an editable identity field;
last_seen_at, sequence and revocation are server-managed, not generic updates.
"""
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr

from deletion_gate import require_auth
from vehicle_admission import CAR_TRANSITION_LOCK_NAMESPACE
from vehicle_identity import DeviceView, VehicleView, VehicleIdentityError, _ref


class VehicleMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    display_name: StrictStr


class DeviceRegistration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    platform: Literal['android', 'ios']


@contextmanager
def _scope(conn, current_user):
    with conn.transaction():
        require_auth(conn, current_user.auth_user_id)
        family = current_user.family_id
        if family is None:
            raise VehicleIdentityError('FAMILY_ACCESS_DENIED', 'Family access denied', 403)
        conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', (CAR_TRANSITION_LOCK_NAMESPACE, family))
        row = conn.execute('SELECT id FROM families WHERE id=%s FOR UPDATE', (family,)).fetchone()
        if not row or not conn.execute(
            'SELECT 1 FROM users WHERE id=%s AND family_id=%s AND auth_user_id=%s',
            (current_user.user_id, family, current_user.auth_user_id),
        ).fetchone():
            raise VehicleIdentityError('FAMILY_ACCESS_DENIED', 'Family access denied', 403)
        yield


def _vehicle_view(row):
    return VehicleView(vehicle_ref=row[1], display_name=row[2], retired_at=row[3])


def _device_view(row):
    return DeviceView(device_ref=row[1], platform=row[2], revoked_at=row[3])


def _vehicle(conn, current_user, ref):
    ref = _ref(ref)
    row = None if ref is None else conn.execute(
        'SELECT id,vehicle_ref,display_name,retired_at FROM vehicles '
        'WHERE family_id=%s AND vehicle_ref=%s FOR UPDATE',
        (current_user.family_id, ref),
    ).fetchone()
    if row is None:
        raise VehicleIdentityError('VEHICLE_NOT_FOUND_OR_UNAVAILABLE', 'Vehicle unavailable')
    return row


def _device(conn, current_user, ref):
    ref = _ref(ref)
    row = None if ref is None else conn.execute(
        'SELECT id,device_ref,platform,revoked_at FROM registered_devices '
        'WHERE user_id=%s AND device_ref=%s FOR UPDATE', (current_user.user_id, ref),
    ).fetchone()
    if row is None:
        raise VehicleIdentityError('DEVICE_NOT_FOUND_OR_UNAVAILABLE', 'Device unavailable')
    return row


def _name(conn, request):
    request = VehicleMetadata.model_validate(request)
    # Match the actual PostgreSQL whitespace constraint, without silent trimming
    # or inventing a name uniqueness/length requirement absent from the schema.
    if not conn.execute("SELECT %s::text !~ '^[[:space:]]*$'", (request.display_name,)).fetchone()[0]:
        raise VehicleIdentityError('INVALID_VEHICLE_NAME', 'Vehicle name must not be blank', 422)
    return request.display_name


def list_vehicles(conn, current_user):
    """All family vehicles, including retired history; public-safe views only."""
    with _scope(conn, current_user):
        return [_vehicle_view(row) for row in conn.execute(
            'SELECT id,vehicle_ref,display_name,retired_at FROM vehicles WHERE family_id=%s ORDER BY id',
            (current_user.family_id,),
        ).fetchall()]


def get_vehicle(conn, current_user, vehicle_ref):
    with _scope(conn, current_user):
        return _vehicle_view(_vehicle(conn, current_user, vehicle_ref))


def create_vehicle(conn, current_user, request: VehicleMetadata):
    with _scope(conn, current_user):
        name = _name(conn, request)
        row = conn.execute(
            'INSERT INTO vehicles(family_id,created_by_user_id,display_name) VALUES(%s,%s,%s) '
            'RETURNING id,vehicle_ref,display_name,retired_at',
            (current_user.family_id, current_user.user_id, name),
        ).fetchone()
        return _vehicle_view(row)


def update_vehicle(conn, current_user, vehicle_ref, request: VehicleMetadata):
    """Rename only; retired history may be renamed, never reactivated."""
    with _scope(conn, current_user):
        row = _vehicle(conn, current_user, vehicle_ref)
        name = _name(conn, request)
        updated = conn.execute(
            'UPDATE vehicles SET display_name=%s WHERE id=%s RETURNING id,vehicle_ref,display_name,retired_at',
            (name, row[0]),
        ).fetchone()
        return _vehicle_view(updated)


def retire_vehicle(conn, current_user, vehicle_ref):
    """Idempotent soft retirement; preserves original timestamp and all history.

    Reservations are deliberately untouched. Slice 5B must define booking and
    existing-reservation policy for retired vehicles before public activation.
    """
    with _scope(conn, current_user):
        row = _vehicle(conn, current_user, vehicle_ref)
        if conn.execute('SELECT 1 FROM vehicle_driver_sessions WHERE vehicle_id=%s AND ended_at IS NULL LIMIT 1',
                        (row[0],)).fetchone():
            raise VehicleIdentityError('VEHICLE_IN_USE', 'Vehicle is currently in use', 409)
        if row[3] is None:
            row = conn.execute(
                'UPDATE vehicles SET retired_at=clock_timestamp() WHERE id=%s '
                'RETURNING id,vehicle_ref,display_name,retired_at', (row[0],),
            ).fetchone()
        return _vehicle_view(row)


def list_devices(conn, current_user):
    """Only own devices, including revoked identities; no sequence disclosure."""
    with _scope(conn, current_user):
        return [_device_view(row) for row in conn.execute(
            'SELECT id,device_ref,platform,revoked_at FROM registered_devices WHERE user_id=%s ORDER BY id',
            (current_user.user_id,),
        ).fetchall()]


def get_device(conn, current_user, device_ref):
    with _scope(conn, current_user):
        return _device_view(_device(conn, current_user, device_ref))


def register_device(conn, current_user, request: DeviceRegistration):
    request = DeviceRegistration.model_validate(request)
    with _scope(conn, current_user):
        row = conn.execute(
            'INSERT INTO registered_devices(user_id,platform) VALUES(%s,%s) '
            'RETURNING id,device_ref,platform,revoked_at',
            (current_user.user_id, request.platform),
        ).fetchone()
        return _device_view(row)


def revoke_device(conn, current_user, device_ref):
    """Idempotent; does not reset sequence, erase evidence or end occupancy."""
    with _scope(conn, current_user):
        row = _device(conn, current_user, device_ref)
        if row[3] is None:
            row = conn.execute(
                'UPDATE registered_devices SET revoked_at=clock_timestamp() WHERE id=%s '
                'RETURNING id,device_ref,platform,revoked_at', (row[0],),
            ).fetchone()
        return _device_view(row)
