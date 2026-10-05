"""Pure domain tests: no application import, database, providers or network."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from itertools import permutations
import unittest
from uuid import UUID

from vehicle_reconciliation import (
    AcceptedEvent, CheckpointSeed, CheckpointSession, ReconciliationError,
    SessionKey, TakeAssociation, reconcile,
)


BASE = datetime(2026, 9, 22, 17, tzinfo=timezone.utc)


def uid(number):
    return UUID(int=number)


def take(number, minute=0, user=1, vehicle=1, **kwargs):
    return AcceptedEvent(uid(number), 10, vehicle, user, "take",
                         BASE + timedelta(minutes=minute), "legacy_shortcut", **kwargs)


def returned(number, cause, minute=1, user=1, vehicle=1):
    return replace(take(number, minute, user, vehicle), event_type="return", take_event_id=uid(cause))


def native(event, sequence, device=1):
    return replace(event, source="native", device_id=device, device_sequence=sequence)


def checkpoint(*, start_event=100):
    return CheckpointSeed(10, BASE, 4, (
        CheckpointSession(uid(500), 1, 1, BASE - timedelta(hours=1),
                          uid(start_event) if start_event is not None else None),
    ))


class ReconciliationTests(unittest.TestCase):
    def project(self, *events, seed=None):
        result = reconcile(10, events, seed)
        self.assert_invariants(result)
        return result

    def assert_invariants(self, result):
        active = [session for session in result.sessions if session.ended_at is None]
        self.assertEqual(len(active), len({session.user_id for session in active}))
        self.assertEqual(len(active), len({session.vehicle_id for session in active}))
        for session in result.sessions:
            if session.ended_at is None:
                self.assertIsNone(session.end_reason)
                self.assertIsNone(session.end_event_id)
            else:
                self.assertGreaterEqual(session.ended_at, session.started_at)
                self.assertIn(session.end_reason, {"return", "handover", "vehicle_switch"})
                self.assertIsNotNone(session.end_event_id)
        # Match the DB's half-open overlap semantics, including empty intervals.
        for i, left in enumerate(result.sessions):
            for right in result.sessions[i + 1:]:
                if left.user_id != right.user_id and left.vehicle_id != right.vehicle_id:
                    continue
                if left.ended_at == left.started_at or right.ended_at == right.started_at:
                    continue
                infinity = datetime.max.replace(tzinfo=timezone.utc)
                self.assertFalse(left.started_at < (right.ended_at or infinity)
                                 and right.started_at < (left.ended_at or infinity))

    def test_single_take_opens_session(self):
        result = self.project(take(1))
        self.assertEqual(len(result.sessions), 1)
        session = result.sessions[0]
        self.assertEqual((session.user_id, session.vehicle_id, session.start_event_id), (1, 1, uid(1)))
        self.assertEqual(session.started_at, BASE)
        self.assertIsNone(session.ended_at)

    def test_causal_return_closes(self):
        result = self.project(take(1), returned(2, 1))
        session = result.sessions[0]
        self.assertEqual((session.ended_at, session.end_event_id, session.end_reason),
                         (BASE + timedelta(minutes=1), uid(2), "return"))

    def test_redundant_take_alias_no_new_session(self):
        result = self.project(take(1), take(2, 1))
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.effects[1].outcome, "redundant_take")
        self.assertEqual(result.take_associations[0].session_key, result.take_associations[1].session_key)

    def test_return_redundant_alias_closes_original(self):
        result = self.project(take(1), take(2, 1), returned(3, 2, 2))
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.sessions[0].start_event_id, uid(1))
        self.assertEqual(result.sessions[0].end_event_id, uid(3))

    def test_handover(self):
        result = self.project(take(1), take(2, 30, user=2))
        self.assertEqual(result.sessions[0].end_reason, "handover")
        self.assertEqual(result.sessions[0].ended_at, result.sessions[1].started_at)
        self.assertEqual(result.sessions[1].user_id, 2)

    def test_vehicle_switch(self):
        result = self.project(take(1), take(2, 30, vehicle=2))
        self.assertEqual(result.sessions[0].end_reason, "vehicle_switch")
        self.assertEqual(result.sessions[1].vehicle_id, 2)

    def test_switch_and_handover_close_two(self):
        result = self.project(take(1), take(2, 1, user=2, vehicle=2), take(3, 2, vehicle=2))
        self.assertEqual([session.end_reason for session in result.sessions], ["vehicle_switch", "handover", None])
        self.assertEqual([session.end_event_id for session in result.sessions[:2]], [uid(3), uid(3)])
        self.assertEqual((result.sessions[2].user_id, result.sessions[2].vehicle_id), (1, 2))

    def test_old_alias_never_closes_reacquisition(self):
        result = self.project(take(1), take(2, 1), returned(3, 1, 2), take(4, 3), returned(5, 2, 4))
        self.assertEqual(len(result.sessions), 2)
        self.assertIsNone(result.sessions[1].ended_at)
        self.assertEqual(result.effects[-1].outcome, "already_ended")
        self.assertEqual(result.effects[-1].session_key, result.sessions[0].key)

    def test_return_after_handover_does_not_change_current_driver(self):
        result = self.project(take(1), take(2, 1, user=2), returned(3, 1, 2))
        self.assertEqual(result.effects[-1].outcome, "already_ended")
        self.assertEqual(result.sessions[1].user_id, 2)
        self.assertIsNone(result.sessions[1].ended_at)

    def test_missing_take_has_explicit_nonmutating_effect(self):
        result = self.project(take(1), returned(2, 99))
        self.assertIsNone(result.sessions[0].ended_at)
        self.assertEqual((result.effects[-1].outcome, result.effects[-1].session_key), ("missing_take", None))

    def test_return_before_take_is_corrupt(self):
        with self.assertRaises(ReconciliationError):
            self.project(take(1, 2), returned(2, 1, 1))

    def test_late_take_replays_chronologically(self):
        result = self.project(take(2, 30, user=2), take(1))
        self.assertEqual(result.sessions[0].started_at, BASE)
        self.assertEqual(result.sessions[0].ended_at, BASE + timedelta(minutes=30))
        self.assertEqual(result.sessions[1].user_id, 2)

    def test_late_return_replays_before_reacquisition(self):
        result = self.project(take(3, 3), returned(2, 1, 2), take(1))
        self.assertEqual(result.sessions[0].end_reason, "return")
        self.assertEqual(result.sessions[1].start_event_id, uid(3))
        self.assertIsNone(result.sessions[1].ended_at)

    def test_input_permutations_identical(self):
        events = (take(4), take(3, 1, user=2), take(2, 2, user=2, vehicle=2), returned(1, 2, 3, user=2, vehicle=2))
        expected = self.project(*events)
        for shuffled in permutations(events):
            self.assertEqual(self.project(*shuffled), expected)

    def test_equal_unrelated_times_use_uuid_not_input_order(self):
        result = self.project(take(2, user=2), take(1))
        self.assertEqual([effect.event_id for effect in result.effects], [uid(1), uid(2)])
        self.assertEqual(result.sessions[0].started_at, result.sessions[0].ended_at)
        self.assertEqual(result.sessions[1].user_id, 2)

    def test_equal_times_same_device_sequence_overrides_uuid(self):
        result = self.project(native(take(9), 10), native(take(1, vehicle=2), 12))
        self.assertEqual([effect.event_id for effect in result.effects], [uid(9), uid(1)])
        # Sequence gaps are admission policy, not repaired or rejected here.
        self.assertEqual(result.sessions[-1].vehicle_id, 1)  # output is canonical, not operation order
        self.assertEqual(next(session for session in result.sessions if session.ended_at is None).vehicle_id, 2)

    def test_equal_times_return_dependency_overrides_uuid(self):
        result = self.project(returned(1, 9, 0), take(9))
        self.assertEqual([effect.event_id for effect in result.effects], [uid(9), uid(1)])
        self.assertEqual(result.sessions[0].ended_at, BASE)

    def test_topological_order_combines_device_and_return_edges(self):
        events = (native(take(9), 1, 1), native(returned(2, 9, 0), 1, 2),
                  native(take(1, vehicle=2), 2, 2), take(5, user=3, vehicle=3))
        expected = self.project(*events)
        self.assertEqual([effect.event_id for effect in expected.effects], [uid(5), uid(9), uid(2), uid(1)])
        for shuffled in permutations(events):
            self.assertEqual(self.project(*shuffled), expected)

    def test_same_device_backward_clock_fails_not_repaired(self):
        with self.assertRaises(ReconciliationError):
            self.project(native(take(1, 2), 1), native(take(2, 1), 2))

    def test_equal_time_dependency_cycle_fails(self):
        with self.assertRaises(ReconciliationError):
            self.project(native(returned(1, 2, 0), 1), native(take(2), 2))

    def test_checkpoint_survives_without_old_evidence(self):
        result = self.project(seed=checkpoint(start_event=None))
        self.assertEqual(len(result.sessions), 1)
        self.assertIsNone(result.sessions[0].start_event_id)
        self.assertIsNone(result.sessions[0].ended_at)
        self.assertEqual(result.sessions[0].checkpoint_generation, 4)
        self.assertEqual(result.effects, ())

    def test_checkpoint_handover(self):
        result = self.project(take(1, 1, user=2), seed=checkpoint())
        self.assertEqual(result.sessions[0].end_reason, "handover")
        self.assertEqual(result.sessions[0].checkpoint_generation, 4)
        self.assertIsNone(result.sessions[1].checkpoint_generation)

    def test_checkpoint_switch(self):
        result = self.project(take(1, 1, vehicle=2), seed=checkpoint())
        self.assertEqual(result.sessions[0].end_reason, "vehicle_switch")

    def test_checkpoint_start_and_alias_return(self):
        seed = replace(checkpoint(), aliases=(TakeAssociation(uid(101), SessionKey("checkpoint", uid(500)), BASE),))
        for cause in (100, 101):
            result = self.project(returned(1, cause), seed=seed)
            self.assertEqual(result.sessions[0].end_reason, "return")
            self.assertEqual(result.sessions[0].checkpoint_generation, 4)

    def test_seed_alias_can_survive_without_original_start_event(self):
        seed = replace(checkpoint(start_event=None), aliases=(TakeAssociation(uid(101), SessionKey("checkpoint", uid(500)), BASE),))
        result = self.project(returned(1, 101), seed=seed)
        self.assertIsNone(result.sessions[0].start_event_id)
        self.assertEqual(result.sessions[0].end_event_id, uid(1))

    def test_redundant_suffix_take_aliases_checkpoint(self):
        result = self.project(take(1, 1), returned(2, 1, 2), seed=checkpoint())
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.effects[0].outcome, "redundant_take")
        self.assertEqual(result.sessions[0].end_reason, "return")

    def test_seed_replay_rebuilds_suffix_end_each_time(self):
        seed = checkpoint()
        first = self.project(take(2, 2, user=2), seed=seed)
        second = self.project(take(2, 2, user=2), returned(1, 100, 1), seed=seed)
        self.assertEqual(first.sessions[0].end_reason, "handover")
        self.assertEqual(second.sessions[0].end_reason, "return")
        self.assertEqual(seed, checkpoint())

    def test_checkpoint_does_not_invent_history(self):
        result = self.project(returned(1, 999), seed=CheckpointSeed(10, BASE, 4))
        self.assertEqual(result.sessions, ())
        self.assertEqual(result.effects[0].outcome, "missing_take")

    def test_preboundary_and_boundary_events_rejected(self):
        for minute in (-1, 0):
            with self.assertRaises(ReconciliationError):
                self.project(take(1, minute), seed=checkpoint())

    def test_checkpoint_start_after_boundary_rejected(self):
        seed = checkpoint()
        seed = replace(seed, sessions=(replace(seed.sessions[0], started_at=BASE + timedelta(minutes=2)),))
        with self.assertRaises(ReconciliationError):
            self.project(returned(1, 100, 1), seed=seed)

    def test_conflicting_seed_occupancy_rejected(self):
        seed = checkpoint()
        for user, vehicle in ((1, 2), (2, 1)):
            other = CheckpointSession(uid(501), vehicle, user, BASE)
            with self.assertRaises(ReconciliationError):
                self.project(seed=replace(seed, sessions=seed.sessions + (other,)))

    def test_seed_alias_validation(self):
        seed = checkpoint()
        for alias in (
            TakeAssociation(uid(101), SessionKey("checkpoint", uid(999)), BASE),
            TakeAssociation(uid(101), SessionKey("checkpoint", uid(500)), BASE + timedelta(seconds=1)),
            TakeAssociation(uid(101), SessionKey("checkpoint", uid(500)), BASE - timedelta(hours=2)),
            TakeAssociation(uid(100), SessionKey("checkpoint", uid(500)), BASE),
        ):
            with self.subTest(alias=alias), self.assertRaises(ReconciliationError):
                self.project(seed=replace(seed, aliases=(alias,)))

    def test_foreign_checkpoint_and_generation_rejected(self):
        for seed in (replace(checkpoint(), family_id=11), replace(checkpoint(), generation=0)):
            with self.assertRaises(ReconciliationError):
                self.project(seed=seed)

    def test_seed_input_order_is_irrelevant(self):
        seed = checkpoint()
        other = CheckpointSession(uid(501), 2, 2, BASE)
        left = replace(seed, sessions=seed.sessions + (other,))
        right = replace(left, sessions=tuple(reversed(left.sessions)))
        self.assertEqual(self.project(take(1, 1, vehicle=2), seed=left),
                         self.project(take(1, 1, vehicle=2), seed=right))

    def test_wrong_actor_or_vehicle_return_is_corrupt(self):
        for user, vehicle in ((2, 1), (1, 2)):
            with self.assertRaises(ReconciliationError):
                self.project(take(1), returned(2, 1, user=user, vehicle=vehicle))
            with self.assertRaises(ReconciliationError):
                self.project(returned(2, 100, user=user, vehicle=vehicle), seed=checkpoint())

    def test_duplicate_uuid_or_sequence_rejected(self):
        for events in ((take(1), take(1)), (take(1), take(1, user=2)),
                       (native(take(1), 1), native(take(2), 1))):
            with self.assertRaises(ReconciliationError):
                self.project(*events)

    def test_device_owner_contradiction_rejected(self):
        with self.assertRaises(ReconciliationError):
            self.project(native(take(1), 1), native(take(2, user=2), 2))

    def test_return_referencing_return_rejected(self):
        with self.assertRaises(ReconciliationError):
            self.project(take(1), returned(2, 1), returned(3, 2, 2))

    def test_invalid_evidence_shapes_rejected(self):
        for event in (
            replace(take(1), family_id=11), replace(take(1), user_id=0),
            replace(take(1), occurred_at=BASE.replace(tzinfo=None)),
            replace(take(1), event_type="invalid"), replace(take(1), source="invalid"),
            replace(take(1), take_event_id=uid(2)), replace(returned(1, 2), take_event_id=uid(1)),
            replace(take(1), source="native"), replace(take(1), device_id=1),
            replace(native(take(1), 1), device_sequence=0),
        ):
            with self.subTest(event=event), self.assertRaises(ReconciliationError):
                self.project(event)

    def test_offsets_are_compared_as_instants(self):
        event = replace(take(1), occurred_at=BASE.astimezone(timezone(timedelta(hours=3))))
        self.assertEqual(self.project(event), self.project(take(1)))

    def test_evidence_and_seed_are_immutable_and_unchanged(self):
        event, seed = take(1, 1), checkpoint()
        before = (event, seed)
        result = self.project(event, seed=seed)
        self.assertEqual((event, seed), before)
        with self.assertRaises(FrozenInstanceError):
            event.vehicle_id = 2
        with self.assertRaises(FrozenInstanceError):
            result.sessions[0].ended_at = BASE

    def test_many_interleavings_preserve_invariants_at_every_prefix(self):
        events = (take(1), take(2, user=2, vehicle=2), take(3, vehicle=2),
                  take(4, user=2), returned(5, 1, 0), returned(6, 2, 0, user=2, vehicle=2))
        expected = self.project(*events)
        for shuffled in permutations(events):
            self.assertEqual(self.project(*shuffled), expected)
        ordered = sorted(events, key=lambda event: event.event_id)
        for end in range(1, len(ordered) + 1):
            self.project(*ordered[:end])


if __name__ == "__main__":
    unittest.main()
