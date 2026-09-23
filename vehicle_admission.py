"""INTERNAL ONLY: native evidence admission. No pool, route or runtime caller.

Lock order: shared deletion identity fence -> existing family car advisory lock
-> family row -> owned device row -> target vehicle row. Never fence another
member while holding family locks. Retirement/checkpoint writers must share the
family serialization contract, also used by account deletion checkpoints.
Call on a caller-owned connection; an outer transaction, if present,
owns the final commit. Exceptions roll back this operation's transaction/savepoint.
"""
from dataclasses import dataclass, replace
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID

from deletion_gate import IdentityUnavailable, require_auth
from identity import CurrentUser
from vehicle_reconciliation import (
    AcceptedEvent, CheckpointSeed, CheckpointSession, ReconciliationError,
    SessionKey, TakeAssociation, reconcile,
)
from vehicle_work import (Budget, PolicyExceeded, SESSION_COLUMNS, rolling_checkpoint,
                          CORRECTION_HOURS, LOCK_TIMEOUT, STATEMENT_TIMEOUT, DeadlineConnection)


CAR_TRANSITION_LOCK_NAMESPACE = 1178686275


@dataclass(frozen=True)
class NativeEvent:
    event_id: UUID
    device_ref: UUID
    vehicle_ref: UUID
    event_type: Literal["take", "return"]
    occurred_at: datetime
    device_sequence: int
    take_event_id: UUID | None = None


@dataclass(frozen=True)
class AdmissionResult:
    kind: Literal["accepted", "retry", "terminal", "gap", "conflict", "unavailable", "malformed", "future_clock_skew"]
    admission_outcome: str | None = None


def _envelope(event):
    if not isinstance(event, NativeEvent):
        return None
    if not all(isinstance(value, UUID) for value in (event.event_id, event.device_ref, event.vehicle_ref)):
        return None
    if type(event.device_sequence) is not int or not 0 < event.device_sequence <= 9223372036854775807:
        return None
    if event.event_type not in ("take", "return"):
        return None
    if event.event_type == "take" and event.take_event_id is not None:
        return None
    if event.event_type == "return" and (
        not isinstance(event.take_event_id, UUID) or event.take_event_id == event.event_id
    ):
        return None
    try:
        if not isinstance(event.occurred_at, datetime) or event.occurred_at.utcoffset() is None:
            return None
        return replace(event, occurred_at=event.occurred_at.astimezone(timezone.utc))
    except (ValueError, OverflowError):
        return None


def _cause(conn, event, budget):
    cause = budget.one(conn,
        "SELECT occurred_at,projection_take_event_id FROM vehicle_events "
        "WHERE event_id=%s AND user_id=%s AND vehicle_id=%s AND family_id=%s "
        "AND event_type='take' AND admission_outcome='accepted' AND occurred_at<=%s",
        (event.take_event_id, event.user_id, event.vehicle_id, event.family_id, event.occurred_at))
    if not cause:
        return None
    session = budget.one(conn,
        f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
        'WHERE start_event_id=%s AND user_id=%s AND vehicle_id=%s AND family_id=%s',
        (cause[1], event.user_id, event.vehicle_id, event.family_id))
    if not session:
        raise ReconciliationError('Accepted TAKE lacks retained session anchor')
    return cause, session


def _load_replay(conn, family_id, generation, boundary, candidate, budget):
    budget.charge('events', 1)
    rows = budget.rows(conn,
        "SELECT event_id,family_id,vehicle_id,user_id,event_type,occurred_at,source,"
        "device_id,device_sequence,take_event_id FROM vehicle_events "
        "WHERE family_id=%s AND admission_outcome='accepted' AND occurred_at>%s "
        'ORDER BY occurred_at,event_id', (family_id, boundary), 'events')
    events = [AcceptedEvent(*row) for row in rows] + [candidate]
    seeds = budget.rows(conn,
        f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
        'WHERE family_id=%s AND checkpoint_generation=%s', (family_id, generation), 'seeds')
    suffix = budget.rows(conn,
        f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
        'WHERE family_id=%s AND started_at>%s ORDER BY started_at,id',
        (family_id, boundary), 'sessions')
    budget.charge('sessions', len(seeds))
    mutable, carried, anchors = {}, [], {}
    for row in seeds:
        if row[4] > boundary or (row[6] is not None and row[6] <= boundary):
            raise ReconciliationError('Invalid checkpoint seed')
        key = SessionKey('checkpoint', row[1])
        mutable[key] = row
        carried.append(CheckpointSession(row[1], row[2], row[3], row[4], row[5]))
        if row[5] is not None:
            anchors[row[5]] = key
    for row in suffix:
        if row[5] is None:
            raise ReconciliationError('Mutable session lacks start evidence')
        mutable[SessionKey('take', row[5])] = row
    event_ids = {event.event_id for event in events}
    external = {event.take_event_id for event in events
                if event.event_type == 'return' and event.take_event_id not in event_ids}
    budget.charge('causes', len(external))
    resolved, aliases, frozen = {}, {}, {}
    for event in events:
        if event.event_type != 'return' or event.take_event_id not in external:
            continue
        if event.take_event_id not in resolved:
            resolved[event.take_event_id] = _cause(conn, event, budget)
        found = resolved[event.take_event_id]
        if not found:
            raise ReconciliationError('Stored RETURN lacks accepted cause')
        cause, session = found
        if (session[3], session[2]) != (event.user_id, event.vehicle_id) or cause[0] > event.occurred_at:
            raise ReconciliationError('Invalid historical RETURN identity/time')
        if cause[0] > boundary:
            raise ReconciliationError('Replay omitted mutable cause')
        if session[6] is not None and session[6] <= boundary:
            frozen[event.take_event_id] = (cause[1], cause[0], event.user_id, event.vehicle_id)
        elif cause[1] in anchors:
            aliases[event.take_event_id] = TakeAssociation(event.take_event_id, anchors[cause[1]], cause[0])
        else:
            raise ReconciliationError('Historical cause lacks checkpoint seed')
    seed = CheckpointSeed(family_id, boundary, generation, tuple(carried), tuple(aliases.values()))
    events = [event for event in events if _frozen_return_anchor(event, frozen) is None]
    return events, seed, mutable, frozen


def _frozen_return_anchor(event, frozen_causes):
    if event.event_type != "return" or event.take_event_id not in frozen_causes:
        return None
    anchor, occurred_at, user_id, vehicle_id = frozen_causes[event.take_event_id]
    if (event.user_id, event.vehicle_id) != (user_id, vehicle_id) or event.occurred_at < occurred_at:
        raise ReconciliationError("Invalid RETURN against frozen session")
    return anchor


def _plan_materialization(projection, mutable, budget, *, incremental=False):
    """No writes: approve the complete physical write set before mutation."""
    associations = {alias.take_event_id: alias.session_key for alias in projection.take_associations}
    retained = {}
    # Prefer unchanged anchors. A newly arrived earlier TAKE can turn the old
    # opening TAKE into an alias without creating a different logical occupancy.
    # Reuse its public ref too. If replay merges multiple old projections, retain
    # the earliest one deterministically; never reuse one ref for two sessions.
    for key, row in mutable.items():
        desired_key = key if key.kind == "checkpoint" else associations.get(key.ref)
        if desired_key is not None:
            retained.setdefault(desired_key, []).append(row)
    writes, unchanged, reused = [], set(), set()
    for session in projection.sessions:
        previous = mutable.get(session.key)
        if previous is None and retained.get(session.key):
            previous = min(retained[session.key], key=lambda row: (row[4], row[1]))
        if previous and previous[0] in reused:
            raise ReconciliationError('Projection reuses session identity')
        if previous:
            reused.add(previous[0])
            if incremental:
                session = replace(session, checkpoint_generation=previous[10])
            expected = (session.vehicle_id, session.user_id, session.started_at, session.start_event_id,
                        session.ended_at, session.end_event_id, session.end_reason)
            if previous[2:9] == expected and previous[10] == session.checkpoint_generation:
                unchanged.add(previous[0])
                continue
        writes.append((session, previous))
    deletes = [] if incremental else [row[0] for row in mutable.values() if row[0] not in unchanged]
    if incremental and reused != {row[0] for row in mutable.values()}:
        raise ReconciliationError('Incremental projection dropped a session')
    sessions = {session.key: session for session in projection.sessions}
    effects = [(effect.event_id, sessions[effect.session_key].start_event_id
                if effect.session_key is not None else None) for effect in projection.effects]
    budget.charge('deletes', len(deletes))
    budget.charge('updates', sum(previous is not None for _, previous in writes))
    budget.charge('inserts', sum(not incremental or previous is None for _, previous in writes))
    budget.charge('associations', len(effects))
    budget.charge('sql', bool(deletes) + len(writes) + len(effects))
    return deletes, writes, effects, incremental


def _materialize(conn, family_id, plan):
    deletes, writes, effects, incremental = plan
    if deletes:
        conn.execute('DELETE FROM vehicle_driver_sessions WHERE family_id=%s AND id=ANY(%s)',
                     (family_id, deletes))
    # Close existing sessions before opening replacements (immediate active indexes).
    writes = sorted(writes, key=lambda item: item[1] is None) if incremental else writes
    columns = 'family_id,vehicle_id,user_id,started_at,start_event_id,ended_at,end_event_id,end_reason,checkpoint_generation'
    for session, previous in writes:
        if incremental and previous:
            conn.execute('UPDATE vehicle_driver_sessions SET ended_at=%s,end_event_id=%s,end_reason=%s '
                         'WHERE family_id=%s AND id=%s',
                         (session.ended_at, session.end_event_id, session.end_reason, family_id, previous[0]))
            continue
        values = (family_id, session.vehicle_id, session.user_id, session.started_at, session.start_event_id,
                  session.ended_at, session.end_event_id, session.end_reason, session.checkpoint_generation)
        if previous:
            conn.execute(f'INSERT INTO vehicle_driver_sessions (id,session_ref,created_at,{columns}) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (previous[0], previous[1], previous[9], *values))
        else:
            conn.execute(f'INSERT INTO vehicle_driver_sessions ({columns}) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', values)
    for event_id, anchor in effects:
        conn.execute("UPDATE vehicle_events SET projection_take_event_id=%s WHERE family_id=%s "
                     "AND event_id=%s AND admission_outcome='accepted' "
                     'AND projection_take_event_id IS DISTINCT FROM %s', (anchor, family_id, event_id, anchor))


def _incremental(conn, event, latest, budget, cause):
    """Run the SAME pure transition engine on at most two active sessions."""
    if event.event_type == 'return' and cause[1][6] is not None:
        budget.charge('events', 1)
        return None, {}, cause[0][1]
    active = {}
    if event.event_type == 'take':
        for column, value in (('user_id', event.user_id), ('vehicle_id', event.vehicle_id)):
            row = budget.one(conn, f'SELECT {SESSION_COLUMNS} FROM vehicle_driver_sessions '
                             f'WHERE {column}=%s AND family_id=%s AND ended_at IS NULL', (value, event.family_id))
            if row:
                active[row[0]] = row
    else:
        active[cause[1][0]] = cause[1]
    budget.charge('events', 1)
    budget.charge('sessions', len(active))
    budget.charge('seeds', len(active))
    mutable = {SessionKey('checkpoint', row[1]): row for row in active.values()}
    carried = tuple(CheckpointSession(row[1], row[2], row[3], row[4], row[5]) for row in active.values())
    aliases = () if event.event_type == 'take' else (
        TakeAssociation(event.take_event_id, SessionKey('checkpoint', cause[1][1]), cause[0][0]),)
    seed = CheckpointSeed(event.family_id, latest or event.occurred_at - timedelta(microseconds=1),
                          1, carried, aliases)
    return reconcile(event.family_id, [event], seed), mutable, None


class _ReceiptConflict(Exception):
    pass


class _RejectedProjection(Exception):
    def __init__(self, outcome):
        self.outcome = outcome


def admit_native_event(conn, current_user: CurrentUser, request: NativeEvent):
    event = _envelope(request)
    if event is None:
        return AdmissionResult("malformed")
    with _bounded_connection(conn) as bounded:
        return _admit(bounded, current_user, event)


@contextmanager
def _bounded_connection(conn):
    # Settings are restored on success and rolled back with this savepoint on
    # failure, so a caller-owned outer transaction does not inherit our limits.
    with conn.transaction():
        previous = conn.execute("SELECT current_setting('lock_timeout'), current_setting('statement_timeout'), "
                                "(SELECT setting::bigint FROM pg_settings WHERE name='lock_timeout'), "
                                "(SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout')").fetchone()
        # Do not relax a stricter timeout established by the caller.
        lock_ms, statement_ms = int(LOCK_TIMEOUT[:-2]), int(STATEMENT_TIMEOUT[:-2])
        conn.execute("SELECT set_config('lock_timeout',%s,true), set_config('statement_timeout',%s,true)",
                     (f'{min(previous[2] or lock_ms, lock_ms)}ms',
                      f'{min(previous[3] or statement_ms, statement_ms)}ms'))
        bounded = DeadlineConnection(conn)
        yield bounded
        bounded.check()
        conn.execute("SELECT set_config('lock_timeout',%s,true), set_config('statement_timeout',%s,true)", previous[:2])


def maintain_native_checkpoint(conn, current_user: CurrentUser):
    """INTERNAL ONLY: one explicit bounded recovery unit, not a worker/queue.

    Caller may schedule another unit after progress. No event/sequence is changed;
    a dense same-time group or excessive carry state fails closed without looping.
    """
    with _bounded_connection(conn) as bounded:
        try:
            require_auth(bounded, current_user.auth_user_id)
        except IdentityUnavailable:
            return 'unavailable'
        family_id = current_user.family_id
        if family_id is None:
            return 'unavailable'
        bounded.execute('SELECT pg_advisory_xact_lock(%s,%s)', (CAR_TRANSITION_LOCK_NAMESPACE, family_id))
        family = bounded.execute('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families '
                                 'WHERE id=%s FOR UPDATE', (family_id,)).fetchone()
        if not family or not bounded.execute('SELECT 1 FROM users WHERE id=%s AND family_id=%s AND auth_user_id=%s',
                (current_user.user_id, family_id, current_user.auth_user_id)).fetchone():
            return 'unavailable'
        now = bounded.execute('SELECT clock_timestamp()').fetchone()[0]
        target = max(family[1], now - timedelta(hours=CORRECTION_HOURS)) if family[1] else now - timedelta(hours=CORRECTION_HOURS)
        try:
            with bounded.transaction():
                _, installed = rolling_checkpoint(bounded, family_id, *family, target, Budget(), maintenance=True)
        except PolicyExceeded:
            return 'policy_exceeded'
        return 'complete' if installed == target else 'progress'


def _admit(conn, current_user, event):
    with conn.transaction():
        try:
            require_auth(conn, current_user.auth_user_id)
        except IdentityUnavailable:
            return AdmissionResult("unavailable")
        family_id = current_user.family_id
        if family_id is None:
            return AdmissionResult("unavailable")
        conn.execute("SELECT pg_advisory_xact_lock(%s,%s)", (CAR_TRANSITION_LOCK_NAMESPACE, family_id))
        family = conn.execute(
            "SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families "
            "WHERE id=%s FOR UPDATE", (family_id,),
        ).fetchone()
        if not family or not conn.execute(
            "SELECT 1 FROM users WHERE id=%s AND family_id=%s AND auth_user_id=%s",
            (current_user.user_id, family_id, current_user.auth_user_id),
        ).fetchone():
            return AdmissionResult("unavailable")
        device = conn.execute(
            "SELECT id,last_processed_sequence FROM registered_devices "
            "WHERE device_ref=%s AND user_id=%s AND revoked_at IS NULL FOR UPDATE",
            (event.device_ref, current_user.user_id),
        ).fetchone()
        vehicle = conn.execute(
            "SELECT id,retired_at FROM vehicles WHERE vehicle_ref=%s AND family_id=%s FOR SHARE",
            (event.vehicle_ref, family_id),
        ).fetchone()
        if not device or not vehicle:
            return AdmissionResult("unavailable")
        device_id, last_sequence = device
        vehicle_id, retired = vehicle
        evidence = (event.event_id, family_id, vehicle_id, current_user.user_id,
                    device_id, "native", event.event_type, event.occurred_at,
                    event.device_sequence, event.take_event_id)
        previous = conn.execute(
            "SELECT event_id,family_id,vehicle_id,user_id,device_id,source,event_type,"
            "occurred_at,device_sequence,take_event_id,admission_outcome FROM vehicle_events "
            "WHERE event_id=%s OR (device_id=%s AND device_sequence=%s)",
            (event.event_id, device_id, event.device_sequence),
        ).fetchall()
        if previous:
            if len(previous) == 1 and tuple(previous[0][:10]) == evidence and event.device_sequence <= last_sequence:
                return AdmissionResult("retry", previous[0][10])
            return AdmissionResult("conflict")
        if event.device_sequence <= last_sequence:
            return AdmissionResult("conflict")
        if event.device_sequence > last_sequence + 1:
            return AdmissionResult("gap")

        # Evaluate after serialization and retry/sequence checks. PostgreSQL,
        # not the application/device clock, bounds brand-new evidence.
        if conn.execute(
            "SELECT %s::timestamptz > clock_timestamp() + INTERVAL '5 minutes'",
            (event.occurred_at,),
        ).fetchone()[0]:
            return AdmissionResult("future_clock_skew")

        generation, boundary = family
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        target = max(boundary, now - timedelta(hours=CORRECTION_HOURS)) if boundary else now - timedelta(hours=CORRECTION_HOURS)
        outcome = "accepted"
        last_time = conn.execute(
            "SELECT occurred_at FROM vehicle_events WHERE device_id=%s AND admission_outcome='accepted' "
            "ORDER BY device_sequence DESC LIMIT 1", (device_id,),
        ).fetchone()
        if event.occurred_at <= target:
            outcome = "before_finalized_boundary"
        elif last_time and event.occurred_at < last_time[0]:
            outcome = "invalid_chronology"
        elif event.event_type == "take" and retired is not None:
            outcome = "vehicle_retired"
        elif event.event_type == "return":
            cause = conn.execute(
                "SELECT 1 FROM vehicle_events WHERE event_id=%s AND user_id=%s AND vehicle_id=%s "
                "AND family_id=%s AND event_type='take' AND admission_outcome='accepted' AND occurred_at<=%s",
                (event.take_event_id, current_user.user_id, vehicle_id, family_id, event.occurred_at),
            ).fetchone()
            if not cause:
                outcome = "causal_conflict"

        accepted = AcceptedEvent(event.event_id, family_id, vehicle_id, current_user.user_id,
                                 event.event_type, event.occurred_at, 'native', device_id,
                                 event.device_sequence, event.take_event_id)
        if outcome == "accepted":
            try:
                # Roll back checkpoint/projection changes on deterministic refusal,
                # then write only the terminal receipt outside this savepoint.
                with conn.transaction():
                    budget = Budget()
                    generation, boundary = rolling_checkpoint(conn, family_id, generation, boundary, target, budget)
                    latest = budget.one(conn, "SELECT occurred_at FROM vehicle_events WHERE family_id=%s "
                                        "AND admission_outcome='accepted' ORDER BY occurred_at DESC,event_id DESC LIMIT 1",
                                        (family_id,))
                    fast = not latest or event.occurred_at > latest[0]
                    if fast:
                        if event.event_type == 'return':
                            budget.charge('causes', 1)
                        cause = _cause(conn, accepted, budget) if event.event_type == 'return' else None
                        if event.event_type == 'return' and not cause:
                            raise _RejectedProjection('causal_conflict')
                        projection, mutable, frozen_anchor = _incremental(conn, accepted, latest[0] if latest else None,
                                                                          budget, cause)
                    else:
                        events, seed, mutable, frozen = _load_replay(conn, family_id, generation, boundary, accepted, budget)
                        frozen_anchor = _frozen_return_anchor(accepted, frozen)
                        projection = reconcile(family_id, events, seed)
                    if projection and any(effect.outcome == 'missing_take' for effect in projection.effects):
                        raise ReconciliationError('Accepted replay lacks causal evidence')
                    plan = _plan_materialization(projection, mutable, budget, incremental=fast) if projection else None
                    if projection is None:
                        budget.charge('associations', 1)  # Anchor persisted directly in the no-op receipt.
                    active_vehicles = [session.vehicle_id for session in projection.sessions
                                       if session.ended_at is None] if projection else []
                    if active_vehicles and budget.one(conn,
                        'SELECT 1 FROM vehicles WHERE family_id=%s AND id=ANY(%s) AND retired_at IS NOT NULL LIMIT 1',
                        (family_id, active_vehicles)):
                        raise _RejectedProjection('vehicle_retired')
                    if not _receipt(conn, evidence, 'accepted', frozen_anchor):
                        raise _ReceiptConflict()
                    if plan:
                        _materialize(conn, family_id, plan)
                    conn.execute('UPDATE registered_devices SET last_processed_sequence=%s WHERE id=%s',
                                 (event.device_sequence, device_id))
                    return AdmissionResult('accepted', 'accepted')
            except PolicyExceeded:
                outcome = 'reconciliation_policy_exceeded'
            except _RejectedProjection as error:
                outcome = error.outcome
            except _ReceiptConflict:
                return AdmissionResult('conflict')

        if not _receipt(conn, evidence, outcome, None):
            return AdmissionResult('conflict')
        conn.execute("UPDATE registered_devices SET last_processed_sequence=%s WHERE id=%s",
                     (event.device_sequence, device_id))
        return AdmissionResult('terminal', outcome)


def _receipt(conn, evidence, outcome, anchor):
    return conn.execute(
            "INSERT INTO vehicle_events (event_id,family_id,vehicle_id,user_id,device_id,source,event_type,"
            "occurred_at,device_sequence,take_event_id,admission_outcome,projection_take_event_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id",
            (*evidence, outcome, anchor),
        ).fetchone()
