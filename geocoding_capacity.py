"""Backend-only PostgreSQL admission for Google geocoding calls."""
import math
from uuid import uuid4

from database import pool
from geocoding_limits import (
    PERMIT_SECONDS,
    PROVIDER_CALL_DEADLINE_SECONDS,
    UNCERTAIN_SECONDS,
)


WINDOW_SECONDS = 10 * 60


class GeocodingAdmissionError(Exception):
    def __init__(self, code, status_code, retry_after_seconds):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = max(1, math.ceil(retry_after_seconds))


def acquire(auth_user_id):
    if not auth_user_id:
        raise RuntimeError("Authenticated identity is required for geocoding")

    attempt_id = str(uuid4())
    with pool.connection() as conn:
        with conn.transaction():
            policy = conn.execute(
                "SELECT max_concurrency FROM geocoding_capacity_policies "
                "WHERE capacity_pool = 'google-geocoding' FOR UPDATE"
            ).fetchone()
            if not policy:
                raise RuntimeError("Geocoding capacity policy is not configured")

            # Cleanup is bounded. The final predicates are rechecked after any
            # concurrent row update, so an extended uncertain permit is retained.
            conn.execute(
                "UPDATE geocoding_attempts SET permit_expires_at = NULL "
                "WHERE attempt_id IN (SELECT attempt_id FROM geocoding_attempts "
                "WHERE permit_expires_at <= clock_timestamp() "
                "ORDER BY permit_expires_at LIMIT 100) "
                "AND permit_expires_at <= clock_timestamp()"
            )
            conn.execute(
                "DELETE FROM geocoding_attempts WHERE attempt_id IN "
                "(SELECT attempt_id FROM geocoding_attempts "
                "WHERE admitted_at <= clock_timestamp() - INTERVAL '10 minutes' "
                "AND permit_expires_at IS NULL ORDER BY admitted_at LIMIT 100) "
                "AND admitted_at <= clock_timestamp() - INTERVAL '10 minutes' "
                "AND permit_expires_at IS NULL"
            )

            active_user = conn.execute(
                "SELECT EXTRACT(EPOCH FROM (permit_expires_at - clock_timestamp())) "
                "FROM geocoding_attempts WHERE auth_user_id = %s "
                "AND permit_expires_at > clock_timestamp() "
                "ORDER BY permit_expires_at LIMIT 1",
                (auth_user_id,),
            ).fetchone()
            if active_user:
                raise GeocodingAdmissionError(
                    "GEOCODING_USER_BUSY", 429, float(active_user[0])
                )

            recent = conn.execute(
                "SELECT count(*), EXTRACT(EPOCH FROM "
                "(MIN(admitted_at) + INTERVAL '10 minutes' - clock_timestamp())) "
                "FROM geocoding_attempts WHERE auth_user_id = %s "
                "AND admitted_at > clock_timestamp() - INTERVAL '10 minutes'",
                (auth_user_id,),
            ).fetchone()
            if recent[0] >= 10:
                raise GeocodingAdmissionError(
                    "GEOCODING_RATE_LIMITED", 429, float(recent[1])
                )

            active_global = conn.execute(
                "SELECT count(*), EXTRACT(EPOCH FROM "
                "(MIN(permit_expires_at) - clock_timestamp())) "
                "FROM geocoding_attempts "
                "WHERE permit_expires_at > clock_timestamp()"
            ).fetchone()
            if active_global[0] >= policy[0]:
                raise GeocodingAdmissionError(
                    "GEOCODING_CAPACITY_FULL", 503, float(active_global[1])
                )

            conn.execute(
                "INSERT INTO geocoding_attempts "
                "(attempt_id, auth_user_id, capacity_pool, admitted_at, permit_expires_at) "
                "VALUES (%s, %s, 'google-geocoding', clock_timestamp(), "
                "clock_timestamp() + (%s * INTERVAL '1 second'))",
                (attempt_id, auth_user_id, PERMIT_SECONDS),
            )
    return attempt_id


def finish(attempt_id, uncertain=False):
    with pool.connection() as conn:
        if uncertain:
            conn.execute(
                "UPDATE geocoding_attempts SET permit_expires_at = "
                "GREATEST(permit_expires_at, clock_timestamp() + (%s * INTERVAL '1 second')) "
                "WHERE attempt_id = %s AND permit_expires_at IS NOT NULL",
                (UNCERTAIN_SECONDS, attempt_id),
            )
        else:
            conn.execute(
                "UPDATE geocoding_attempts SET permit_expires_at = NULL "
                "WHERE attempt_id = %s",
                (attempt_id,),
            )


def geocode_with_capacity(auth_user_id, geocode, **kwargs):
    attempt_id = acquire(auth_user_id)
    completed = False
    try:
        result = geocode(**kwargs)
        completed = True
        return result
    finally:
        finish(attempt_id, uncertain=not completed)
