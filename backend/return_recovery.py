"""Server-proven, immutable RETURN recovery. No network or standalone commits.

Caller owns the transaction. Family/device locks serialize normal admission,
recovery and deletion. Refusals that must persist are values until AFTER commit.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID

from psycopg.types.json import Jsonb
from vehicle_identity import VehicleIdentityError
from vehicle_admission import admit_native_event, _bounded_connection
import vehicle_lifecycle as lifecycle

HOME_CODES = frozenset(('RETURN_HOME_UNAVAILABLE', 'RETURN_OUTSIDE_HOME'))


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str
    status_code: int = 409


def refused(suffix):
    return Refusal('RETURN_RECOVERY_' + suffix, 'Return recovery could not be completed')


def canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    # Normalize negative zero and integer/float representations of GPS inputs.
    if isinstance(value, float) and value == 0:
        return 0.0
    return value


def fingerprint(payload):
    return sha256(json.dumps(canonical(payload), sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def original(event, evidence):
    return canonical(dict(event_id=event.event_id, device_ref=event.device_ref,
        vehicle_ref=event.vehicle_ref, device_sequence=event.device_sequence,
        occurred_at=event.occurred_at, take_event_id=event.take_event_id,
        latitude=float(evidence.latitude), longitude=float(evidence.longitude),
        accuracy_m=float(evidence.accuracy_m), location_at=evidence.location_at))


def cause_exists(conn, user, event, vehicle_id):
    return bool(conn.execute(
        "SELECT 1 FROM vehicle_events WHERE event_id=%s AND user_id=%s AND vehicle_id=%s "
        "AND family_id=%s AND event_type='take' AND admission_outcome='accepted' AND occurred_at<=%s",
        (event.take_event_id, user.user_id, vehicle_id, user.family_id, event.occurred_at)).fetchone())


def record_rejection(conn, user, event, evidence, device, vehicle, error):
    """Called INSIDE normal RETURN scope, only after authorized home rejection.

    An invalid cause still gets the original HTTP error, but is not eligible.
    ON CONFLICT never rewrites the first rejection's immutable evidence.
    """
    if error.code not in HOME_CODES:
        raise error
    if cause_exists(conn, user, event, vehicle[0]):
        payload = original(event, evidence)
        conn.execute(
            'INSERT INTO return_recovery_candidates '
            '(event_id,family_id,user_id,device_id,vehicle_id,device_sequence,take_event_id,'
            'occurred_at,rejection_code,payload_fingerprint,original_evidence) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
            (event.event_id, user.family_id, user.user_id, device[0], vehicle[0],
             event.device_sequence, event.take_event_id, event.occurred_at,
             error.code, fingerprint(payload), Jsonb(payload)))
    return Refusal(error.code, error.message, error.status_code)


class _AdmissionRefused(Exception):
    pass


def recover(conn, user, event, evidence, recovery_id, verification):
    import vehicle_bindings as bindings
    with _bounded_connection(conn) as conn, lifecycle._scope(conn, user):
        device = bindings._native(conn, user, event.device_ref)
        vehicle = lifecycle._vehicle(conn, user, event.vehicle_ref)
        if device[3] is not None:
            bindings.unavailable()
        candidate = conn.execute(
            'SELECT payload_fingerprint,rejection_code FROM return_recovery_candidates '
            'WHERE event_id=%s AND user_id=%s AND family_id=%s AND device_id=%s AND vehicle_id=%s FOR UPDATE',
            (event.event_id, user.user_id, user.family_id, device[0], vehicle[0])).fetchone()
        if not candidate:
            return refused('LEGACY_UNVERIFIED')
        payload = original(event, evidence)
        if candidate[0] != fingerprint(payload):
            return refused('EVIDENCE_MISMATCH')
        if candidate[1] not in HOME_CODES:
            return refused('NOT_ELIGIBLE')
        digest = fingerprint({'original': payload, 'verification': verification.model_dump()})
        # ID is scoped to candidate. Identical IDs on a different event cannot
        # collide or retrieve another user's outcome.
        prior = conn.execute(
            'SELECT payload_fingerprint,result FROM return_recovery_attempts '
            'WHERE event_id=%s AND recovery_id=%s', (event.event_id, recovery_id)).fetchone()
        if prior:
            if prior[0] != digest:
                return refused('IDEMPOTENCY_CONFLICT')
            return _restore(prior[1])
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        result = _verify_and_admit(conn, user, event, device, vehicle, verification, now, bindings)
        if not isinstance(result, Refusal):
            result['recovery_id'] = str(recovery_id)
        stored = ({'code': result.code, 'message': result.message, 'status_code': result.status_code}
                  if isinstance(result, Refusal) else result)
        # No raw verification coordinates are retained. Fingerprint binds them
        # for retries; timestamps plus outcome record the separate verification.
        conn.execute(
            'INSERT INTO return_recovery_attempts '
            '(event_id,recovery_id,payload_fingerprint,invoked_at,location_at,received_at,result) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (event.event_id, recovery_id, digest, verification.invoked_at,
             verification.location_at, now, Jsonb(stored)))
        return result


def _restore(result):
    return Refusal(**result) if 'code' in result else result


def _verify_and_admit(conn, user, event, device, vehicle, verification, now, bindings):
    # A DIFFERENT recovery attempt cannot overwrite/re-admit an existing receipt.
    if conn.execute('SELECT 1 FROM vehicle_events WHERE event_id=%s', (event.event_id,)).fetchone():
        return refused('NOT_ELIGIBLE')
    if not cause_exists(conn, user, event, vehicle[0]):
        return refused('NOT_ELIGIBLE')
    if vehicle[3] is not None or not conn.execute(
        'SELECT 1 FROM registered_device_vehicle_bindings WHERE device_id=%s AND vehicle_id=%s',
        (device[0], vehicle[0])).fetchone():
        return refused('NOT_ELIGIBLE')
    if not (0 <= (verification.invoked_at - verification.location_at).total_seconds() <= 30
            and 0 <= (now - verification.invoked_at).total_seconds() <= 120
            and verification.invoked_at >= event.occurred_at):
        return refused('VERIFICATION_EXPIRED')
    try:
        bindings.verify_home(conn, user, verification)
    except VehicleIdentityError as error:
        if error.code not in HOME_CODES:
            raise
        return Refusal(error.code, error.message, error.status_code)
    try:
        # Existing admission may write a terminal receipt and advance sequence.
        # Recovery must retain blocked evidence, not consume/skip a refused event.
        # Roll all those effects back, then persist ONLY this attempt's outcome.
        with conn.transaction():
            outcome = admit_native_event(conn, user, event)
            if outcome.kind != 'accepted' or outcome.admission_outcome != 'accepted':
                raise _AdmissionRefused()
    except _AdmissionRefused:
        return refused('ORDER_CONFLICT')
    return {'kind': 'accepted', 'admission_outcome': 'accepted',
            'recovery_outcome': 'recovered', 'event_id': str(event.event_id),
            'verified_at': canonical(now)}
