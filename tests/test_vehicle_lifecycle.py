"""Lifecycle contracts and real transactions in isolated LOCAL test schemas."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError
import account_deletion as deletion
from deletion_gate import IdentityUnavailable
from identity import CurrentUser
import vehicle_admission as admission
import vehicle_lifecycle as lifecycle
from vehicle_identity import VehicleIdentityError
from tests import test_account_deletion as fixtures


class LifecycleContractTests(unittest.TestCase):
    def test_only_descriptive_vehicle_name_is_input(self):
        for field in ('id', 'family_id', 'vehicle_ref', 'created_by_user_id', 'retired_at', 'checkpoint_generation'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                lifecycle.VehicleMetadata.model_validate({'display_name': 'Car', field: 1})
        with self.assertRaises(ValidationError):
            lifecycle.VehicleMetadata(display_name=123)

    def test_registration_has_no_identity_sequence_or_revoke_input(self):
        for field in ('id', 'user_id', 'family_id', 'auth_user_id', 'device_ref', 'last_processed_sequence', 'last_seen_at', 'revoked_at'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                lifecycle.DeviceRegistration.model_validate({'platform': 'ios', field: 1})
        for platform in ('IOS', 'web', None, 1):
            with self.assertRaises(ValidationError):
                lifecycle.DeviceRegistration(platform=platform)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class LifecyclePostgresTests(unittest.TestCase):
    connection = fixtures.AccountDeletionPostgresTests.connection
    drop_schema = fixtures.AccountDeletionPostgresTests.drop_schema
    query = fixtures.AccountDeletionPostgresTests.query
    person = fixtures.AccountDeletionPostgresTests.person
    delete = fixtures.AccountDeletionPostgresTests.delete

    def setUp(self):
        fixtures.AccountDeletionPostgresTests.setUp(self)
        self.member = self.person(self.family)
        self.foreign = self.person()
        other_family = self.query("INSERT INTO families(name,family_code,created_by_user_id) VALUES('Other','xyz123',%s) RETURNING id", (self.foreign[1],))[0][0]
        self.query('UPDATE users SET family_id=%s WHERE id=%s', (other_family, self.foreign[1]))
        self.current = CurrentUser(self.creator[1], 'User', self.family, auth_user_id=self.creator[0])
        self.peer = CurrentUser(self.member[1], 'User', self.family, auth_user_id=self.member[0])
        self.outsider = CurrentUser(self.foreign[1], 'Other', other_family, auth_user_id=self.foreign[0])

    def call(self, operation, *args, user=None):
        with self.connection() as conn:
            return operation(conn, user or self.current, *args)

    def vehicle(self, user=None):
        return self.call(lifecycle.create_vehicle, {'display_name': 'רכב משפחתי'}, user=user)

    def device(self, user=None):
        return self.call(lifecycle.register_device, {'platform': 'android'}, user=user)

    def event(self, vehicle, device, seq=1, cause=None):
        now = self.query('SELECT clock_timestamp()')[0][0]
        return admission.NativeEvent(uuid4(), device.device_ref, vehicle.vehicle_ref,
            'return' if cause else 'take', now, seq, cause)

    def test_empty_lists_create_scope_safe_views_and_shared_family_vehicle(self):
        self.assertEqual(self.call(lifecycle.list_vehicles), [])
        self.assertEqual(self.call(lifecycle.list_devices), [])
        vehicle = self.vehicle(user=self.peer)
        self.assertEqual(set(vehicle.model_dump()), {'vehicle_ref', 'display_name', 'retired_at'})
        self.assertEqual(self.call(lifecycle.get_vehicle, vehicle.vehicle_ref), vehicle)
        self.assertEqual(self.call(lifecycle.list_vehicles), [vehicle])
        self.assertEqual(self.call(lifecycle.list_vehicles, user=self.outsider), [])
        self.assertEqual(self.query('SELECT family_id,created_by_user_id FROM vehicles'), [(self.family, self.member[1])])
        # No schema uniqueness requirement on name: each call is a new vehicle.
        self.assertNotEqual(self.vehicle().vehicle_ref, vehicle.vehicle_ref)

    def test_vehicle_idor_has_same_error_as_missing(self):
        vehicle = self.vehicle()
        for operation, args in ((lifecycle.get_vehicle, ()), (lifecycle.update_vehicle, ({'display_name': 'Other'},)), (lifecycle.retire_vehicle, ())):
            results = []
            for ref in (vehicle.vehicle_ref, uuid4(), 'invalid'):
                with self.assertRaises(VehicleIdentityError) as caught:
                    self.call(operation, ref, *args, user=self.outsider)
                results.append((caught.exception.code, caught.exception.status_code))
            self.assertEqual(results, [('VEHICLE_NOT_FOUND_OR_UNAVAILABLE', 404)] * 3)

    def test_names_match_database_whitespace_rule(self):
        for name in ('', ' ', '\t', '\n\r', ' \t\n\v\f '):
            with self.assertRaises(VehicleIdentityError) as caught:
                self.call(lifecycle.create_vehicle, {'display_name': name})
            self.assertEqual(caught.exception.status_code, 422)
        name = ' רכב חדש '
        vehicle = self.call(lifecycle.create_vehicle, {'display_name': name})
        self.assertEqual(vehicle.display_name, name)
        updated = self.call(lifecycle.update_vehicle, vehicle.vehicle_ref, {'display_name': 'New'}, user=self.peer)
        self.assertEqual(updated.vehicle_ref, vehicle.vehicle_ref)
        self.assertEqual(updated.display_name, 'New')

    def test_retire_is_idempotent_and_update_cannot_reactivate(self):
        vehicle = self.vehicle()
        before = self.query('SELECT clock_timestamp()')[0][0]
        retired = self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref, user=self.peer)
        self.assertGreaterEqual(retired.retired_at, before)
        self.assertEqual(self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref), retired)
        self.assertEqual(self.call(lifecycle.list_vehicles), [retired])
        renamed = self.call(lifecycle.update_vehicle, vehicle.vehicle_ref, {'display_name': 'History'})
        self.assertEqual(renamed.retired_at, retired.retired_at)
        with self.assertRaises(ValidationError):
            self.call(lifecycle.update_vehicle, vehicle.vehicle_ref, {'display_name': 'Hack', 'retired_at': None})
        device = self.device()
        result = self.call(admission.admit_native_event, self.event(vehicle, device))
        self.assertEqual((result.kind, result.admission_outcome), ('terminal', 'vehicle_retired'))

    def test_active_refused_then_return_retirement_preserves_history(self):
        vehicle, device = self.vehicle(), self.device()
        take = self.event(vehicle, device)
        self.assertEqual(self.call(admission.admit_native_event, take).kind, 'accepted')
        with self.assertRaises(VehicleIdentityError) as caught:
            self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref)
        self.assertEqual((caught.exception.code, caught.exception.status_code), ('VEHICLE_IN_USE', 409))
        self.assertEqual(self.call(admission.admit_native_event, self.event(vehicle, device, 2, take.event_id)).kind, 'accepted')
        history = self.query('SELECT * FROM vehicle_driver_sessions')
        events = self.query('SELECT * FROM vehicle_events ORDER BY id')
        self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref)
        self.assertEqual(self.query('SELECT * FROM vehicle_driver_sessions'), history)
        self.assertEqual(self.query('SELECT * FROM vehicle_events ORDER BY id'), events)

    def test_device_owner_safe_views_sequence_and_registration_limitation(self):
        device = self.device()
        self.assertEqual(set(device.model_dump()), {'device_ref', 'platform', 'revoked_at'})
        self.assertEqual(self.call(lifecycle.list_devices), [device])
        self.assertEqual(self.call(lifecycle.get_device, device.device_ref), device)
        self.assertEqual(self.call(lifecycle.list_devices, user=self.peer), [])
        self.assertEqual(self.query('SELECT user_id,last_processed_sequence FROM registered_devices'), [(self.current.user_id, 0)])
        self.assertNotEqual(self.device().device_ref, device.device_ref)
        vehicle = self.vehicle()
        self.assertEqual(self.call(admission.admit_native_event, self.event(vehicle, device)).kind, 'accepted')

    def test_other_users_cannot_resolve_or_revoke_device(self):
        device = self.device()
        for user in (self.peer, self.outsider):
            for operation in (lifecycle.get_device, lifecycle.revoke_device):
                for ref in (device.device_ref, uuid4(), 'invalid'):
                    with self.assertRaises(VehicleIdentityError) as caught:
                        self.call(operation, ref, user=user)
                    self.assertEqual(caught.exception.code, 'DEVICE_NOT_FOUND_OR_UNAVAILABLE')

    def test_revoke_idempotent_preserves_evidence_sequence_and_occupancy(self):
        vehicle, device = self.vehicle(), self.device()
        self.call(admission.admit_native_event, self.event(vehicle, device))
        events = self.query('SELECT * FROM vehicle_events')
        sessions = self.query('SELECT * FROM vehicle_driver_sessions')
        revoked = self.call(lifecycle.revoke_device, device.device_ref)
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(self.call(lifecycle.revoke_device, device.device_ref), revoked)
        self.assertEqual(self.call(lifecycle.list_devices), [revoked])
        self.assertEqual(self.call(admission.admit_native_event, self.event(vehicle, device, 2)).kind, 'unavailable')
        self.assertEqual(self.query('SELECT * FROM vehicle_events'), events)
        self.assertEqual(self.query('SELECT * FROM vehicle_driver_sessions'), sessions)
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'), [(1,)])

    def test_deleting_and_deleted_identity_cannot_mutate(self):
        vehicle, device = self.vehicle(), self.device()
        calls = ((lifecycle.create_vehicle, ({'display_name': 'X'},)),
                 (lifecycle.register_device, ({'platform': 'ios'},)),
                 (lifecycle.update_vehicle, (vehicle.vehicle_ref, {'display_name': 'X'})),
                 (lifecycle.retire_vehicle, (vehicle.vehicle_ref,)),
                 (lifecycle.revoke_device, (device.device_ref,)))
        deletion.confirm(self.pool, self.creator[0])
        for operation, args in calls:
            with self.assertRaises(IdentityUnavailable):
                self.call(operation, *args)
        self.assertTrue(deletion.cleanup(self.pool, self.creator[0]))
        for operation, args in calls:
            with self.assertRaises(IdentityUnavailable):
                self.call(operation, *args)
        self.assertEqual(self.call(lifecycle.get_vehicle, vehicle.vehicle_ref, user=self.peer), vehicle)
        self.assertEqual(self.query('SELECT created_by_user_id FROM vehicles'), [(None,)])

    def test_stale_or_mismatched_current_user_fails_closed(self):
        for user in (CurrentUser(self.current.user_id, 'X', self.outsider.family_id, auth_user_id=self.creator[0]),
                     CurrentUser(self.member[1], 'X', self.family, auth_user_id=self.creator[0]),
                     CurrentUser(self.current.user_id, 'X', None, auth_user_id=self.creator[0])):
            with self.assertRaises(VehicleIdentityError):
                self.call(lifecycle.create_vehicle, {'display_name': 'X'}, user=user)
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(0,)])

    def race_ordered(self, first, second):
        """First holds the real family lock until second has been dispatched."""
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        original = self.connection

        @contextmanager
        def held_connection():
            with original() as conn:
                class Held:
                    transaction = conn.transaction

                    def execute(inner, sql, params=None):
                        result = conn.execute(sql, params)
                        if sql.startswith('SELECT id FROM families') and threading.current_thread().name.endswith('_0'):
                            entered.set()
                            if not release.wait(5):
                                raise AssertionError('Timeout waiting for competing operation')
                        return result
                yield Held()

        def competing():
            started.set()
            return second()

        with patch.object(self, 'connection', held_connection), ThreadPoolExecutor(2, thread_name_prefix='lifecycle') as executor:
            first_result = executor.submit(first)
            self.assertTrue(entered.wait(5))
            second_result = executor.submit(competing)
            self.assertTrue(started.wait(5))
            release.set()
            return first_result.result(8), second_result.result(8)

    def test_retirement_wins_racing_take(self):
        vehicle, device = self.vehicle(), self.device()
        event = self.event(vehicle, device)
        retired, result = self.race_ordered(
            lambda: self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref),
            lambda: self.call(admission.admit_native_event, event))
        self.assertIsNotNone(retired.retired_at)
        self.assertEqual(result.admission_outcome, 'vehicle_retired')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions'), [(0,)])

    def test_revocation_wins_racing_admission(self):
        vehicle, device = self.vehicle(), self.device()
        event = self.event(vehicle, device)
        revoked, result = self.race_ordered(
            lambda: self.call(lifecycle.revoke_device, device.device_ref),
            lambda: self.call(admission.admit_native_event, event))
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(result.kind, 'unavailable')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])

    def test_create_races_deletion_then_vehicle_survives(self):
        vehicle, result = self.race_ordered(
            lambda: self.vehicle(), lambda: self.delete(self.creator))
        self.assertTrue(result)
        self.assertEqual(self.call(lifecycle.get_vehicle, vehicle.vehicle_ref, user=self.peer), vehicle)
        self.assertEqual(self.query('SELECT created_by_user_id FROM vehicles'), [(None,)])

    def test_registration_races_deletion_without_orphan(self):
        _, result = self.race_ordered(lambda: self.device(), lambda: self.delete(self.creator))
        self.assertTrue(result)
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(0,)])

    def admission_first(self, operation):
        vehicle, device = self.vehicle(), self.device()
        event = self.event(vehicle, device)
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        original = admission.reconcile

        def held(*args):
            result = original(*args)
            entered.set()  # Admission already holds family/device/vehicle locks.
            if not release.wait(5):
                raise AssertionError('Timed out waiting for competitor')
            return result

        def competing():
            started.set()
            try:
                return operation(vehicle, device)
            except VehicleIdentityError as error:
                return error.code

        with patch.object(admission, 'reconcile', side_effect=held), ThreadPoolExecutor(2) as executor:
            first = executor.submit(self.call, admission.admit_native_event, event)
            self.assertTrue(entered.wait(5))
            second = executor.submit(competing)
            self.assertTrue(started.wait(5))
            release.set()
            self.assertEqual(first.result(8).kind, 'accepted')
            return second.result(8), vehicle, device

    def test_take_wins_racing_retirement(self):
        result, vehicle, _ = self.admission_first(
            lambda vehicle, device: self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref))
        self.assertEqual(result, 'VEHICLE_IN_USE')
        self.assertIsNone(self.call(lifecycle.get_vehicle, vehicle.vehicle_ref).retired_at)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions WHERE ended_at IS NULL'), [(1,)])

    def test_take_wins_racing_revocation(self):
        revoked, vehicle, device = self.admission_first(
            lambda vehicle, device: self.call(lifecycle.revoke_device, device.device_ref))
        self.assertIsNotNone(revoked.revoked_at)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(1,)])
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'), [(1,)])
        self.assertEqual(self.call(admission.admit_native_event, self.event(vehicle, device, 2)).kind, 'unavailable')

    def test_caller_rollback_undoes_lifecycle(self):
        with self.assertRaisesRegex(RuntimeError, 'rollback'), self.connection() as conn:
            with conn.transaction():
                lifecycle.create_vehicle(conn, self.current, {'display_name': 'X'})
                lifecycle.register_device(conn, self.current, {'platform': 'ios'})
                raise RuntimeError('rollback')
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(0,)])
