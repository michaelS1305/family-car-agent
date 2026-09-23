"""Real PostgreSQL reservation selection, atomic conflicts and fenced Chat replay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
from pydantic import ValidationError
from models import ReservationIntervalRequest, ReservationUpdateRequest, ReservationCancelRequest

import deletion_gate
from identity import CurrentUser
import vehicle_lifecycle as lifecycle
from tests import test_account_deletion as fixtures
from tests.test_chat_service import load_chat_service


class ReservationContractTests(unittest.TestCase):
    def test_public_payloads_reject_internal_authority(self):
        for key in ('family_id', 'vehicle_id', 'reservation_id', 'user_id', 'auth_user_id'):
            with self.assertRaises(ValidationError):
                ReservationIntervalRequest(start_time='2030-01-01T10:00:00', end_time='2030-01-01T11:00:00', **{key: 1})

    def test_opaque_and_legacy_locators_and_omitted_vs_explicit_general(self):
        fields = {'start_time': '2030-01-01T10:00:00', 'end_time': '2030-01-01T11:00:00'}
        ref = uuid4()
        omitted = ReservationUpdateRequest(**fields, reservation_ref=ref)
        general = ReservationUpdateRequest(**fields, reservation_ref=ref, vehicle_ref=None)
        self.assertNotIn('vehicle_ref', omitted.model_fields_set)
        self.assertIn('vehicle_ref', general.model_fields_set)
        self.assertEqual(ReservationCancelRequest(reservation_ref=ref).reservation_ref, ref)
        ReservationCancelRequest(original_start_time=fields['start_time'], original_end_time=fields['end_time'])
        with self.assertRaises(ValidationError):
            ReservationCancelRequest()


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class MultiCarReservationPostgresTests(unittest.TestCase):
    connection = fixtures.AccountDeletionPostgresTests.connection
    drop_schema = fixtures.AccountDeletionPostgresTests.drop_schema
    query = fixtures.AccountDeletionPostgresTests.query
    person = fixtures.AccountDeletionPostgresTests.person
    delete = fixtures.AccountDeletionPostgresTests.delete
    START = '2030-01-11T10:00:00'
    END = '2030-01-11T11:00:00'

    def setUp(self):
        fixtures.AccountDeletionPostgresTests.setUp(self)
        self.query('''ALTER TABLE reservations ADD COLUMN id serial PRIMARY KEY,
            ADD COLUMN reservation_ref uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            ADD COLUMN vehicle_id integer REFERENCES vehicles ON DELETE RESTRICT,
            ADD COLUMN start_time text, ADD COLUMN end_time text,
            ADD COLUMN status text, ADD COLUMN created_at text;
            ALTER TABLE chat_tool_actions ADD COLUMN id serial PRIMARY KEY,
            ADD COLUMN action_type text, ADD COLUMN arguments jsonb, ADD COLUMN status text,
            ADD COLUMN lease_token_at_execution uuid, ADD COLUMN result jsonb, ADD COLUMN completed_at timestamptz;
            CREATE UNIQUE INDEX one_action ON chat_tool_actions(chat_request_id);''')
        self.member = self.person(self.family)
        self.current = CurrentUser(self.creator[1], 'User', self.family, auth_user_id=self.creator[0])
        self.chat = load_chat_service()
        self.chat.pool = self.pool
        self.chat.require_user = deletion_gate.require_user
        for name in ('_lock_reservation_family', '_create_reservation_on_connection', '_update_reservation_on_connection', '_cancel_reservation_on_connection'):
            setattr(self.chat, name, getattr(self.database, name))

    def vehicle(self, family=None):
        return self.query("INSERT INTO vehicles(family_id,display_name) VALUES(%s,'Car') RETURNING vehicle_ref", (family or self.family,))[0][0]

    def create(self, **kwargs):
        return self.database.create_current_user_reservation(self.creator[1], self.family, self.START, self.END, **kwargs)

    def update(self, ref, **kwargs):
        return self.database.update_current_user_reservation(self.creator[1], self.family, None, None, '',
            self.START, self.END, reservation_ref=ref, **kwargs)

    def cancel(self, ref):
        return self.database.cancel_current_user_reservation(self.creator[1], self.family, None, None, '', reservation_ref=ref)

    def retire(self, ref):
        with self.connection() as conn:
            return lifecycle.retire_vehicle(conn, self.current, ref)

    def test_zero_one_multiple_selection_and_safe_choices(self):
        general = self.create()
        self.assertTrue(general['success'])
        self.assertIsNone(general['vehicle_ref'])
        self.assertTrue(self.cancel(general['reservation_ref'])['success'])
        first = self.vehicle()
        inferred = self.create()
        self.assertEqual(inferred['vehicle_ref'], str(first))
        self.cancel(inferred['reservation_ref'])
        second = self.vehicle()
        required = self.create()
        self.assertEqual(required['code'], 'VEHICLE_REQUIRED')
        self.assertEqual({row['vehicle_ref'] for row in required['vehicles']}, {str(first), str(second)})
        self.assertTrue(all(set(row) == {'vehicle_ref', 'display_name'} for row in required['vehicles']))
        self.assertTrue(self.create(vehicle_ref=second)['success'])

    def test_null_conflicts_both_directions_and_no_auto_backfill(self):
        general = self.create()
        self.assertEqual(self.create()['code'], 'RESERVATION_CONFLICT')
        vehicle = self.vehicle()
        self.assertEqual(self.create(vehicle_ref=vehicle)['code'], 'RESERVATION_CONFLICT')
        self.assertIsNone(self.update(general['reservation_ref'])['vehicle_ref'])
        self.cancel(general['reservation_ref'])
        specific = self.create(vehicle_ref=vehicle)
        # Retire it so a new omitted selection becomes general.
        self.retire(vehicle)
        self.assertEqual(self.create()['code'], 'RESERVATION_CONFLICT')
        self.assertEqual(self.update(specific['reservation_ref'])['vehicle_ref'], str(vehicle))

    def test_different_vehicles_overlap_same_vehicle_does_not_and_general_update(self):
        a, b = self.vehicle(), self.vehicle()
        one = self.create(vehicle_ref=a)
        two = self.create(vehicle_ref=b)
        self.assertTrue(one['success'] and two['success'])
        self.assertEqual(self.create(vehicle_ref=a)['code'], 'RESERVATION_CONFLICT')
        self.assertTrue(self.update(one['reservation_ref'])['success'])
        self.assertEqual(self.update(one['reservation_ref'], vehicle_ref=b)['code'], 'RESERVATION_CONFLICT')
        self.assertEqual(self.update(one['reservation_ref'], vehicle_ref=None)['code'], 'RESERVATION_CONFLICT')
        self.cancel(two['reservation_ref'])
        moved = self.update(one['reservation_ref'], vehicle_ref=b)
        self.assertEqual(moved['vehicle_ref'], str(b))
        self.assertEqual(moved['reservation_ref'], one['reservation_ref'])
        self.assertIsNone(self.update(one['reservation_ref'], vehicle_ref=None)['vehicle_ref'])

    def test_touching_intervals_do_not_overlap_and_jerusalem_unchanged(self):
        a = self.vehicle()
        first = self.create(vehicle_ref=a)
        second = self.database.create_current_user_reservation(self.creator[1], self.family,
            '2030-01-11T09:00:00Z', '2030-01-11T10:00:00Z', vehicle_ref=a)
        self.assertTrue(first['success'] and second['success'])
        self.assertEqual((second['start_time'], second['end_time']), ('2030-01-11T11:00:00', '2030-01-11T12:00:00'))

    def test_refs_ownership_and_legacy_ambiguity(self):
        a, b = self.vehicle(), self.vehicle()
        one, two = self.create(vehicle_ref=a), self.create(vehicle_ref=b)
        self.assertEqual(self.database.cancel_current_user_reservation(self.member[1], self.family, None, None, '', reservation_ref=one['reservation_ref'])['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
        result = self.database.cancel_current_user_reservation(self.creator[1], self.family, self.START, self.END, '')
        self.assertEqual(result['code'], 'RESERVATION_AMBIGUOUS')
        result = self.database.update_current_user_reservation(self.creator[1], self.family, self.START, self.END, '', self.START, self.END)
        self.assertEqual(result['code'], 'RESERVATION_AMBIGUOUS')
        self.assertTrue(self.cancel(one['reservation_ref'])['success'])
        self.assertTrue(self.database.cancel_current_user_reservation(self.creator[1], self.family, self.START, self.END, '')['success'])
        self.assertEqual(self.cancel(uuid4())['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(self.database.cancel_current_user_reservation(self.member[1], self.family, None, None, '', reservation_ref=two['reservation_ref'])['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')

    def test_foreign_missing_retired_and_historical_display(self):
        other = self.person()
        family = self.query("INSERT INTO families(name,family_code,created_by_user_id) VALUES('Other','def456',%s) RETURNING id", (other[1],))[0][0]
        foreign = self.vehicle(family)
        self.query('UPDATE users SET family_id=%s WHERE id=%s', (family, other[1]))
        foreign_reservation = self.database.create_current_user_reservation(other[1], family, self.START, self.END, vehicle_ref=foreign)
        self.assertEqual(self.update(foreign_reservation['reservation_ref'])['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(self.cancel(foreign_reservation['reservation_ref'])['code'], 'RESERVATION_NOT_FOUND_OR_UNAVAILABLE')
        for ref in (foreign, uuid4()):
            self.assertEqual(self.create(vehicle_ref=ref)['code'], 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE')
        a, b = self.vehicle(), self.vehicle()
        booked = self.create(vehicle_ref=a)
        self.retire(a)
        self.assertEqual(self.create(vehicle_ref=a)['code'], 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(self.update(booked['reservation_ref'], vehicle_ref=a)['vehicle_ref'], str(a))
        listing = self.database.list_family_reservations(self.family, self.creator[1], 'future', 'all', '2026-01-01')
        self.assertEqual(str(listing[0][5]), str(a))
        ai = self.database.get_ai_reservations(self.family)
        self.assertEqual(ai['items'][0]['vehicle_ref'], str(a))
        self.assertNotIn('reservation_id', ai['items'][0])
        self.assertNotIn('vehicle_id', ai['items'][0])
        self.assertTrue(self.cancel(booked['reservation_ref'])['success'])
        active = self.create(vehicle_ref=b)
        self.assertEqual(self.update(active['reservation_ref'], vehicle_ref=a)['code'], 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE')

    def race(self, calls):
        barrier = threading.Barrier(len(calls))
        def run(call):
            barrier.wait(5)
            return call()
        with ThreadPoolExecutor(len(calls)) as executor:
            return list(executor.map(run, calls))

    def test_same_vehicle_race_one_winner(self):
        a = self.vehicle()
        results = self.race([lambda: self.create(vehicle_ref=a)] * 2)
        self.assertEqual(sorted(row['code'] for row in results), ['RESERVATION_CONFLICT', 'RESERVATION_CREATED'])

    def test_different_vehicle_race_both_win(self):
        a, b = self.vehicle(), self.vehicle()
        self.assertTrue(all(row['success'] for row in self.race([lambda: self.create(vehicle_ref=a), lambda: self.create(vehicle_ref=b)])))

    def test_general_update_races_specific_create(self):
        a, b = self.vehicle(), self.vehicle()
        original = self.create(vehicle_ref=a)
        results = self.race([lambda: self.update(original['reservation_ref'], vehicle_ref=None), lambda: self.create(vehicle_ref=b)])
        self.assertEqual(sum(row['success'] for row in results), 1)

    def test_retirement_first_blocks_waiting_create(self):
        a = self.vehicle()
        with ThreadPoolExecutor(1) as executor, self.connection() as conn:
            with conn.transaction():
                lifecycle.retire_vehicle(conn, self.current, a)
                future = executor.submit(self.create, vehicle_ref=a)
            # Commit outer connection transaction before waiting for competitor.
        self.assertEqual(future.result(8)['code'], 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE')

    def test_retirement_first_blocks_reassignment_but_preserves_existing(self):
        a, b = self.vehicle(), self.vehicle()
        original = self.create(vehicle_ref=a)
        with ThreadPoolExecutor(1) as executor, self.connection() as conn:
            with conn.transaction():
                lifecycle.retire_vehicle(conn, self.current, b)
                future = executor.submit(self.update, original['reservation_ref'], vehicle_ref=b)
        self.assertEqual(future.result(8)['code'], 'VEHICLE_NOT_FOUND_OR_UNAVAILABLE')
        self.assertEqual(self.update(original['reservation_ref'])['vehicle_ref'], str(a))

    def test_create_wins_before_retirement_reservation_is_preserved(self):
        a = self.vehicle()
        with ThreadPoolExecutor(1) as executor, self.connection() as conn:
            with conn.transaction():
                deletion_gate.require_user(conn, self.creator[1])
                booked = self.database._create_reservation_on_connection(conn, self.creator[1], self.START, self.END, self.family, vehicle_ref=a)
                future = executor.submit(self.retire, a)
        self.assertIsNotNone(future.result(8).retired_at)
        self.assertEqual(self.update(booked['reservation_ref'])['vehicle_ref'], str(a))

    def chat_action(self, arguments, action='create_reservation', request=None):
        if request is None:
            lease = uuid4()
            request_id = self.query("INSERT INTO chat_requests(user_id,family_id,status,lease_token,lease_expires_at) VALUES(%s,%s,'processing',%s,clock_timestamp()+interval '120 seconds') RETURNING id", (self.creator[1], self.family, lease))[0][0]
            request = (request_id, lease)
        return self.chat._execute_mutation(*request, self.current, action, arguments), request

    def test_chat_general_inference_choice_and_durable_replay(self):
        args = {'start_time': self.START, 'end_time': self.END}
        general, request = self.chat_action(args)
        self.assertTrue(general['result']['success'])
        replay, _ = self.chat_action({}, request=request)
        self.assertTrue(replay['already_executed'])
        self.assertEqual(replay['result'], general['result'])
        self.assertEqual(self.query('SELECT count(*) FROM reservations'), [(1,)])
        self.cancel(general['result']['reservation_ref'])
        a = self.vehicle()
        inferred, _ = self.chat_action(args)
        self.assertEqual(inferred['result']['vehicle_ref'], str(a))
        self.cancel(inferred['result']['reservation_ref'])
        b = self.vehicle()
        required, request = self.chat_action(args)
        self.assertEqual(required['result']['code'], 'VEHICLE_REQUIRED')
        replay, _ = self.chat_action({**args, 'vehicle_ref': str(a)}, request=request)
        self.assertEqual(replay['result'], required['result'])
        explicit, _ = self.chat_action({**args, 'vehicle_ref': str(b)})
        ref = explicit['result']['reservation_ref']
        self.assertTrue(explicit['result']['success'])
        cancelled, _ = self.chat_action({'reservation_ref': ref}, 'cancel_reservation')
        self.assertTrue(cancelled['result']['success'])

    def test_account_deletion_cleans_associated_reservations_without_deleting_vehicle(self):
        a = self.vehicle()
        self.create(vehicle_ref=a)
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.query('SELECT count(*) FROM reservations'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(1,)])

    def test_last_member_deletion_with_vehicle_reservation_fk(self):
        a = self.vehicle()
        self.create(vehicle_ref=a)
        self.assertTrue(self.delete(self.member))
        self.assertTrue(self.delete(self.creator))
        self.assertEqual(self.query('SELECT count(*) FROM reservations'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(0,)])

    def test_chat_update_retains_or_explicitly_changes_association(self):
        a, b = self.vehicle(), self.vehicle()
        created = self.create(vehicle_ref=a)
        args = {'reservation_ref': created['reservation_ref'], 'start_time': self.START, 'end_time': self.END}
        kept, _ = self.chat_action(args, 'update_reservation')
        self.assertEqual(kept['result']['vehicle_ref'], str(a))
        moved, request = self.chat_action({**args, 'vehicle_ref': str(b)}, 'update_reservation')
        self.assertEqual(moved['result']['vehicle_ref'], str(b))
        replay, _ = self.chat_action({**args, 'vehicle_ref': None}, 'update_reservation', request)
        self.assertEqual(replay['result'], moved['result'])
        general, _ = self.chat_action({**args, 'vehicle_ref': None}, 'update_reservation')
        self.assertIsNone(general['result']['vehicle_ref'])

    def test_chat_concurrent_same_request_mutates_once(self):
        lease = uuid4()
        request_id = self.query("INSERT INTO chat_requests(user_id,family_id,status,lease_token,lease_expires_at) VALUES(%s,%s,'processing',%s,clock_timestamp()+interval '120 seconds') RETURNING id", (self.creator[1], self.family, lease))[0][0]
        args = {'start_time': self.START, 'end_time': self.END}
        results = self.race([lambda: self.chat_action(args, request=(request_id, lease))[0]] * 2)
        self.assertEqual(sorted(row['already_executed'] for row in results), [False, True])
        self.assertEqual(results[0]['result'], results[1]['result'])
        self.assertEqual(self.query('SELECT count(*) FROM reservations'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM chat_tool_actions'), [(1,)])
