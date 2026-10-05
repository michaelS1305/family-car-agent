"""Shortcut boundary only. No alternative occupancy state machine."""
from uuid import UUID, uuid5

from identity import CurrentUser
from vehicle_admission import NativeEvent, AdmissionResult, _admit, _bounded_connection
from vehicle_lifecycle import _scope, _vehicle
from vehicle_identity import VehicleIdentityError
from vehicle_creation_policy import request_key


def bind_vehicle(conn, current_user, vehicle_ref):
    """JWT caller owns this binding; opaque vehicle ref is family-validated."""
    with _bounded_connection(conn) as conn, _scope(conn, current_user):
        vehicle = _vehicle(conn, current_user, vehicle_ref)
        if vehicle[3] is not None:
            raise VehicleIdentityError('VEHICLE_NOT_FOUND_OR_UNAVAILABLE', 'Vehicle unavailable')
        conn.execute('INSERT INTO carplay_vehicle_bindings(user_id,family_id,vehicle_id) VALUES(%s,%s,%s) '
                     'ON CONFLICT(user_id) DO UPDATE SET family_id=EXCLUDED.family_id,vehicle_id=EXCLUDED.vehicle_id',
                     (current_user.user_id, current_user.family_id, vehicle[0]))
        return {'vehicle_ref': str(vehicle[1])}


def operation_id(auth_user_id, acquisition_id, event_type):
    # Scoped deterministic operation identity: retries cannot allocate new IDs.
    return uuid5(UUID(str(auth_user_id)), 'fca-carplay-v1:' + str(acquisition_id) + ':' + event_type)


def transition(conn, current_user, acquisition_id, *, disconnect=False):
    acquisition_id = request_key(acquisition_id)
    event_type = 'return' if disconnect else 'take'
    event_id = operation_id(current_user.auth_user_id, acquisition_id, event_type)
    take_id = operation_id(current_user.auth_user_id, acquisition_id, 'take') if disconnect else None
    with _bounded_connection(conn) as bounded, _scope(bounded, current_user):
        binding = bounded.execute(
            'SELECT v.vehicle_ref FROM carplay_vehicle_bindings b JOIN vehicles v '
            'ON v.id=b.vehicle_id AND v.family_id=b.family_id '
            'WHERE b.user_id=%s AND b.family_id=%s AND v.retired_at IS NULL',
            (current_user.user_id, current_user.family_id)).fetchone()
        if not binding:
            raise VehicleIdentityError('CARPLAY_BINDING_UNAVAILABLE', 'CarPlay vehicle binding unavailable', 409)
        previous = bounded.execute('SELECT occurred_at FROM vehicle_events WHERE event_id=%s AND user_id=%s '
                                   'AND family_id=%s AND source=\'legacy_shortcut\'',
                                   (event_id, current_user.user_id, current_user.family_id)).fetchone()
        now = previous[0] if previous else bounded.execute('SELECT clock_timestamp()').fetchone()[0]
        # The engine aliases redundant TAKEs to one session. A new Shortcut
        # acquisition is nevertheless a new physical detector cycle: an older
        # cycle's RETURN must not close that still-active aliased acquisition.
        # Exact operation retries remain handled by the engine below.
        if disconnect and not previous and bounded.execute(
            'SELECT 1 FROM vehicle_events cause JOIN vehicle_driver_sessions s '
            'ON s.start_event_id=cause.projection_take_event_id '
            'WHERE cause.event_id=%s AND cause.user_id=%s AND cause.family_id=%s '
            'AND s.ended_at IS NULL AND EXISTS (SELECT 1 FROM vehicle_events newer '
            'WHERE newer.projection_take_event_id=s.start_event_id '
            "AND newer.source='legacy_shortcut' AND newer.event_type='take' "
            "AND newer.admission_outcome='accepted' "
            'AND (newer.occurred_at,newer.event_id)>(cause.occurred_at,cause.event_id))',
            (take_id, current_user.user_id, current_user.family_id)).fetchone():
            return AdmissionResult('conflict'), None, now.isoformat()
        event = NativeEvent(event_id, None, binding[0], event_type, now, None, take_id)
        result = _admit(bounded, current_user, event, shortcut=True)
        receipt = bounded.execute('SELECT id FROM vehicle_events WHERE event_id=%s AND user_id=%s AND family_id=%s',
                                  (event_id, current_user.user_id, current_user.family_id)).fetchone()
        return result, receipt[0] if receipt else None, now.isoformat()
