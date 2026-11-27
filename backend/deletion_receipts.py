"""Read-only, operation-scoped capability; never accepted by normal JWT authentication."""
import base64
import hashlib
import hmac
import os
import re
import threading
import time
from uuid import UUID

from deletion_gate import lock_identity

class Rejected(Exception):
    pass

class Unavailable(Exception):
    pass


def enabled():
    return os.environ.get('DELETION_RECEIPTS_ENABLED') == 'true'


def credential(operation, secret):
    # Do not attach rejected input or parser exceptions to public errors.
    if not isinstance(operation, str) or not isinstance(secret, str):
        raise Rejected() from None
    try:
        op = UUID(operation)
        if str(op) != operation or op.version != 4 or not re.fullmatch(r'[A-Za-z0-9_-]{43}', secret):
            raise ValueError()
        raw = base64.urlsafe_b64decode(secret + '=')
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip('=') != secret:
            raise ValueError()
    except (ValueError, TypeError):
        raise Rejected() from None
    return op, hashlib.sha256(b'fca-deletion-status-v1\0' + op.bytes + raw).digest()


class Limiter:
    """Bounded process-wide admission, no attacker-selected keys or personal data.
    Capacity is per worker; deployments must retain ingress rate limits as well.
    """
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.tokens = 30.0
        self.last = clock()

    def allow(self):
        with self.lock:
            now = self.clock()
            self.tokens = min(30., self.tokens + max(0., now-self.last)*5.)
            self.last = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True

limiter = Limiter()


def initiate(pool, owner, operation, secret):
    if not enabled():
        raise Unavailable()
    op, digest = credential(operation, secret)
    with pool.connection() as conn:
        lock_identity(conn, owner, exclusive=True)
        # Serialize operation-ID collisions across different owners too.
        conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', (1178686280, int.from_bytes(op.bytes[:4], 'big', signed=True)))
        existing = conn.execute('SELECT credential_digest,job_ref,state FROM account_deletion_receipts WHERE operation_id=%s FOR UPDATE', (op,)).fetchone()
        if existing:
            job = conn.execute('SELECT job_ref FROM account_deletion_jobs WHERE auth_user_id=%s', (owner,)).fetchone()
            if not hmac.compare_digest(bytes(existing[0]), digest) or not job or job[0] != existing[1]:
                raise Rejected()
            return {'status': 'pending', 'operation_id': str(op)}
        # Never manufacture a receipt from absence or adopt a legacy/in-progress job.
        if not conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (owner,)).fetchone():
            raise Rejected()
        if conn.execute('SELECT 1 FROM account_deletion_jobs WHERE auth_user_id=%s', (owner,)).fetchone():
            raise Rejected()
        job = conn.execute('INSERT INTO account_deletion_jobs(auth_user_id) VALUES(%s) RETURNING job_ref', (owner,)).fetchone()[0]
        conn.execute('INSERT INTO account_deletion_receipts(operation_id,credential_digest,job_ref) VALUES(%s,%s,%s)', (op,digest,job))
        return {'status': 'pending', 'operation_id': str(op)}


def lookup(pool, operation, secret):
    op, digest = credential(operation, secret)
    with pool.connection() as conn:
        row = conn.execute("SELECT credential_digest,state,completed_at,expires_at FROM account_deletion_receipts WHERE operation_id=%s AND (expires_at IS NULL OR expires_at>clock_timestamp())", (op,)).fetchone()
    # Perform a comparison on misses as well; no account lookup is performed.
    matches = hmac.compare_digest(bytes(row[0]) if row else bytes(32), digest)
    if not row or not matches:
        raise Rejected()
    result = {'operation_id': str(op), 'status': row[1]}
    if row[1] == 'completed':
        result.update(completed_at=row[2].isoformat(), expires_at=row[3].isoformat())
    return result


def finalize(conn, job):
    # Called INSIDE the existing finalization transaction, after all authority checks.
    # No-op for legacy jobs; errors must roll back the entire finalization.
    conn.execute("""WITH stamp AS (SELECT clock_timestamp() AS t)
        UPDATE account_deletion_receipts SET state='completed',job_ref=NULL,
        completed_at=stamp.t,expires_at=stamp.t+interval '4320 hours'
        FROM stamp WHERE job_ref=%s AND state='pending'""", (job,))


def expire(pool):
    with pool.connection() as conn:
        conn.execute("""DELETE FROM account_deletion_receipts WHERE operation_id IN
          (SELECT operation_id FROM account_deletion_receipts
           WHERE state='completed' AND expires_at<=clock_timestamp()
           ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)""")
