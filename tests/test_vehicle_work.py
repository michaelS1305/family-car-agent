"""Bounded admission tests; only disposable local PostgreSQL fixtures."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import vehicle_admission as va
import vehicle_work as work
from vehicle_reconciliation import AcceptedEvent, reconcile
from tests import test_vehicle_admission as fixtures


MIGRATION = Path(__file__).resolve().parents[1] / 'supabase/manual_migrations/2026092301_vehicle_events_accepted_device_index.sql'


class BudgetTests(unittest.TestCase):
    def test_each_dimension_and_aggregate_are_hard_caps(self):
        for name in work.WorkLimits.__dataclass_fields__:
            if name == 'total':
                continue
            budget = work.Budget(replace(work.DEFAULT_LIMITS, **{name: 1}))
            budget.charge(name, 1)
            with self.assertRaises(work.PolicyExceeded, msg=name):
                budget.charge(name, 1)
        budget = work.Budget(replace(work.DEFAULT_LIMITS, total=1))
        budget.charge('events', 1)
        with self.assertRaises(work.PolicyExceeded):
            budget.charge('sql', 1)

    def test_migration_only_authorized_index(self):
        source = MIGRATION.read_text()
        self.assertEqual(source.count('CREATE INDEX '), 1)
        self.assertIn("ON public.vehicle_events (device_id, device_sequence)", source)
        self.assertIn("WHERE admission_outcome = 'accepted'", source)
        for forbidden in ('ALTER TABLE', 'CREATE TABLE', 'CREATE FUNCTION', 'GRANT ', 'REVOKE ', 'DROP '):
            self.assertNotIn(forbidden, source)
        self.assertIn('BEGIN;', source)
        self.assertIn('COMMIT;', source)
        self.assertIn('Already applied or conflicting index', source)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class BoundedAdmissionPostgresTests(unittest.TestCase):
    setUp = fixtures.VehicleAdmissionPostgresTests.setUp
    connection = fixtures.VehicleAdmissionPostgresTests.connection
    drop_schema = fixtures.VehicleAdmissionPostgresTests.drop_schema
    query = fixtures.VehicleAdmissionPostgresTests.query
    event = fixtures.VehicleAdmissionPostgresTests.event
    sessions = fixtures.VehicleAdmissionPostgresTests.sessions
    snapshot = fixtures.VehicleAdmissionPostgresTests.snapshot
    sequence = fixtures.VehicleAdmissionPostgresTests.sequence

    def admit_at(self, event, now=None, user=1, queries=None, maintenance=False):
        now = now or fixtures.BASE + timedelta(hours=1)
        with self.connection() as conn:
            class Clock:
                transaction = conn.transaction

                def execute(inner, sql, params=None):
                    if queries is not None:
                        queries.append((sql, params))
                    if sql == 'SELECT clock_timestamp()':
                        return conn.execute('SELECT %s::timestamptz', (now,))
                    if sql.startswith('SELECT %s::timestamptz > clock_timestamp()'):
                        return conn.execute(sql.replace('clock_timestamp()', '%s::timestamptz'), (*params, now))
                    return conn.execute(sql, params)
            if maintenance:
                return va.maintain_native_checkpoint(Clock(), self.users[user])
            return va.admit_native_event(Clock(), self.users[user], event)

    def family(self):
        return self.query('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=10')[0]

    def projection(self):
        return (self.family(), self.query('SELECT * FROM vehicle_driver_sessions ORDER BY id'))

    def test_incremental_all_transitions_equal_full_engine_and_no_replay(self):
        first = self.event()
        redundant = self.event(2, 1)
        handover = self.event(user=2, minute=2)
        switch = self.event(3, 3, vehicle=1)
        both = self.event(4, 4)
        stale_return = self.event(2, 5, user=2, cause=handover.event_id)
        returned = self.event(5, 6, cause=both.event_id)
        ended_return = self.event(6, 7, cause=redundant.event_id)
        accepted = []
        with patch.object(va, '_load_replay', side_effect=AssertionError('strict append replayed')):
            for event, user in ((first, 1), (redundant, 1), (handover, 2), (switch, 1),
                                (both, 1), (stale_return, 2), (returned, 1), (ended_return, 1)):
                self.assertEqual(self.admit_at(event, user=user).kind, 'accepted')
                vehicle = self.query('SELECT id FROM vehicles WHERE vehicle_ref=%s', (event.vehicle_ref,))[0][0]
                device = self.query('SELECT id FROM registered_devices WHERE device_ref=%s', (event.device_ref,))[0][0]
                accepted.append(AcceptedEvent(event.event_id, 10, vehicle, user, event.event_type,
                                              event.occurred_at, 'native', device, event.device_sequence, event.take_event_id))
                expected = reconcile(10, accepted)
                actual = self.query('SELECT user_id,vehicle_id,started_at,ended_at,end_reason,start_event_id,end_event_id '
                                    'FROM vehicle_driver_sessions ORDER BY started_at,start_event_id')
                want = sorted([(s.user_id, s.vehicle_id, s.started_at, s.ended_at, s.end_reason,
                                s.start_event_id, s.end_event_id) for s in expected.sessions], key=lambda row: (row[2], row[5]))
                self.assertEqual(actual, want)

    def test_equal_timestamp_replays_and_keeps_unchanged_rows(self):
        first = self.event()
        self.admit_at(first)
        rows = self.query('SELECT * FROM vehicle_driver_sessions')
        with patch.object(va, '_load_replay', wraps=va._load_replay) as replay:
            self.assertEqual(self.admit_at(self.event(2)).kind, 'accepted')
            replay.assert_called_once()
        self.assertEqual(rows, self.query('SELECT * FROM vehicle_driver_sessions'))

    def test_exact_72h_inside_outside_and_terminal_retry(self):
        now = fixtures.BASE + timedelta(hours=72)
        at = self.event()
        self.assertEqual(self.admit_at(at, now).admission_outcome, 'before_finalized_boundary')
        self.assertEqual(self.sequence(), 1)
        self.assertEqual(self.admit_at(at, now + timedelta(days=5)).kind, 'retry')
        self.assertEqual(self.admit_at(replace(at, occurred_at=at.occurred_at + timedelta(seconds=1)), now).kind, 'conflict')
        outside = replace(self.event(2), occurred_at=fixtures.BASE - timedelta(microseconds=1))
        self.assertEqual(self.admit_at(outside, now).admission_outcome, 'before_finalized_boundary')
        inside = replace(self.event(3), occurred_at=fixtures.BASE + timedelta(microseconds=1))
        self.assertEqual(self.admit_at(inside, now).kind, 'accepted')
        self.assertEqual(self.family(), (1, fixtures.BASE))

    def test_long_trip_generations_old_alias_return_and_aged_retry(self):
        first, alias = self.event(), self.event(2, 1)
        self.admit_at(first)
        self.admit_at(alias)
        ref = self.sessions()[0][0]
        for seq, day in ((3, 4), (4, 5)):
            now = fixtures.BASE + timedelta(days=day)
            event = replace(self.event(seq), occurred_at=now)
            self.assertEqual(self.admit_at(event, now).kind, 'accepted')
            self.assertEqual(self.sessions()[0][0], ref)
            self.assertIsNone(self.sessions()[0][4])
            self.assertEqual(self.sessions()[0][8], self.family()[0])
        now = fixtures.BASE + timedelta(days=6)
        returned = replace(self.event(5, cause=alias.event_id), occurred_at=now)
        self.assertEqual(self.admit_at(returned, now).kind, 'accepted')
        self.assertEqual(self.sessions()[0][5], 'return')
        self.assertEqual(self.admit_at(first, now).kind, 'retry')

    def test_ended_now_crossing_seed_and_demand_only_aliases(self):
        first, alias = self.event(), self.event(2, 1)
        self.admit_at(first)
        self.admit_at(alias)
        end = replace(self.event(3, cause=alias.event_id), occurred_at=fixtures.BASE + timedelta(days=2))
        self.admit_at(end, end.occurred_at)
        now = fixtures.BASE + timedelta(days=4)
        # A different user's strictly newer event advances boundary to day 1.
        self.admit_at(replace(self.event(user=2, vehicle=1), occurred_at=now), now, user=2)
        seed = self.query('SELECT checkpoint_generation FROM vehicle_driver_sessions WHERE start_event_id=%s', (first.event_id,))[0][0]
        self.assertEqual(seed, self.family()[0])
        late = replace(self.event(4, cause=first.event_id), occurred_at=fixtures.BASE + timedelta(days=3))
        queries = []
        self.assertEqual(self.admit_at(late, now, queries=queries).kind, 'accepted')
        self.assertEqual(self.sessions()[0][4], end.occurred_at)
        self.assertFalse(any('projection_take_event_id=ANY' in sql for sql, _ in queries))

    def test_old_unaccepted_take_cannot_be_return_cause(self):
        now = fixtures.BASE + timedelta(days=4)
        old = self.event()
        self.assertEqual(self.admit_at(old, now).kind, 'terminal')
        returned = replace(self.event(2, cause=old.event_id), occurred_at=now)
        self.assertEqual(self.admit_at(returned, now).admission_outcome, 'causal_conflict')
        self.assertEqual(self.sessions(), [])

    def reject(self, event, dimension, now=None):
        before = self.projection()
        with patch.object(work, 'DEFAULT_LIMITS', replace(work.DEFAULT_LIMITS, **{dimension: 0})):
            self.assertEqual(self.admit_at(event, now).admission_outcome, 'reconciliation_policy_exceeded', dimension)
        self.assertEqual(self.projection(), before, dimension)
        self.assertEqual(self.sequence(), event.device_sequence)
        self.assertEqual(self.admit_at(event, now).kind, 'retry')

    def test_event_insert_association_sql_total_overflow(self):
        for seq, dimension in enumerate(('events', 'inserts', 'associations', 'sql', 'total'), 1):
            self.reject(self.event(seq, seq), dimension)

    def test_seed_session_update_cause_overflow(self):
        first = self.event()
        self.admit_at(first)
        for seq, dimension in enumerate(('seeds', 'sessions', 'updates', 'causes'), 2):
            event = self.event(seq, seq, cause=first.event_id) if dimension == 'causes' else self.event(seq, seq, vehicle=1)
            self.reject(event, dimension)

    def test_delete_overflow_and_bounded_loader(self):
        first = self.event()
        self.admit_at(first)
        self.admit_at(self.event(user=2, minute=5), user=2)
        # Earlier RETURN changes the already materialized handover ending.
        before = self.projection()
        queries = []
        with patch.object(work, 'DEFAULT_LIMITS', replace(work.DEFAULT_LIMITS, deletes=0)):
            result = self.admit_at(self.event(2, minute=4, cause=first.event_id), queries=queries)
        self.assertEqual(result.admission_outcome, 'reconciliation_policy_exceeded')
        self.assertEqual(self.projection(), before)
        for sql, params in queries:
            if sql.startswith('SELECT') and ('ORDER BY started_at,id' in sql or 'ORDER BY occurred_at,event_id' in sql
                                             or 'AND checkpoint_generation=%s' in sql):
                self.assertTrue(sql.endswith('LIMIT %s'), sql)
                self.assertLessEqual(params[-1], work.DEFAULT_LIMITS.sessions + 1)

    def test_checkpoint_overflow_does_not_partially_advance(self):
        self.admit_at(self.event())
        now = fixtures.BASE + timedelta(days=4)
        self.reject(replace(self.event(2), occurred_at=now), 'checkpoint', now)

    def test_dense_suffix_overflow_reads_only_sentinel_page(self):
        self.admit_at(self.event())
        self.admit_at(self.event(2, 2))
        before, queries = self.projection(), []
        with patch.object(work, 'DEFAULT_LIMITS', replace(work.DEFAULT_LIMITS, events=1)):
            result = self.admit_at(self.event(user=2, minute=1), user=2, queries=queries)
        self.assertEqual(result.admission_outcome, 'reconciliation_policy_exceeded')
        self.assertEqual(self.projection(), before)
        loads = [(sql, params) for sql, params in queries if 'ORDER BY occurred_at,event_id' in sql]
        self.assertEqual(len(loads), 1)
        self.assertEqual(loads[0][1][-1], 1)

    def test_explicit_maintenance_advances_bounded_complete_steps(self):
        for seq in range(1, 7):
            self.admit_at(self.event(seq, seq, vehicle=seq % 2))
        now = fixtures.BASE + timedelta(days=4)
        before_events = self.query('SELECT * FROM vehicle_events ORDER BY id')
        before_sequence = self.sequence()
        with patch.object(work, 'DEFAULT_LIMITS', replace(work.DEFAULT_LIMITS, checkpoint=3)):
            self.assertEqual(self.admit_at(None, now, maintenance=True), 'progress')
            first_boundary = self.family()[1]
            self.assertEqual(self.admit_at(None, now, maintenance=True), 'progress')
            self.assertGreater(self.family()[1], first_boundary)
            self.assertEqual(self.admit_at(None, now, maintenance=True), 'complete')
        self.assertEqual(self.family()[1], now - timedelta(hours=72))
        self.assertEqual(self.query('SELECT * FROM vehicle_events ORDER BY id'), before_events)
        self.assertEqual(self.sequence(), before_sequence)
        self.assertEqual(len([row for row in self.sessions() if row[4] is None]), 1)

    def test_closed_return_still_obeys_cause_budget(self):
        first = self.event()
        self.admit_at(first)
        self.admit_at(self.event(2, 1, cause=first.event_id))
        self.reject(self.event(3, 2, cause=first.event_id), 'causes')

    def test_large_frozen_history_does_not_enter_fast_path(self):
        # Frozen rows are outside both seed and start-range access paths.
        self.query("INSERT INTO vehicle_driver_sessions(family_id,vehicle_id,user_id,started_at,ended_at,end_reason) "
                   "SELECT 10,(SELECT id FROM vehicles ORDER BY id LIMIT 1),1,"
                   "%s::timestamptz-(n*interval '2 minutes'),%s::timestamptz-(n*interval '2 minutes')+interval '1 minute','return' "
                   'FROM generate_series(1,2000) n', (fixtures.BASE - timedelta(days=10), fixtures.BASE - timedelta(days=10)))
        self.query('UPDATE families SET vehicle_reconciliation_generation=1,vehicle_finalized_through=%s WHERE id=10',
                   (fixtures.BASE - timedelta(days=3),))
        queries = []
        with patch.object(va, '_load_replay', side_effect=AssertionError('replay')):
            self.assertEqual(self.admit_at(self.event(), queries=queries).kind, 'accepted')
        self.assertLess(len(queries), 40)
        self.assertFalse(any('DELETE FROM vehicle_driver_sessions' in sql for sql, _ in queries))

    def test_timeout_rolls_back_and_restores_caller_settings(self):
        before = self.projection(), self.snapshot()
        with patch.object(va, '_materialize', side_effect=self.pg.errors.QueryCanceled('test timeout')):
            with self.assertRaises(self.pg.errors.QueryCanceled):
                self.admit_at(self.event())
        self.assertEqual((self.projection(), self.snapshot()), before)
        with patch.object(work, 'ADMISSION_SECONDS', -1):
            with self.assertRaises(work.AdmissionDeadlineExceeded):
                self.admit_at(self.event())
        self.assertEqual((self.projection(), self.snapshot()), before)
        with self.connection() as conn:
            conn.execute("SET LOCAL lock_timeout='500ms'")
            conn.execute("SET LOCAL statement_timeout='1500ms'")
            settings = conn.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone()
            original = va._admit
            def inspect_limits(bounded, *args):
                self.assertEqual(bounded.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone(), settings)
                return original(bounded, *args)
            with patch.object(va, '_admit', side_effect=inspect_limits):
                va.admit_native_event(conn, self.users[1], self.event())
            self.assertEqual(conn.execute("SELECT current_setting('lock_timeout'),current_setting('statement_timeout')").fetchone(), settings)

    def test_real_lock_timeout_leaves_event_retryable(self):
        event = self.event()
        before = self.projection(), self.snapshot()
        with self.connection() as holder:
            holder.execute('SELECT pg_advisory_xact_lock(%s,%s)',
                           (va.CAR_TRANSITION_LOCK_NAMESPACE, 10))
            with self.assertRaises(self.pg.errors.LockNotAvailable):
                self.admit_at(event)
        self.assertEqual((self.projection(), self.snapshot()), before)
        self.assertEqual(self.admit_at(event).kind, 'accepted')

    def test_index_migration_and_large_terminal_tail(self):
        source = MIGRATION.read_text().replace('public.', self.schema + '.')
        # Local test superuser differs from Supabase's postgres; no production connection.
        source = source.replace("current_user <> 'postgres'", "current_user <> 'gemini_test'")
        source = source.replace('BEGIN;', '').replace('COMMIT;', '')
        self.query(source)
        self.admit_at(self.event())
        self.query("INSERT INTO vehicle_events(event_id,family_id,vehicle_id,user_id,device_id,source,event_type,"
                   "occurred_at,device_sequence,admission_outcome) SELECT gen_random_uuid(),10,"
                   "(SELECT id FROM vehicles ORDER BY id LIMIT 1),1,(SELECT id FROM registered_devices WHERE user_id=1),"
                   "'native','take',%s,n,'invalid_chronology' FROM generate_series(2,3000) n", (fixtures.BASE,))
        with self.connection() as conn:
            conn.execute('ANALYZE vehicle_events')
            conn.execute('SET LOCAL enable_seqscan=off')
            plan = conn.execute("EXPLAIN SELECT occurred_at FROM vehicle_events WHERE device_id=1 "
                                "AND admission_outcome='accepted' ORDER BY device_sequence DESC LIMIT 1").fetchall()
            self.assertIn('vehicle_events_device_accepted_sequence_idx', str(plan))
        self.query('UPDATE registered_devices SET last_processed_sequence=3000 WHERE user_id=1')
        self.assertEqual(self.admit_at(self.event(3001, -1)).admission_outcome, 'invalid_chronology')
        self.assertEqual(self.admit_at(self.event(3002, 1)).kind, 'accepted')
        with self.assertRaises(self.pg.errors.RaiseException):
            self.query(source)
