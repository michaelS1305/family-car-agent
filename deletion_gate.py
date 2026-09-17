"""Transaction-scoped identity fencing; no network calls or process-local state."""
import hashlib
from uuid import UUID


class IdentityUnavailable(Exception):
    """A verified JWT is not sufficient for an absent/deleting Auth identity."""


def lock_identity(conn, auth_user_id, *, exclusive=False):
    # Negative bigint key space; existing one-key operation locks are positive.
    # PostgreSQL's two-int advisory namespace is disjoint as well.
    identity = str(UUID(str(auth_user_id)))
    key = -1 - (int.from_bytes(hashlib.sha256(('fca-deletion:' + identity).encode()).digest()[:8],
                              'big') & ((1 << 63) - 1))
    function = 'pg_advisory_xact_lock' if exclusive else 'pg_advisory_xact_lock_shared'
    conn.execute(f'SELECT {function}(%s)', (key,))


def require_auth(conn, auth_user_id):
    lock_identity(conn, auth_user_id)
    row = conn.execute(
        """SELECT EXISTS(SELECT 1 FROM auth.users WHERE id = %s),
                  EXISTS(SELECT 1 FROM account_deletion_jobs WHERE auth_user_id = %s)""",
        (auth_user_id, auth_user_id),
    ).fetchone()
    if not row or not row[0] or row[1]:
        raise IdentityUnavailable()


def require_user(conn, user_id):
    row = conn.execute('SELECT auth_user_id FROM users WHERE id = %s', (user_id,)).fetchone()
    if not row or row[0] is None:
        raise IdentityUnavailable()
    require_auth(conn, row[0])
    # Mapping may have disappeared while acquiring the identity lock.
    if not conn.execute('SELECT 1 FROM users WHERE id = %s AND auth_user_id = %s',
                        (user_id, row[0])).fetchone():
        raise IdentityUnavailable()


def require_request(conn, request_id):
    row = conn.execute('SELECT user_id FROM chat_requests WHERE id = %s', (request_id,)).fetchone()
    if not row:
        raise IdentityUnavailable()
    require_user(conn, row[0])
