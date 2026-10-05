"""Native installation authorization, serialized with lifecycle and admission."""
import vehicle_lifecycle as lifecycle
from math import isfinite
from car_service import calculate_distance_meters
from vehicle_admission import admit_native_event, _bounded_connection
from vehicle_identity import VehicleIdentityError


def unavailable():
    raise VehicleIdentityError('DEVICE_OR_VEHICLE_UNAVAILABLE', 'Device or vehicle unavailable')


def _android(conn, user, ref):
    device = lifecycle._device(conn, user, ref)
    if device[2] != 'android':
        unavailable()
    return device


def bindings(conn, user, device_ref, vehicle_ref=None, *, remove=False):
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device = _android(conn, user, device_ref)
        if vehicle_ref is None:
            rows = conn.execute(
                'SELECT v.vehicle_ref,v.display_name,v.retired_at FROM registered_device_vehicle_bindings b '
                'JOIN vehicles v ON v.id=b.vehicle_id WHERE b.device_id=%s AND v.family_id=%s ORDER BY v.id',
                (device[0], user.family_id)).fetchall()
            return [{'vehicle_ref': r[0], 'display_name': r[1],
                     'usable': device[3] is None and r[2] is None} for r in rows]
        vehicle = lifecycle._vehicle(conn, user, vehicle_ref)
        if remove:
            conn.execute('DELETE FROM registered_device_vehicle_bindings WHERE device_id=%s AND vehicle_id=%s',
                         (device[0], vehicle[0]))
        else:
            if device[3] is not None or vehicle[3] is not None:
                unavailable()
            conn.execute('INSERT INTO registered_device_vehicle_bindings(device_id,vehicle_id) VALUES(%s,%s) '
                         'ON CONFLICT(device_id,vehicle_id) DO NOTHING', (device[0], vehicle[0]))


def admit_take(conn, user, event):
    if event.event_type != 'take':
        unavailable()
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device = _android(conn, user, event.device_ref)
        vehicle = lifecycle._vehicle(conn, user, event.vehicle_ref)
        if device[3] is not None:
            unavailable()
        # Committed receipt replay is not new authorization. Exact matching and
        # sequence checks remain in admission; no second reconciliation occurs.
        prior = conn.execute('SELECT 1 FROM vehicle_events WHERE event_id=%s AND device_id=%s',
                             (event.event_id, device[0])).fetchone()
        if not prior and (vehicle[3] is not None or not conn.execute(
                'SELECT 1 FROM registered_device_vehicle_bindings WHERE device_id=%s AND vehicle_id=%s',
                (device[0], vehicle[0])).fetchone()):
            unavailable()
        return admit_native_event(conn, user, event)


def _home(conn, user):
    home = conn.execute('SELECT home_latitude,home_longitude FROM families WHERE id=%s',
                        (user.family_id,)).fetchone()
    if not home or any(v is None or not isfinite(v) for v in home) or not (
            -90 <= home[0] <= 90 and -180 <= home[1] <= 180):
        raise VehicleIdentityError('RETURN_HOME_UNAVAILABLE', 'Home unavailable', 409)
    return home


def return_home(conn, user, device_ref):
    # Necessary for offline prequalification, never a server authorization token.
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        if _android(conn, user, device_ref)[3] is not None:
            unavailable()
        latitude, longitude = _home(conn, user)
        return {'latitude': latitude, 'longitude': longitude}


def admit_return(conn, user, event, evidence):
    if event.event_type != 'return':
        unavailable()
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device = _android(conn, user, event.device_ref)
        vehicle = lifecycle._vehicle(conn, user, event.vehicle_ref)
        if device[3] is not None:
            unavailable()
        prior = conn.execute('SELECT 1 FROM vehicle_events WHERE event_id=%s AND device_id=%s',
                             (event.event_id, device[0])).fetchone()
        if not prior:
            if vehicle[3] is not None or not conn.execute(
                    'SELECT 1 FROM registered_device_vehicle_bindings WHERE device_id=%s AND vehicle_id=%s',
                    (device[0], vehicle[0])).fetchone():
                unavailable()
            # Fresh relative to the physical decision, not delivery: offline is supported.
            age = (event.occurred_at - evidence.location_at).total_seconds()
            if not 0 <= age <= 30:
                raise VehicleIdentityError('RETURN_LOCATION_INVALID', 'Location unavailable', 422)
            latitude, longitude = _home(conn, user)
            try:
                distance = calculate_distance_meters(evidence.latitude, evidence.longitude, latitude, longitude)
            except (ValueError, OverflowError):
                # Finite antipodal inputs can still encounter floating-point
                # roundoff in the shared haversine helper. Fail closed safely.
                raise VehicleIdentityError('RETURN_OUTSIDE_HOME', 'Home verification failed', 409) from None
            if not isfinite(distance) or distance + evidence.accuracy_m > 500:
                raise VehicleIdentityError('RETURN_OUTSIDE_HOME', 'Home verification failed', 409)
        # No GPS stored. Exact event/cause matching and all side effects belong to
        # the existing receipt/reconciliation engine, including committed retries.
        return admit_native_event(conn, user, event)
