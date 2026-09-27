"""Internal creation policy; not native event-ingestion rate limits."""
from hashlib import sha256
from uuid import UUID

from vehicle_identity import VehicleIdentityError

VEHICLES_ACTIVE = 10
VEHICLES_LIFETIME = 50
DEVICES_USER_ACTIVE = 5
DEVICES_USER_LIFETIME = 30
DEVICES_FAMILY_ACTIVE = 20
DEVICES_FAMILY_LIFETIME = 100


def request_key(value):
    # Deliberately no server-generated default: the caller must reuse its key.
    if isinstance(value, str) and len(value) == 36:
        try:
            parsed = UUID(value)
            if str(parsed) == value:
                value = parsed
        except ValueError:
            pass
    if not isinstance(value, UUID) or value.version != 4:
        raise VehicleIdentityError('INVALID_CREATION_REQUEST_ID', 'Invalid creation request identifier', 422)
    return value


def fingerprint(value):
    return sha256(value.encode('utf-8')).digest()


def limit(reached, code):
    if reached:
        raise VehicleIdentityError(code, 'Resource creation limit reached', 409)


def conflict():
    raise VehicleIdentityError('CREATION_IDEMPOTENCY_CONFLICT', 'Creation request conflicts', 409)
