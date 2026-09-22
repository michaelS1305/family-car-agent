"""Vehicle checkpoints through the real account-cleanup transaction (local PG)."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import account_deletion as deletion
from identity import CurrentUser
import vehicle_admission as admission
from tests import test_account_deletion as fixtures


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class VehicleDeletionPostgresTests(unittest.TestCase):
    setUp = fixtures.AccountDeletionPostgresTests.setUp
    connection = fixtures.AccountDeletionPostgresTests.connection
    drop_schema = fixtures.AccountDeletionPostgresTests.drop_schema
    query = fixtures.AccountDeletionPostgresTests.query
    person = fixtures.AccountDeletionPostgresTests.person
    delete = fixtures.AccountDeletionPostgresTests.delete

    def setup_vehicle(self):
        self.member = self.person(self.family)
        self.vehicle = self.query(
            "INSERT INTO vehicles(family_id,created_by_user_id,display_name) VALUES(%s,%s,'Car') RETURNING vehicle_ref",
            (self.family, self.creator[1]))[0][0]
        self.devices = {}
        for person in (self.creator, self.member):
            self.devices[person[1]] = self.query(
                "INSERT INTO registered_devices(user_id,platform) VALUES(%s,'ios') RETURNING device_ref",
                (person[1],))[0][0]
        self.now = self.query('SELECT clock_timestamp()')[0][0]

    def native(self, person, seconds=-60, seq=1, cause=None):
        return admission.NativeEvent(uuid4(), self.devices[person[1]], self.vehicle,
            'return' if cause else 'take', self.now + timedelta(seconds=seconds), seq, cause)

    def admit(self, person, event):
        with self.connection() as conn:
            return admission.admit_native_event(conn,
                CurrentUser(person[1], 'User', self.family, auth_user_id=person[0]), event)

    def checkpoint(self):
        return self.query('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=%s', (self.family,))[0]

    def active(self):
        return self.query('SELECT user_id FROM vehicle_driver_sessions WHERE ended_at IS NULL')

    def test_survivor_seed_return_and_second_checkpoint(self):
        self.setup_vehicle()
        take = self.native(self.member)
        self.assertEqual(self.admit(self.member, take).kind, 'accepted')
        ref = self.query('SELECT session_ref FROM vehicle_driver_sessions')[0][0]
        self.assertTrue(self.delete(self.creator))
        generation, boundary = self.checkpoint()
        self.assertEqual(generation, 1)
        self.assertEqual(self.active(), [(self.member[1],)])
        self.assertEqual(self.query('SELECT checkpoint_generation,session_ref FROM vehicle_driver_sessions'), [(1, ref)])
        self.assertEqual(self.query('SELECT created_by_user_id FROM vehicles'), [(None,)])
        self.assertEqual(self.query('SELECT user_id FROM registered_devices'), [(self.member[1],)])
        self.assertTrue(deletion.cleanup(self.pool, self.creator[0]))
        self.assertEqual(self.checkpoint(), (generation, boundary))
        returned = self.native(self.member, seconds=1, seq=2, cause=take.event_id)
        self.assertEqual(self.admit(self.member, returned).kind, 'accepted')
        self.assertEqual(self.active(), [])
        self.assertEqual(self.query('SELECT checkpoint_generation FROM vehicle_driver_sessions'), [(1,)])
        # Replay includes a carried-in seed even after its session ended.
        self.assertEqual(self.admit(self.member, self.native(self.member, seconds=2, seq=3)).kind, 'accepted')
        another = self.person(self.family)
        self.assertTrue(self.delete(another))
        self.assertEqual(self.checkpoint()[0], 2)
        self.assertEqual(self.active(), [(self.member[1],)])

    def test_future_handover_never_resurrects_survivor(self):
        self.setup_vehicle()
        dad = self.native(self.member, seconds=60)
        michael = self.native(self.creator, seconds=120)
        self.assertEqual(self.admit(self.member, dad).kind, 'accepted')
        self.assertEqual(self.admit(self.creator, michael).kind, 'accepted')
        self.assertTrue(self.delete(self.creator))
        self.assertGreaterEqual(self.checkpoint()[1], michael.occurred_at)
        self.assertEqual(self.active(), [])
        self.assertEqual(self.query('SELECT ended_at,end_event_id,end_reason FROM vehicle_driver_sessions'),
                         [(michael.occurred_at, None, 'handover')])
        self.assertEqual(self.query('SELECT event_type FROM vehicle_events'), [('take',)])
        old = self.native(self.member, seconds=120, seq=2)
        self.assertEqual(self.admit(self.member, old).admission_outcome, 'before_finalized_boundary')
        late_return = self.native(self.member, seconds=121, seq=3, cause=dad.event_id)
        self.assertEqual(self.admit(self.member, late_return).kind, 'accepted')
        self.assertEqual(self.active(), [])
        self.assertEqual(self.admit(self.creator, michael).kind, 'unavailable')
        self.assertEqual(self.admit(self.member, self.native(self.member, seconds=122, seq=4)).kind, 'accepted')
        self.assertEqual(self.active(), [(self.member[1],)])

    def test_pre_guard_future_evidence_is_enclosed(self):
        self.setup_vehicle()
        future = self.now + timedelta(days=365)
        event_id = uuid4()
        self.query("INSERT INTO vehicle_events(event_id,family_id,vehicle_id,user_id,source,event_type,occurred_at,admission_outcome) "
                   "SELECT %s,%s,id,%s,'legacy_shortcut','take',%s,'accepted' FROM vehicles",
                   (event_id, self.family, self.member[1], future))
        self.query('INSERT INTO vehicle_driver_sessions(family_id,vehicle_id,user_id,started_at,start_event_id) '
                   'SELECT %s,id,%s,%s,%s FROM vehicles', (self.family, self.member[1], future, event_id))
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.checkpoint()[1], future)
        self.assertEqual(self.query('SELECT occurred_at FROM vehicle_events'), [(future,)])
        self.assertEqual(self.active(), [(self.member[1],)])
        self.assertEqual(self.query('SELECT checkpoint_generation FROM vehicle_driver_sessions'), [(1,)])
        event = self.native(self.member, seconds=600)
        self.assertEqual(self.admit(self.member, event).kind, 'future_clock_skew')
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'), [(0,)])

    def test_last_member_cleanup_and_fk_order(self):
        self.setup_vehicle()
        self.assertEqual(self.admit(self.creator, self.native(self.creator)).kind, 'accepted')
        self.assertTrue(self.delete(self.member))
        self.assertTrue(self.delete(self.creator))
        for table in ('families', 'vehicles', 'registered_devices', 'vehicle_events', 'vehicle_driver_sessions', 'users'):
            self.assertEqual(self.query(f'SELECT count(*) FROM {table}'), [(0,)], table)

    def test_failure_after_checkpoint_and_cleanup_rolls_back(self):
        self.setup_vehicle()
        self.assertEqual(self.admit(self.member, self.native(self.member)).kind, 'accepted')
        self.assertEqual(self.admit(self.creator, self.native(self.creator, seconds=-30)).kind, 'accepted')
        deletion.confirm(self.pool, self.creator[0])
        tables = ('families', 'vehicle_events', 'vehicle_driver_sessions', 'registered_devices')
        before = [self.query(f'SELECT * FROM {table} ORDER BY id') for table in tables]
        self.query('CREATE TABLE injected_blocker(user_id integer REFERENCES users)')
        self.query('INSERT INTO injected_blocker VALUES(%s)', (self.creator[1],))
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            deletion.cleanup(self.pool, self.creator[0])
        self.assertEqual([self.query(f'SELECT * FROM {table} ORDER BY id') for table in tables], before)
        self.assertEqual(self.query('SELECT phase FROM account_deletion_jobs'), [('draining',)])
        self.query('DELETE FROM injected_blocker')
        self.assertTrue(deletion.cleanup(self.pool, self.creator[0]))
        self.assertEqual(self.checkpoint()[0], 1)
        self.assertEqual(self.active(), [])

    def test_failures_at_each_vehicle_cleanup_stage_are_atomic(self):
        self.setup_vehicle()
        self.assertEqual(self.admit(self.creator, self.native(self.creator)).kind, 'accepted')
        deletion.confirm(self.pool, self.creator[0])
        tables = ('families', 'vehicle_events', 'vehicle_driver_sessions', 'registered_devices')
        before = [self.query(f'SELECT * FROM {table} ORDER BY id') for table in tables]
        original = self.connection
        for prefix in ('UPDATE families SET vehicle_reconciliation_generation=',
                       'UPDATE vehicle_driver_sessions SET checkpoint_generation=',
                       'DELETE FROM vehicle_events WHERE user_id=',
                       'DELETE FROM registered_devices WHERE user_id='):
            @contextmanager
            def failing_connection():
                with original() as conn:
                    class Failing:
                        def execute(inner, sql, params=None):
                            result = conn.execute(sql, params)
                            if sql.startswith(prefix):
                                raise RuntimeError('Injected transaction failure')
                            return result
                    yield Failing()
            with patch.object(self.pool, 'connection', failing_connection):
                with self.assertRaisesRegex(RuntimeError, 'Injected'):
                    deletion.cleanup(self.pool, self.creator[0])
            self.assertEqual([self.query(f'SELECT * FROM {table} ORDER BY id') for table in tables], before)
        self.assertTrue(deletion.cleanup(self.pool, self.creator[0]))
        self.assertEqual(self.checkpoint()[0], 1)

    def test_deletion_wins_then_take_and_return_cannot_mutate(self):
        self.setup_vehicle()
        take = self.native(self.creator)
        self.assertEqual(self.admit(self.creator, take).kind, 'accepted')
        deletion.confirm(self.pool, self.creator[0])
        entered, release = threading.Event(), threading.Event()
        original = deletion._checkpoint_vehicle_identity

        def paused(*args):
            original(*args)
            entered.set()
            if not release.wait(5):
                raise AssertionError('Synchronization timed out')

        with patch.object(deletion, '_checkpoint_vehicle_identity', side_effect=paused), ThreadPoolExecutor(3) as executor:
            deleting = executor.submit(deletion.cleanup, self.pool, self.creator[0])
            self.assertTrue(entered.wait(5))
            pending = [executor.submit(self.admit, self.creator, event) for event in (
                self.native(self.creator, seconds=1, seq=2),
                self.native(self.creator, seconds=1, seq=2, cause=take.event_id))]
            release.set()
            self.assertTrue(deleting.result(8))
            self.assertEqual([result.result(8).kind for result in pending], ['unavailable', 'unavailable'])
        self.assertEqual(self.active(), [])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])

    def test_existing_later_boundary_never_moves_backwards(self):
        self.setup_vehicle()
        boundary = self.now + timedelta(days=2)
        self.query('UPDATE families SET vehicle_reconciliation_generation=8,vehicle_finalized_through=%s WHERE id=%s', (boundary, self.family))
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.checkpoint(), (9, boundary))

    def test_other_vehicle_and_redundant_take_alias_survive(self):
        self.setup_vehicle()
        other = self.query("INSERT INTO vehicles(family_id,display_name) VALUES(%s,'Other') RETURNING vehicle_ref", (self.family,))[0][0]
        take = self.native(self.member, seconds=-90)
        alias = self.native(self.member, seconds=-80, seq=2)
        for event in (take, alias):
            self.assertEqual(self.admit(self.member, event).kind, 'accepted')
        deleting_take = replace(self.native(self.creator, seconds=-70), vehicle_ref=other)
        self.assertEqual(self.admit(self.creator, deleting_take).kind, 'accepted')
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.active(), [(self.member[1],)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(2,)])
        returned = self.native(self.member, seconds=1, seq=3, cause=alias.event_id)
        self.assertEqual(self.admit(self.member, returned).kind, 'accepted')
        self.assertEqual(self.active(), [])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events WHERE user_id=%s', (self.creator[1],)), [(0,)])

    def test_admission_wins_identity_fence_then_deletion_take_and_return(self):
        self.setup_vehicle()
        for is_return in (False, True):
            # A fresh family member per case; actual shared/exclusive identity
            # locks order the transactions. Events synchronize without sleeps.
            person = self.person(self.family)
            self.devices[person[1]] = self.query("INSERT INTO registered_devices(user_id,platform) VALUES(%s,'ios') RETURNING device_ref", (person[1],))[0][0]
            second = 4 if is_return else 1
            take = self.native(person, seconds=second)
            if is_return:
                self.assertEqual(self.admit(person, take).kind, 'accepted')
            event = self.native(person, seconds=second + 1, seq=2, cause=take.event_id) if is_return else take
            entered, release = threading.Event(), threading.Event()
            original = admission.require_auth

            def fenced(*args):
                original(*args)
                entered.set()
                if not release.wait(5):
                    raise AssertionError('Synchronization timed out')

            with patch.object(admission, 'require_auth', side_effect=fenced), ThreadPoolExecutor(2) as executor:
                admit = executor.submit(self.admit, person, event)
                self.assertTrue(entered.wait(5))
                deleting = executor.submit(self.delete, person)
                release.set()
                self.assertEqual(admit.result(8).kind, 'accepted')
                self.assertTrue(deleting.result(8))
            self.assertEqual(self.admit(person, event).kind, 'unavailable')
            self.assertEqual(self.query('SELECT count(*) FROM vehicle_events WHERE user_id=%s', (person[1],)), [(0,)])
            self.assertEqual(self.active(), [])
