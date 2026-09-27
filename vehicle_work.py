"""Internal conservative safety defaults, pending production-like load testing.

Not enrollment/rate limits. These cap one serialized admission's planning and
materialization. Database timeouts are additional defense, not work accounting.
"""
from dataclasses import dataclass
from datetime import timedelta
import time


CORRECTION_HOURS = 72
LOCK_TIMEOUT = '1000ms'
STATEMENT_TIMEOUT = '2000ms'
ADMISSION_SECONDS = 5


class AdmissionDeadlineExceeded(TimeoutError):
    """Transient local deadline; transaction must roll back, never consume."""


class DeadlineConnection:
    def __init__(self, conn):
        self.conn = conn
        self.deadline = time.monotonic() + ADMISSION_SECONDS

    def transaction(self):
        return self.conn.transaction()

    def execute(self, query, params=None):
        self.check()
        return self.conn.execute(query, params)

    def check(self):
        if time.monotonic() >= self.deadline:
            raise AdmissionDeadlineExceeded()


@dataclass(frozen=True)
class WorkLimits:
    events: int = 512
    seeds: int = 128
    sessions: int = 512
    causes: int = 128
    inserts: int = 512
    updates: int = 512
    deletes: int = 512
    associations: int = 512
    checkpoint: int = 512
    sql: int = 2048
    total: int = 4096


DEFAULT_LIMITS = WorkLimits()


class PolicyExceeded(Exception):
    """Only deterministic work accounting raises this; never DB failures."""


class Budget:
    def __init__(self, limits=None):
        self.limits = limits or DEFAULT_LIMITS
        self.used = {}
        self.total = 0

    def charge(self, dimension, count):
        used = self.used.get(dimension, 0) + count
        if used > getattr(self.limits, dimension) or self.total + count > self.limits.total:
            raise PolicyExceeded()
        self.used[dimension] = used
        self.total += count

    def remaining(self, dimension):
        return min(getattr(self.limits, dimension) - self.used.get(dimension, 0),
                   self.limits.total - self.total)

    def rows(self, conn, query, params, dimension):
        # Caller supplies an indexed predicate/order, never a post-LIMIT filter.
        maximum = self.remaining(dimension)
        self.charge('sql', 1)
        rows = conn.execute(query + ' LIMIT %s', (*params, maximum + 1)).fetchall()
        self.charge(dimension, len(rows))
        return rows

    def one(self, conn, query, params):
        self.charge('sql', 1)
        return conn.execute(query, params).fetchone()


SESSION_COLUMNS = ('id,session_ref,vehicle_id,user_id,started_at,start_event_id,'
                   'ended_at,end_event_id,end_reason,created_at,checkpoint_generation')


def rolling_checkpoint(conn, family_id, generation, boundary, target, budget, *, maintenance=False):
    if boundary is not None and target <= boundary:
        return generation, boundary
    candidates = []
    if boundary is not None:
        candidates = budget.rows(conn,
            f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
            'WHERE family_id=%s AND checkpoint_generation=%s',
            (family_id, generation), 'checkpoint')
    predicate = '' if boundary is None else ' AND started_at>%s'
    params = (family_id, target) if boundary is None else (family_id, target, boundary)
    query = (f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
             'WHERE family_id=%s AND started_at<=%s' + predicate + ' ORDER BY started_at,id')
    if maintenance:
        # One explicit maintenance unit may install a complete earlier boundary.
        # Never split a timestamp group; no admission uses this partial target as
        # permission to widen its independent 72-hour eligibility cutoff.
        maximum = budget.remaining('checkpoint')
        budget.charge('sql', 1)
        rows = conn.execute(query + ' LIMIT %s', (*params, maximum + 1)).fetchall()
        if len(rows) > maximum:
            target = rows[-1][4] - timedelta(microseconds=1)
            if boundary is not None and target <= boundary:
                raise PolicyExceeded()
            rows = [row for row in rows if row[4] <= target]
        budget.charge('checkpoint', len(rows))
        candidates += rows
    else:
        candidates += budget.rows(conn, query, params, 'checkpoint')
    # Filter only the already bounded old seeds/new starts, NOT all history.
    carried = [row[0] for row in candidates if row[4] <= target and (row[6] is None or row[6] > target)]
    budget.charge('seeds', len(carried))
    budget.charge('updates', len(carried))
    budget.charge('sql', 2)
    conn.execute('UPDATE families SET vehicle_finalized_through=%s, '
                 'vehicle_reconciliation_generation=vehicle_reconciliation_generation+1 WHERE id=%s',
                 (target, family_id))
    conn.execute('UPDATE vehicle_driver_sessions SET checkpoint_generation=%s '
                 'WHERE family_id=%s AND id=ANY(%s)', (generation + 1, family_id, carried))
    return generation + 1, target
