"""Durable hard deletion. All application cleanup commits before Auth HTTP I/O."""
import logging
import os
from urllib.parse import urlsplit
from uuid import UUID

import requests

from deletion_gate import lock_identity


logger = logging.getLogger(__name__)
RETRY_SECONDS = 60
PASS_LIMIT = 10
FAMILY_LOCK = 1178686273
CAR_LOCK = 1178686275
RESERVATION_LOCK = 1178686274


def _log(stage):
    # Only internal constant categories, never identities, payloads or exceptions.
    try:
        logger.warning('operation=account_deletion stage=%s', stage)
    except Exception:
        pass


def status(pool, auth_user_id):
    with pool.connection() as conn:
        job = conn.execute('SELECT phase FROM account_deletion_jobs WHERE auth_user_id=%s',
                           (auth_user_id,)).fetchone()
        if job:
            return {'status': job[0]}
        exists = conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (auth_user_id,)).fetchone()
        return {'status': 'not_requested' if exists else 'completed'}


def preview(pool, auth_user_id):
    with pool.connection() as conn:
        from deletion_gate import require_auth
        require_auth(conn, auth_user_id)
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (FAMILY_LOCK,))
        user = conn.execute('SELECT id,family_id FROM users WHERE auth_user_id=%s',
                            (auth_user_id,)).fetchone()
        consequence = 'personal'
        if user and user[1] is not None:
            family = conn.execute('SELECT created_by_user_id FROM families WHERE id=%s',
                                  (user[1],)).fetchone()
            other = conn.execute('SELECT 1 FROM users WHERE family_id=%s AND id<>%s LIMIT 1',
                                 (user[1], user[0])).fetchone()
            if not other:
                consequence = 'family_deleted'
            elif family and family[0] == user[0]:
                consequence = 'management_transferred'
        return {'consequence': consequence}


def confirm(pool, auth_user_id):
    with pool.connection() as conn:
        lock_identity(conn, auth_user_id, exclusive=True)
        job = conn.execute('SELECT phase FROM account_deletion_jobs WHERE auth_user_id=%s',
                           (auth_user_id,)).fetchone()
        if job:
            return {'status': job[0]}
        if not conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (auth_user_id,)).fetchone():
            return {'status': 'completed'}
        conn.execute('INSERT INTO account_deletion_jobs (auth_user_id) VALUES (%s)', (auth_user_id,))
    return {'status': 'draining'}


def _drained(conn, auth_user_id, user_id, family_id, last_member):
    # Lock before testing expiry: a concurrent uncertain finish can extend a
    # previously expired lease. Its committed extension must be seen, not erased.
    conn.execute('SELECT attempt_id FROM geocoding_attempts WHERE auth_user_id=%s ORDER BY attempt_id FOR UPDATE',
                 (auth_user_id,)).fetchall()
    if conn.execute('''SELECT 1 FROM geocoding_attempts
                       WHERE auth_user_id=%s AND permit_expires_at>clock_timestamp() LIMIT 1''',
                    (auth_user_id,)).fetchone():
        return False
    if user_id is None:
        return True
    conn.execute('''SELECT p.permit_id FROM gemini_call_permits p
        JOIN chat_requests cr ON cr.id=p.chat_request_id
        WHERE cr.user_id=%s OR (%s AND cr.family_id=%s)
        ORDER BY p.permit_id FOR UPDATE OF p''', (user_id,last_member,family_id)).fetchall()
    return not conn.execute('''SELECT 1 FROM gemini_call_permits p
        JOIN chat_requests cr ON cr.id=p.chat_request_id
        WHERE (cr.user_id=%s OR (%s AND cr.family_id=%s))
          AND p.expires_at>clock_timestamp() LIMIT 1''',
        (user_id, last_member, family_id)).fetchone()


def cleanup(pool, auth_user_id):
    from database import _get_active_driver_on_connection, _insert_car_event_on_connection
    with pool.connection() as conn:
        # Confirmation and all normal mutations acquire identity before operation locks.
        conn.execute("SET LOCAL lock_timeout='3s'")
        conn.execute("SET LOCAL statement_timeout='10s'")
        lock_identity(conn, auth_user_id, exclusive=True)
        job = conn.execute('SELECT phase FROM account_deletion_jobs WHERE auth_user_id=%s FOR UPDATE',
                           (auth_user_id,)).fetchone()
        if not job or job[0] != 'draining':
            return bool(job and job[0] == 'auth_pending')
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (FAMILY_LOCK,))
        user = conn.execute('SELECT id,family_id FROM users WHERE auth_user_id=%s',
                            (auth_user_id,)).fetchone()
        user_id, family_id = user if user else (None, None)
        # Chat admission and CarPlay share a namespace: deduplicate and sort.
        for key in sorted({key for key in (user_id, family_id) if key is not None}):
            conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', (CAR_LOCK, key))
        family = None
        successor = None
        if family_id is not None:
            family = conn.execute('SELECT created_by_user_id FROM families WHERE id=%s FOR UPDATE',
                                  (family_id,)).fetchone()
            successor = conn.execute('SELECT id FROM users WHERE family_id=%s AND id<>%s ORDER BY id LIMIT 1',
                                     (family_id, user_id)).fetchone()
        last_member = family is not None and successor is None
        if not _drained(conn, auth_user_id, user_id, family_id, last_member):
            return False
        if user_id is not None:
            # Request -> reservation-family order matches Chat tool mutations.
            requests_ = conn.execute('''SELECT id FROM chat_requests
                WHERE user_id=%s OR (%s AND family_id=%s) ORDER BY id FOR UPDATE''',
                (user_id, last_member, family_id)).fetchall()
            if family_id is not None:
                conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', (RESERVATION_LOCK, family_id))
            ids = [row[0] for row in requests_]
            conn.execute('DELETE FROM gemini_call_permits WHERE chat_request_id=ANY(%s)', (ids,))
            conn.execute('DELETE FROM chat_tool_actions WHERE chat_request_id=ANY(%s)', (ids,))
            conn.execute('DELETE FROM conversation_messages WHERE chat_request_id=ANY(%s) OR user_id=%s', (ids, user_id))
            conn.execute('DELETE FROM chat_requests WHERE id=ANY(%s)', (ids,))
            conn.execute('DELETE FROM reservations WHERE user_id=%s', (user_id,))
            _checkpoint_vehicle_identity(conn, user_id, family_id)
            active = _get_active_driver_on_connection(conn, family_id) if family_id is not None else None
            # Non-personal logical barrier. NOT a disconnected/physical-return event.
            # It closes all prior reconstructed active state without deleting or
            # claiming attribution of any legacy null-user event.
            if not last_member and active and active[1] == user_id:
                _insert_car_event_on_connection(conn, None, '', 'state_reset', family_id)
            conn.execute('DELETE FROM car_events WHERE user_id=%s OR (%s AND family_id=%s)',
                         (user_id, last_member, family_id))
            conn.execute('DELETE FROM push_subscriptions WHERE user_id=%s', (user_id,))
            conn.execute('DELETE FROM carplay_transition_admissions WHERE user_id=%s OR (%s AND family_id=%s)',
                         (user_id, last_member, family_id))
        conn.execute('DELETE FROM pwa_join_sessions WHERE auth_user_id=%s OR (%s AND family_id=%s)',
                     (auth_user_id, last_member, family_id))
        conn.execute('DELETE FROM family_address_confirmations WHERE auth_user_id=%s OR user_id=%s OR (%s AND family_id=%s)',
                     (auth_user_id, user_id, last_member, family_id))
        conn.execute('DELETE FROM geocoding_attempts WHERE auth_user_id=%s', (auth_user_id,))
        if last_member:
            conn.execute('UPDATE users SET family_id=NULL WHERE id=%s', (user_id,))
            conn.execute('DELETE FROM families WHERE id=%s', (family_id,))
        elif family and family[0] == user_id:
            conn.execute('UPDATE families SET created_by_user_id=%s WHERE id=%s', (successor[0], family_id))
        if user_id is not None:
            conn.execute('DELETE FROM users WHERE id=%s', (user_id,))
        conn.execute("UPDATE account_deletion_jobs SET phase='auth_pending' WHERE auth_user_id=%s AND phase='draining'",
                     (auth_user_id,))
    return True


def _checkpoint_vehicle_identity(conn, user_id, family_id):
    """Caller holds identity -> job -> global family -> sorted car/chat ->
    family row -> provider/request -> reservation locks, in that order.
    No other identity lock or network call is acquired here. All changes share
    cleanup's transaction and its one-way auth_pending phase transition.
    """
    if family_id is not None:
        generation = conn.execute(
            "UPDATE families SET vehicle_reconciliation_generation=vehicle_reconciliation_generation+1, "
            "vehicle_finalized_through=GREATEST(vehicle_finalized_through,clock_timestamp(),"
            "(SELECT MAX(occurred_at) FROM vehicle_events WHERE family_id=%s "
            "AND admission_outcome='accepted')) WHERE id=%s "
            "RETURNING vehicle_reconciliation_generation",
            (family_id, family_id),
        ).fetchone()[0]
        # Enclose even pre-guard future evidence. Only currently open surviving
        # sessions carry state into the new suffix; ended rows remain history.
        conn.execute(
            "UPDATE vehicle_driver_sessions SET checkpoint_generation=%s "
            "WHERE family_id=%s AND user_id<>%s AND ended_at IS NULL",
            (generation, family_id, user_id),
        )
    # End-event references on survivors become NULL through the existing FK;
    # their ended_at/reason survive. Projection anchors are same-user FKs.
    conn.execute('DELETE FROM vehicle_driver_sessions WHERE user_id=%s', (user_id,))
    conn.execute('DELETE FROM vehicle_events WHERE user_id=%s', (user_id,))
    conn.execute('DELETE FROM registered_devices WHERE user_id=%s', (user_id,))


def delete_auth_identity(auth_user_id):
    """Best-effort HTTP request; ONLY a subsequent DB absence check completes a job.

    This also covers a lost success response and rejects arbitrary proxy 404s.
    """
    identity = str(UUID(str(auth_user_id)))
    url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    parsed = urlsplit(url)
    if not key or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        _log('auth_configuration_error')
        return
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.delete(f'{url}/auth/v1/admin/users/{identity}',
                headers={'Authorization': f'Bearer {key}', 'apikey': key},
                json={'should_soft_delete': False}, timeout=(5, 10), allow_redirects=False)
            if response.status_code not in (200, 204, 404):
                _log('auth_delete_rejected')
    except requests.RequestException:
        _log('auth_transport_error')


def recover_one(pool, auth_user_id):
    if not cleanup(pool, auth_user_id):
        return
    with pool.connection() as conn:
        exists = conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (auth_user_id,)).fetchone()
    if exists:
        delete_auth_identity(auth_user_id)  # No DB connection or lock spans HTTP.
    with pool.connection() as conn:
        lock_identity(conn, auth_user_id, exclusive=True)
        conn.execute("""DELETE FROM account_deletion_jobs WHERE auth_user_id=%s AND phase='auth_pending'
                     AND NOT EXISTS(SELECT 1 FROM auth.users WHERE id=%s)""", (auth_user_id, auth_user_id))


def run_due(pool, should_stop=lambda: False):
    # Claim/schedule atomically; do not hold row locks while taking identity locks.
    # Duplicate workers after claim expiry are harmless: phases only advance and
    # every cleanup is serialized. Auth DELETE is idempotent; DB absence is final.
    with pool.connection() as conn:
        jobs = conn.execute('''WITH due AS (
            SELECT auth_user_id FROM account_deletion_jobs
            WHERE next_attempt_at<=clock_timestamp() ORDER BY next_attempt_at,auth_user_id
            LIMIT %s FOR UPDATE SKIP LOCKED)
            UPDATE account_deletion_jobs j SET next_attempt_at=clock_timestamp()+(%s*INTERVAL '1 second')
            FROM due WHERE j.auth_user_id=due.auth_user_id RETURNING j.auth_user_id''',
            (PASS_LIMIT, RETRY_SECONDS)).fetchall()
    for (identity,) in jobs:
        if should_stop():
            break
        try:
            recover_one(pool, identity)
        except Exception:
            _log('recovery_retry')
