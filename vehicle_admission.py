"""INTERNAL ONLY: native evidence admission. No pool, route or runtime caller.

Lock order: shared deletion identity fence -> existing family car advisory lock
-> family row -> owned device row -> target vehicle row. Never fence another
member while holding family locks. Retirement/checkpoint writers must share the
family serialization contract. Deletion integration is still a prerequisite to
activation. Call on a caller-owned connection; an outer transaction, if present,
owns the final commit. Exceptions roll back this operation's transaction/savepoint.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from deletion_gate import IdentityUnavailable, require_auth
from identity import CurrentUser
from vehicle_reconciliation import (
    AcceptedEvent, CheckpointSeed, CheckpointSession, ReconciliationError,
    SessionKey, TakeAssociation, reconcile,
)


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
    kind: Literal["accepted", "retry", "terminal", "gap", "conflict", "unavailable", "malformed"]
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


def _load_replay(conn, family_id, generation, boundary):
    """Single insertion point for a future bounded replay-load policy.

    No production workload threshold is chosen here; this service has no route.
    Seeds include marked sessions even when a suffix event has since ended them.
    """
    existing = conn.execute(
        "SELECT id,session_ref,vehicle_id,user_id,started_at,start_event_id,"
        "ended_at,end_event_id,end_reason,created_at,checkpoint_generation "
        "FROM vehicle_driver_sessions WHERE family_id=%s ORDER BY id", (family_id,),
    ).fetchall()
    seed, mutable, anchors, frozen_anchors = None, {}, {}, set()
    carried = []
    for row in existing:
        _, ref, vehicle, user, start, start_event, end, _, _, _, marker = row
        if boundary is not None and marker == generation:
            if start > boundary or (end is not None and end <= boundary):
                raise ReconciliationError("Invalid carried checkpoint session")
            key = SessionKey("checkpoint", ref)
            carried.append(CheckpointSession(ref, vehicle, user, start, start_event))
            if start_event is not None:
                anchors[start_event] = key
        elif boundary is None or start > boundary:
            if start_event is None:
                raise ReconciliationError("Mutable session lacks start evidence")
            key = SessionKey("take", start_event)
        else:
            if end is None or end > boundary:
                raise ReconciliationError("Unmarked session crosses checkpoint")
            if start_event is not None:
                frozen_anchors.add(start_event)
            continue  # Frozen historical row is never deleted/updated.
        mutable[key] = row
    frozen_causes = {}
    if boundary is not None:
        aliases = []
        for event_id, anchor, occurred_at, user_id, vehicle_id in conn.execute(
            "SELECT event_id,projection_take_event_id,occurred_at,user_id,vehicle_id FROM vehicle_events "
            "WHERE family_id=%s AND admission_outcome='accepted' AND event_type='take' "
            "AND occurred_at<=%s AND projection_take_event_id=ANY(%s)",
            (family_id, boundary, list(anchors.keys() | frozen_anchors)),
        ).fetchall():
            if anchor in frozen_anchors:
                frozen_causes[event_id] = (anchor, occurred_at, user_id, vehicle_id)
            else:
                aliases.append(TakeAssociation(event_id, anchors[anchor], occurred_at))
        seed = CheckpointSeed(family_id, boundary, generation, tuple(carried), tuple(aliases))
    rows = conn.execute(
        "SELECT event_id,family_id,vehicle_id,user_id,event_type,occurred_at,source,"
        "device_id,device_sequence,take_event_id FROM vehicle_events "
        "WHERE family_id=%s AND admission_outcome='accepted' "
        "AND (%s::timestamptz IS NULL OR occurred_at>%s)",
        (family_id, boundary, boundary),
    ).fetchall()
    events = [AcceptedEvent(*row) for row in rows]
    # Proven already-ended RETURNs have no effect on the mutable suffix. Keep
    # their evidence/association intact; do not reconstruct frozen sessions.
    events = [event for event in events if _frozen_return_anchor(event, frozen_causes) is None]
    return events, seed, mutable, frozen_causes


def _frozen_return_anchor(event, frozen_causes):
    if event.event_type != "return" or event.take_event_id not in frozen_causes:
        return None
    anchor, occurred_at, user_id, vehicle_id = frozen_causes[event.take_event_id]
    if (event.user_id, event.vehicle_id) != (user_id, vehicle_id) or event.occurred_at < occurred_at:
        raise ReconciliationError("Invalid RETURN against frozen session")
    return anchor


def _materialize(conn, family_id, projection, mutable):
    # Sessions have no inbound FKs. Remove only replay-owned rows before inserts:
    # partial active indexes are immediate, unlike deferrable overlap constraints.
    conn.execute("DELETE FROM vehicle_driver_sessions WHERE family_id=%s AND id=ANY(%s)",
                 (family_id, [row[0] for row in mutable.values()]))
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
    for session in projection.sessions:
        values = (family_id, session.vehicle_id, session.user_id, session.started_at,
                  session.start_event_id, session.ended_at, session.end_event_id,
                  session.end_reason, session.checkpoint_generation)
        columns = "family_id,vehicle_id,user_id,started_at,start_event_id,ended_at,end_event_id,end_reason,checkpoint_generation"
        previous = mutable.get(session.key)
        if previous is None and retained.get(session.key):
            previous = min(retained[session.key], key=lambda row: (row[4], row[1]))
        if previous:
            conn.execute(f"INSERT INTO vehicle_driver_sessions (id,session_ref,created_at,{columns}) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (previous[0], previous[1], previous[9], *values))
        else:
            conn.execute(f"INSERT INTO vehicle_driver_sessions ({columns}) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", values)
    sessions = {session.key: session for session in projection.sessions}
    for effect in projection.effects:
        anchor = sessions[effect.session_key].start_event_id if effect.session_key is not None else None
        conn.execute("UPDATE vehicle_events SET projection_take_event_id=%s "
                     "WHERE family_id=%s AND event_id=%s AND admission_outcome='accepted'",
                     (anchor, family_id, effect.event_id))


def admit_native_event(conn, current_user: CurrentUser, request: NativeEvent):
    event = _envelope(request)
    if event is None:
        return AdmissionResult("malformed")
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

        generation, boundary = family
        outcome = "accepted"
        last_time = conn.execute(
            "SELECT occurred_at FROM vehicle_events WHERE device_id=%s AND admission_outcome='accepted' "
            "ORDER BY device_sequence DESC LIMIT 1", (device_id,),
        ).fetchone()
        if boundary is not None and event.occurred_at <= boundary:
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

        projection, mutable, frozen_anchor = None, None, None
        if outcome == "accepted":
            events, seed, mutable, frozen_causes = _load_replay(conn, family_id, generation, boundary)
            accepted = AcceptedEvent(event.event_id, family_id, vehicle_id, current_user.user_id,
                                     event.event_type, event.occurred_at, "native", device_id,
                                     event.device_sequence, event.take_event_id)
            frozen_anchor = _frozen_return_anchor(accepted, frozen_causes)
            projection = reconcile(family_id, events if frozen_anchor else [*events, accepted], seed)
            for effect in projection.effects:
                if effect.outcome == "missing_take":
                    if effect.event_id != event.event_id:
                        raise ReconciliationError("Stored accepted RETURN lacks replay cause")
                    outcome = "causal_conflict"
            active_vehicles = [session.vehicle_id for session in projection.sessions if session.ended_at is None]
            if outcome == "accepted" and conn.execute(
                "SELECT 1 FROM vehicles WHERE family_id=%s AND id=ANY(%s) AND retired_at IS NOT NULL LIMIT 1",
                (family_id, active_vehicles),
            ).fetchone():
                outcome = "vehicle_retired"  # Late replay must not reactivate another retired vehicle.

        inserted = conn.execute(
            "INSERT INTO vehicle_events (event_id,family_id,vehicle_id,user_id,device_id,source,event_type,"
            "occurred_at,device_sequence,take_event_id,admission_outcome,projection_take_event_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id",
            (*evidence, outcome, frozen_anchor if outcome == "accepted" else None),
        ).fetchone()
        if not inserted:
            # Global UUID races can cross family locks. Unique constraints arbitrate;
            # no unrelated integrity error is swallowed and no projection changed.
            return AdmissionResult("conflict")
        if outcome == "accepted":
            _materialize(conn, family_id, projection, mutable)
        conn.execute("UPDATE registered_devices SET last_processed_sequence=%s WHERE id=%s",
                     (event.device_sequence, device_id))
        return AdmissionResult("accepted" if outcome == "accepted" else "terminal", outcome)
