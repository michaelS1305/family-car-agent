"""Vehicle-owned outbox writes. No network I/O and no change to admission results.

An isolated write failure can permanently lose a notification. This intentionally
favours vehicle availability, NOT guaranteed delivery. Transaction/connection
failures and failures to recover the savepoint always propagate.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging
import os
from threading import Event
from uuid import uuid4

import psycopg
from psycopg.pq import TransactionStatus

log = logging.getLogger(__name__)
wakeup = Event()
_committed_work = ContextVar('native_push_committed_work', default=None)


def enabled():
    return os.getenv('NATIVE_PUSH_ENABLED', '').lower() == 'true'


@contextmanager
def commit_boundary():
    """Wrap OUTSIDE pool.connection(); its exit must commit before this exits.

    On any outer exception (including COMMIT), discard the signal. This is only
    a latency hint; durable polling recovers work after process termination.
    """
    work = []
    token = _committed_work.set(work)
    try:
        yield
    except BaseException:
        raise
    else:
        if work:
            wakeup.set()
    finally:
        _committed_work.reset(token)


def _raw_connection(conn):
    while hasattr(conn, 'conn'):
        conn = conn.conn
    return conn


def produce(conn, source_event_id, *, fast, transition):
    if not enabled() or not fast or transition not in ('opened', 'returned'):
        return False
    event_type = 'vehicle_taken' if transition == 'opened' else 'vehicle_returned'
    try:
        # psycopg creates a SAVEPOINT inside the authoritative transaction.
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO native_push_events (event_ref,source_event_id,family_id,actor_user_id,"
                "vehicle_id,event_type,occurred_at,expires_at,status) "
                "SELECT %s,event_id,family_id,user_id,vehicle_id,%s,occurred_at,"
                "occurred_at+interval '5 minutes','pending' FROM vehicle_events "
                "WHERE event_id=%s AND admission_outcome='accepted' "
                "AND event_type=%s AND occurred_at<=clock_timestamp() "
                "AND occurred_at+interval '5 minutes'>clock_timestamp() "
                "ON CONFLICT (source_event_id,event_type) DO NOTHING RETURNING event_ref",
                (uuid4(), event_type, source_event_id, 'take' if transition == 'opened' else 'return'),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "INSERT INTO native_push_deliveries (delivery_ref,event_ref,installation_ref,"
                "recipient_user_id,installation_generation,status,created_at,updated_at,next_attempt_at) "
                "SELECT gen_random_uuid(),e.event_ref,i.installation_ref,i.user_id,i.generation,"
                "'pending',statement_timestamp(),statement_timestamp(),statement_timestamp() "
                "FROM native_push_installations i "
                "JOIN users u ON u.id=i.user_id JOIN native_push_events e ON e.event_ref=%s "
                "WHERE u.family_id=e.family_id AND u.id<>e.actor_user_id AND i.status='active' "
                "AND u.auth_user_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM account_deletion_jobs j WHERE j.auth_user_id=u.auth_user_id)",
                (row[0],),
            )
    except psycopg.Error as error:
        # Deliberately narrow: only statement-local data/integrity errors, missing
        # optional push objects/privileges, or a statement-local lock/timeout.
        # Never suppress class 08/40/57, unknown errors, or failed SAVEPOINT recovery.
        code = error.sqlstate or ''
        recoverable = code[:2] in ('22', '23') or code in ('42P01', '42703', '42501', '55P03', '57014')
        raw = _raw_connection(conn)
        if not recoverable or raw.closed or raw.info.transaction_status != TransactionStatus.INTRANS:
            raise
        log.error('native_push_outbox_write_failed', extra={
            'operation': 'native_push_outbox', 'sqlstate': code,
            'notification_may_be_lost': True,
        })
        return False
    work = _committed_work.get()
    if work is not None:
        work.append(True)
    return True
