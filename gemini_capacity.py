"""Backend-only PostgreSQL permits. No connection spans a provider invocation."""
import logging
import time
from uuid import uuid4


logger = logging.getLogger(__name__)
ATTEMPT_SECONDS = 75
FINALIZATION_RESERVE_SECONDS = 5
UNCERTAINTY_SECONDS = 45


class CapacityUnavailable(Exception):
    pass


class AttemptExpired(Exception):
    pass


def acquire(pool, request_id, token):
    permit_id = str(uuid4())
    with pool.connection() as conn:
        with conn.transaction():
            # All acquisitions use the same lock order: policy, then request.
            policy = conn.execute(
                "SELECT max_concurrency FROM gemini_capacity_policies "
                "WHERE capacity_pool = 'gemini-default' FOR UPDATE"
            ).fetchone()
            if not policy:
                raise CapacityUnavailable()
            request = conn.execute(
                "SELECT EXTRACT(EPOCH FROM (lease_expires_at - INTERVAL '45 seconds' "
                "- clock_timestamp())) FROM chat_requests "
                "WHERE id = %s AND lease_token = %s AND status = 'processing' FOR UPDATE",
                (request_id, token),
            ).fetchone()
            if not request or float(request[0]) <= FINALIZATION_RESERVE_SECONDS:
                raise AttemptExpired()
            # Bounded cleanup; expired rows do not count even if not yet deleted.
            conn.execute(
                "DELETE FROM gemini_call_permits WHERE permit_id IN "
                "(SELECT permit_id FROM gemini_call_permits "
                "WHERE expires_at <= clock_timestamp() ORDER BY expires_at LIMIT 100) "
                "AND expires_at <= clock_timestamp()"
            )
            conn.execute(
                "DELETE FROM gemini_call_permits WHERE chat_request_id = %s "
                "AND expires_at <= clock_timestamp()", (request_id,),
            )
            occupied = conn.execute(
                "SELECT count(*), COALESCE(bool_or(chat_request_id = %s), false) "
                "FROM gemini_call_permits WHERE capacity_pool = 'gemini-default' "
                "AND expires_at > clock_timestamp()", (request_id,),
            ).fetchone()
            if occupied[0] >= policy[0] or occupied[1]:
                raise CapacityUnavailable()
            conn.execute(
                "INSERT INTO gemini_call_permits "
                "(permit_id, chat_request_id, attempt_token, capacity_pool, acquired_at, expires_at) "
                "SELECT %s, id, %s, 'gemini-default', clock_timestamp(), lease_expires_at "
                "FROM chat_requests WHERE id = %s", (permit_id, token, request_id),
            )
    return permit_id, float(request[0])


def finish(pool, permit_id, token, uncertain=False):
    with pool.connection() as conn:
        if uncertain:
            conn.execute(
                "UPDATE gemini_call_permits SET expires_at = GREATEST(expires_at, "
                "clock_timestamp() + INTERVAL '45 seconds') "
                "WHERE permit_id = %s AND attempt_token = %s", (permit_id, token),
            )
        else:
            conn.execute(
                "DELETE FROM gemini_call_permits WHERE permit_id = %s AND attempt_token = %s",
                (permit_id, token),
            )


class ProviderCalls:
    def __init__(self, pool, request_id, token, public_request_id, started):
        self.pool, self.request_id, self.token = pool, request_id, token
        self.public_request_id = public_request_id
        self.deadline = started + ATTEMPT_SECONDS

    def __call__(self, generate, **kwargs):
        if self.deadline - time.monotonic() <= FINALIZATION_RESERVE_SECONDS:
            raise AttemptExpired()
        permit_id, db_remaining = acquire(self.pool, self.request_id, self.token)
        remaining = min(db_remaining, self.deadline - time.monotonic())
        if remaining <= FINALIZATION_RESERVE_SECONDS:
            finish(self.pool, permit_id, self.token)
            raise AttemptExpired()
        config = dict(kwargs.get('config') or {})
        config['http_options'] = {
            'timeout': int(min(30, remaining - FINALIZATION_RESERVE_SECONDS) * 1000),
            'retry_options': {'attempts': 1},
        }
        kwargs['config'] = config
        started = time.monotonic()
        outcome = 'uncertain'
        try:
            response = generate(**kwargs)
            outcome = 'completed'
            return response
        except Exception as error:
            # HTTP error response is definite; unknown transport/SDK failures are not.
            if type(error).__module__.startswith('google.genai.errors') and isinstance(getattr(error, 'code', None), int):
                outcome = 'provider_error'
            raise
        finally:
            logger.info(
                'operation=gemini_call request_id=%s latency_ms=%d outcome=%s',
                self.public_request_id, int((time.monotonic() - started) * 1000), outcome,
            )
            finish(self.pool, permit_id, self.token, uncertain=outcome == 'uncertain')
