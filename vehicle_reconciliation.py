"""Pure family-wide projection of accepted evidence. Standard library only.

No admission, I/O, clocks, random IDs or persistence. Inputs are trusted internal
contracts, not HTTP models. Structural contradictions raise ReconciliationError;
an absent causal TAKE produces a non-mutating `missing_take` effect.

A checkpoint supplies state AT its boundary, not current session row state.
The future loader must include all marked carry-in sessions even if later ended,
and their retained TAKE aliases. Frozen pre-boundary history is not returned.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from heapq import heappop, heappush
from typing import Literal
from uuid import UUID


class ReconciliationError(ValueError):
    """Corrupt/contradictory accepted evidence or checkpoint; not admission."""


@dataclass(frozen=True)
class AcceptedEvent:
    event_id: UUID
    family_id: int
    vehicle_id: int
    user_id: int
    event_type: Literal["take", "return"]
    occurred_at: datetime
    source: Literal["native", "legacy_shortcut"]
    device_id: int | None = None
    device_sequence: int | None = None
    take_event_id: UUID | None = None


@dataclass(frozen=True)
class SessionKey:
    # A projection key, NOT a newly generated public session_ref. The adapter
    # preserves/materializes public refs; tags separate event and seed UUIDs.
    kind: Literal["take", "checkpoint"]
    ref: UUID


@dataclass(frozen=True)
class SessionProjection:
    key: SessionKey
    vehicle_id: int
    user_id: int
    started_at: datetime
    start_event_id: UUID | None
    ended_at: datetime | None = None
    end_event_id: UUID | None = None
    end_reason: Literal["return", "handover", "vehicle_switch"] | None = None
    checkpoint_generation: int | None = None


@dataclass(frozen=True)
class CheckpointSession:
    session_ref: UUID
    vehicle_id: int
    user_id: int
    started_at: datetime
    start_event_id: UUID | None = None


@dataclass(frozen=True)
class TakeAssociation:
    take_event_id: UUID
    session_key: SessionKey
    occurred_at: datetime


@dataclass(frozen=True)
class CheckpointSeed:
    family_id: int
    finalized_through: datetime
    generation: int
    sessions: tuple[CheckpointSession, ...] = ()
    aliases: tuple[TakeAssociation, ...] = ()


@dataclass(frozen=True)
class EventEffect:
    event_id: UUID
    outcome: Literal["opened", "redundant_take", "returned", "already_ended", "missing_take"]
    session_key: SessionKey | None


@dataclass(frozen=True)
class ReconciliationResult:
    family_id: int
    sessions: tuple[SessionProjection, ...]
    take_associations: tuple[TakeAssociation, ...]
    effects: tuple[EventEffect, ...]


def _require(condition, message):
    if not condition:
        raise ReconciliationError(message)


def _positive(value):
    return type(value) is int and value > 0


def _instant(value):
    _require(isinstance(value, datetime), "Expected aware datetime")
    try:
        _require(value.tzinfo is not None and value.utcoffset() is not None,
                 "Naive timestamp")
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as error:
        raise ReconciliationError("Invalid timestamp") from error


def _ordered(events, family_id, boundary, seed_aliases):
    by_id, devices = {}, {}
    for raw in events:
        _require(isinstance(raw, AcceptedEvent), "Expected accepted event")
        _require(isinstance(raw.event_id, UUID), "Invalid event UUID")
        _require(raw.event_id not in by_id and raw.event_id not in seed_aliases,
                 "Duplicate event UUID or checkpoint evidence replay")
        _require(_positive(raw.family_id) and raw.family_id == family_id, "Mixed family evidence")
        _require(_positive(raw.user_id) and _positive(raw.vehicle_id), "Invalid event identity")
        _require(raw.event_type in ("take", "return"), "Invalid event type")
        _require(raw.source in ("native", "legacy_shortcut"), "Invalid event source")
        if raw.source == "native":
            _require(_positive(raw.device_id) and _positive(raw.device_sequence), "Invalid device evidence")
        else:
            _require(raw.device_id is None and raw.device_sequence is None, "Invalid legacy evidence")
        if raw.event_type == "take":
            _require(raw.take_event_id is None, "TAKE cannot reference TAKE")
        else:
            _require(isinstance(raw.take_event_id, UUID) and raw.take_event_id != raw.event_id,
                     "Invalid RETURN cause")
        event = replace(raw, occurred_at=_instant(raw.occurred_at))
        _require(boundary is None or event.occurred_at > boundary, "Evidence at/before finalized boundary")
        by_id[event.event_id] = event
        if event.device_id is not None:
            devices.setdefault(event.device_id, []).append(event)

    edges = {key: set() for key in by_id}
    indegree = dict.fromkeys(by_id, 0)

    def precedes(first, second):
        _require(first.occurred_at <= second.occurred_at, "Backward causal chronology")
        if second.event_id not in edges[first.event_id]:
            edges[first.event_id].add(second.event_id)
            indegree[second.event_id] += 1

    for device_events in devices.values():
        device_events.sort(key=lambda event: event.device_sequence)
        _require(len({event.user_id for event in device_events}) == 1, "Device has contradictory owners")
        for first, second in zip(device_events, device_events[1:]):
            _require(first.device_sequence != second.device_sequence, "Duplicate device sequence")
            precedes(first, second)
    for event in by_id.values():
        if event.event_type == "return" and event.take_event_id in by_id:
            cause = by_id[event.take_event_id]
            _require(cause.event_type == "take", "RETURN references non-TAKE")
            _require((cause.user_id, cause.vehicle_id) == (event.user_id, event.vehicle_id),
                     "RETURN cause identity mismatch")
            precedes(cause, event)

    ready = []
    for key, degree in indegree.items():
        if degree == 0:
            heappush(ready, (by_id[key].occurred_at, key))
    ordered = []
    while ready:
        _, key = heappop(ready)
        ordered.append(by_id[key])
        for next_key in edges[key]:
            indegree[next_key] -= 1
            if indegree[next_key] == 0:
                heappush(ready, (by_id[next_key].occurred_at, next_key))
    _require(len(ordered) == len(by_id), "Contradictory event ordering cycle")
    return ordered


def reconcile(family_id: int, events, seed: CheckpointSeed | None = None):
    """Compute a desired suffix projection without mutating any input.

    Device gaps and policy limits are deliberately not checked here. Missing
    TAKE effects must be classified by admission, never resolved via current
    occupancy. Caller must supply the complete accepted suffix and boundary seed.
    """
    _require(_positive(family_id), "Invalid family identity")
    sessions, aliases, active_users, active_vehicles = {}, {}, {}, {}
    boundary = None

    def activate(session):
        _require(session.key not in sessions, "Duplicate session key")
        _require(session.user_id not in active_users and session.vehicle_id not in active_vehicles,
                 "Overlapping checkpoint/session state")
        sessions[session.key] = session
        active_users[session.user_id] = session.key
        active_vehicles[session.vehicle_id] = session.key

    def associate(alias):
        _require(isinstance(alias.take_event_id, UUID), "Invalid alias UUID")
        _require(alias.session_key in sessions, "Alias references absent session")
        previous = aliases.get(alias.take_event_id)
        _require(previous is None or previous == alias, "Contradictory TAKE alias")
        aliases[alias.take_event_id] = alias

    if seed is not None:
        _require(isinstance(seed, CheckpointSeed) and _positive(seed.generation), "Invalid checkpoint")
        _require(_positive(seed.family_id) and seed.family_id == family_id, "Mixed family checkpoint")
        boundary = _instant(seed.finalized_through)
        for carried in seed.sessions:
            _require(isinstance(carried, CheckpointSession), "Invalid checkpoint session")
            _require(isinstance(carried.session_ref, UUID), "Invalid checkpoint reference")
            _require(_positive(carried.user_id) and _positive(carried.vehicle_id), "Invalid checkpoint identity")
            start = _instant(carried.started_at)
            _require(start <= boundary, "Checkpoint session starts after boundary")
            _require(carried.start_event_id is None or isinstance(carried.start_event_id, UUID),
                     "Invalid checkpoint start event")
            key = SessionKey("checkpoint", carried.session_ref)
            activate(SessionProjection(key, carried.vehicle_id, carried.user_id, start,
                                       carried.start_event_id, checkpoint_generation=seed.generation))
            if carried.start_event_id is not None:
                associate(TakeAssociation(carried.start_event_id, key, start))
        for alias in seed.aliases:
            _require(isinstance(alias, TakeAssociation), "Invalid checkpoint alias")
            alias = replace(alias, occurred_at=_instant(alias.occurred_at))
            _require(alias.session_key in sessions, "Alias references absent session")
            _require(sessions[alias.session_key].started_at <= alias.occurred_at <= boundary,
                     "Checkpoint alias outside carried session history")
            associate(alias)

    ordered = _ordered(events, family_id, boundary, aliases)
    effects = []

    def close(key, event, reason):
        session = sessions[key]
        _require(session.ended_at is None and event.occurred_at >= session.started_at,
                 "Invalid session ending")
        _require(active_users.get(session.user_id) == key and active_vehicles.get(session.vehicle_id) == key,
                 "Inconsistent active session projection")
        sessions[key] = replace(session, ended_at=event.occurred_at,
                                end_event_id=event.event_id, end_reason=reason)
        del active_users[session.user_id]
        del active_vehicles[session.vehicle_id]

    for event in ordered:
        if event.event_type == "take":
            actor_key = active_users.get(event.user_id)
            target_key = active_vehicles.get(event.vehicle_id)
            if actor_key is not None and actor_key == target_key:
                key, outcome = actor_key, "redundant_take"
            else:
                if actor_key is not None:
                    close(actor_key, event, "vehicle_switch")
                if target_key is not None:
                    close(target_key, event, "handover")
                key, outcome = SessionKey("take", event.event_id), "opened"
                activate(SessionProjection(key, event.vehicle_id, event.user_id,
                                           event.occurred_at, event.event_id))
            associate(TakeAssociation(event.event_id, key, event.occurred_at))
        else:
            alias = aliases.get(event.take_event_id)
            if alias is None:
                key, outcome = None, "missing_take"
            else:
                key = alias.session_key
                session = sessions[key]
                _require((session.user_id, session.vehicle_id) == (event.user_id, event.vehicle_id),
                         "RETURN cause identity mismatch")
                _require(event.occurred_at >= alias.occurred_at, "RETURN precedes causal TAKE")
                if session.ended_at is None:
                    close(key, event, "return")
                    outcome = "returned"
                else:
                    outcome = "already_ended"
        effects.append(EventEffect(event.event_id, outcome, key))

    return ReconciliationResult(
        family_id,
        tuple(sorted(sessions.values(), key=lambda item: (item.started_at, item.key.kind, item.key.ref))),
        tuple(sorted(aliases.values(), key=lambda item: item.take_event_id)),
        tuple(effects),
    )
