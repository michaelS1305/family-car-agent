"""MC-SEC-002: isolated PostgreSQL quotas, retries and transaction races."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import unittest
from uuid import uuid4

from identity import CurrentUser
from vehicle_identity import VehicleIdentityError
import vehicle_lifecycle as lifecycle
import vehicle_creation_policy as policy
from tests import test_vehicle_lifecycle as fixtures
from tests import test_account_deletion as deletion_fixtures


class CreationContracts(unittest.TestCase):
    def test_keys_are_explicit_uuid4(self):
        for value in (None, '', 'x', 1, {}, [], '00000000-0000-0000-0000-000000000000'):
            with self.assertRaises(VehicleIdentityError):
                policy.request_key(value)
        key = uuid4()
        self.assertEqual(policy.request_key(str(key)), key)

    def test_policy(self):
        self.assertEqual((policy.VEHICLES_ACTIVE, policy.VEHICLES_LIFETIME,
                          policy.DEVICES_USER_ACTIVE, policy.DEVICES_USER_LIFETIME,
                          policy.DEVICES_FAMILY_ACTIVE, policy.DEVICES_FAMILY_LIFETIME),
                         (10, 50, 5, 30, 20, 100))


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class CreationPostgresTests(unittest.TestCase):
    setUp = fixtures.LifecyclePostgresTests.setUp
    connection = fixtures.LifecyclePostgresTests.connection
    drop_schema = fixtures.LifecyclePostgresTests.drop_schema
    query = fixtures.LifecyclePostgresTests.query
    person = fixtures.LifecyclePostgresTests.person
    delete = fixtures.LifecyclePostgresTests.delete
    call = fixtures.LifecyclePostgresTests.call
    event = fixtures.LifecyclePostgresTests.event

    def create(self, key=None, name='Car', user=None):
        with self.connection() as conn:
            return lifecycle.create_vehicle(conn, user or self.current, {'display_name': name}, request_id=key or uuid4())

    def register(self, key=None, platform='ios', user=None):
        with self.connection() as conn:
            return lifecycle.register_device(conn, user or self.current, {'platform': platform}, request_id=key or uuid4())

    def expect(self, code, action):
        with self.assertRaises(VehicleIdentityError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_vehicle_active_limit_retry_rename_retirement_conflict(self):
        key = uuid4()
        first = self.create(key)
        for _ in range(9):
            self.create()
        self.expect('VEHICLE_ACTIVE_LIMIT', self.create)
        self.assertEqual(self.create(key), first)
        self.expect('CREATION_IDEMPOTENCY_CONFLICT', lambda: self.create(key, 'Different'))
        self.expect('CREATION_IDEMPOTENCY_CONFLICT', lambda: self.create(key, user=self.peer))
        self.call(lifecycle.update_vehicle, first.vehicle_ref, {'display_name': 'Renamed'})
        retired = self.call(lifecycle.retire_vehicle, first.vehicle_ref)
        self.assertEqual(self.create(key), retired)
        self.create()
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(11,)])

    def test_vehicle_lifetime_churn_exact_boundary(self):
        key = uuid4()
        for n in range(49):
            vehicle = self.create(key if n == 0 else None)
            self.call(lifecycle.retire_vehicle, vehicle.vehicle_ref)
        results = self.race([self.create, self.create])
        self.assertEqual(results.count('VEHICLE_LIFETIME_LIMIT'), 1)
        self.expect('VEHICLE_LIFETIME_LIMIT', self.create)
        self.assertIsNotNone(self.create(key).retired_at)
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(50,)])

    def test_device_user_active_retry_revocation_conflict(self):
        key = uuid4()
        first = self.register(key)
        for _ in range(4):
            self.register()
        self.expect('DEVICE_USER_ACTIVE_LIMIT', self.register)
        self.assertEqual(self.register(key), first)
        self.expect('CREATION_IDEMPOTENCY_CONFLICT', lambda: self.register(key, 'android'))
        revoked = self.call(lifecycle.revoke_device, first.device_ref)
        self.assertEqual(self.register(key), revoked)
        self.register()
        import vehicle_admission
        vehicle = self.create()
        self.assertEqual(self.call(vehicle_admission.admit_native_event, self.event(vehicle, first)).kind, 'unavailable')

    def test_device_user_lifetime_churn(self):
        key = uuid4()
        for n in range(30):
            device = self.register(key if n == 0 else None)
            self.call(lifecycle.revoke_device, device.device_ref)
        self.expect('DEVICE_USER_LIFETIME_LIMIT', self.register)
        self.assertIsNotNone(self.register(key).revoked_at)
        self.assertEqual(self.query('SELECT device_identities_created FROM families WHERE id=%s', (self.family,)), [(30,)])

    def members(self, count):
        return [CurrentUser(uid, 'Member', self.family, auth_user_id=auth)
                for auth, uid in [self.person(self.family) for _ in range(count)]]

    def test_family_active_limit(self):
        users = self.members(5)
        devices = [self.register(user=user) for user in users[:4] for _ in range(5)]
        self.expect('DEVICE_FAMILY_ACTIVE_LIMIT', lambda: self.register(user=users[4]))
        self.call(lifecycle.revoke_device, devices[0].device_ref, user=users[0])
        self.register(user=users[4])

    def test_family_lifetime_survives_member_deletion(self):
        users = self.members(4)
        key = uuid4()
        for index, user in enumerate(users):
            for n in range(24 if index == 3 else 25):
                device = self.register(key if index == n == 0 else None, user=user)
                self.call(lifecycle.revoke_device, device.device_ref, user=user)
        results = self.race([self.register, lambda: self.register(user=self.peer)])
        self.assertEqual(results.count('DEVICE_FAMILY_LIFETIME_LIMIT'), 1)
        self.assertIsNotNone(self.register(key, user=users[0]).revoked_at)
        self.expect('DEVICE_FAMILY_LIFETIME_LIMIT', self.register)
        self.assertTrue(self.delete((users[0].auth_user_id, users[0].user_id)))
        self.expect('DEVICE_FAMILY_LIFETIME_LIMIT', self.register)
        self.assertEqual(self.query('SELECT device_identities_created FROM families WHERE id=%s', (self.family,)), [(100,)])

    def race(self, actions):
        import threading
        barrier = threading.Barrier(len(actions))
        def run(action):
            barrier.wait(5)
            try:
                return action()
            except VehicleIdentityError as error:
                return error.code
        with ThreadPoolExecutor(len(actions)) as pool:
            return list(pool.map(run, actions))

    def test_concurrent_same_keys(self):
        key = uuid4()
        cars = self.race([lambda: self.create(key)] * 2)
        self.assertEqual(cars[0], cars[1])
        devices = self.race([lambda: self.register(key)] * 2)
        self.assertEqual(devices[0], devices[1])
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(1,)])
        self.assertEqual(self.query('SELECT device_identities_created FROM families WHERE id=%s', (self.family,)), [(1,)])

    def test_concurrent_vehicle_and_user_device_limits(self):
        for _ in range(9):
            self.create()
        results = self.race([self.create, self.create])
        self.assertEqual(results.count('VEHICLE_ACTIVE_LIMIT'), 1)
        for _ in range(4):
            self.register()
        results = self.race([self.register, self.register])
        self.assertEqual(results.count('DEVICE_USER_ACTIVE_LIMIT'), 1)

    def test_concurrent_family_device_limit(self):
        users = self.members(5)
        for user in users[:3]:
            for _ in range(5):
                self.register(user=user)
        for _ in range(4):
            self.register(user=users[3])
        results = self.race([lambda: self.register(user=users[3]), lambda: self.register(user=users[4])])
        self.assertEqual(results.count('DEVICE_FAMILY_ACTIVE_LIMIT'), 1)

    def test_rollback_and_independent_connection_retry(self):
        key = uuid4()
        with self.assertRaises(RuntimeError), self.connection() as conn:
            with conn.transaction():
                lifecycle.register_device(conn, self.current, {'platform': 'ios'}, request_id=key)
                raise RuntimeError('rollback')
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(0,)])
        self.assertEqual(self.query('SELECT device_identities_created FROM families WHERE id=%s', (self.family,)), [(0,)])
        original = self.register(key)
        self.assertEqual(self.register(key), original)

    def test_legacy_rows_count_and_metadata_constraints(self):
        self.query("INSERT INTO vehicles(family_id,display_name) SELECT %s,'Old' FROM generate_series(1,10)", (self.family,))
        self.expect('VEHICLE_ACTIVE_LIMIT', self.create)
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.query('UPDATE vehicles SET creation_request_id=%s', (uuid4(),))

    def test_invalid_key_and_scoped_retry_identity(self):
        for operation, payload in ((lifecycle.create_vehicle, {'display_name': 'Car'}),
                                   (lifecycle.register_device, {'platform': 'ios'})):
            for value in (None, {}, [], 'not-a-uuid'):
                with self.connection() as conn:
                    self.expect('INVALID_CREATION_REQUEST_ID',
                                lambda: operation(conn, self.current, payload, request_id=value))
        self.assertEqual(self.query('SELECT count(*) FROM vehicles'), [(0,)])
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(0,)])
        key = uuid4()
        first = self.create(key)
        other = self.create(key, user=self.outsider)
        self.assertNotEqual(first.vehicle_ref, other.vehicle_ref)
        own = self.register(key)
        peer = self.register(key, user=self.peer)
        self.assertNotEqual(own.device_ref, peer.device_ref)

    def test_lock_timeout_and_failure_after_insert_are_retryable(self):
        key = uuid4()
        with self.connection() as holder:
            from vehicle_admission import CAR_TRANSITION_LOCK_NAMESPACE
            holder.execute('SELECT pg_advisory_xact_lock(%s,%s)',
                           (CAR_TRANSITION_LOCK_NAMESPACE, self.family))
            with self.assertRaises(self.psycopg.errors.LockNotAvailable):
                self.register(key)
        with self.connection() as conn:
            error = self.psycopg.errors.QueryCanceled
            class FailCounter:
                transaction = conn.transaction

                def execute(inner, sql, params=None):
                    if sql.startswith('UPDATE families SET device_identities_created='):
                        raise error('Injected timeout')
                    return conn.execute(sql, params)
            with self.assertRaises(error):
                lifecycle.register_device(FailCounter(), self.current, {'platform': 'ios'}, request_id=key)
        self.assertEqual(self.query('SELECT count(*) FROM registered_devices'), [(0,)])
        self.assertEqual(self.query('SELECT device_identities_created FROM families WHERE id=%s', (self.family,)), [(0,)])
        self.assertEqual(self.register(key), self.register(key))


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class CreationMigrationPostgresTests(unittest.TestCase):
    setUp = deletion_fixtures.AccountDeletionPostgresTests.setUp
    connection = deletion_fixtures.AccountDeletionPostgresTests.connection
    drop_schema = deletion_fixtures.AccountDeletionPostgresTests.drop_schema
    query = deletion_fixtures.AccountDeletionPostgresTests.query
    person = deletion_fixtures.AccountDeletionPostgresTests.person

    def apply(self):
        source = (Path(__file__).resolve().parents[1] / 'supabase/manual_migrations/2026092501_vehicle_creation_bounds.sql').read_text()
        self.query(source.replace('public.', self.schema + '.').replace("current_user <> 'postgres'", "current_user <> 'gemini_test'").replace('BEGIN;', '').replace('COMMIT;', ''))

    def test_backfill_preserves_refs_revoked_rows_and_rerun_fails(self):
        old_car = self.query("INSERT INTO vehicles(family_id,display_name) VALUES(%s,'Old') RETURNING vehicle_ref", (self.family,))
        old_device = self.query("INSERT INTO registered_devices(user_id,platform,revoked_at) VALUES(%s,'ios',clock_timestamp()) RETURNING device_ref", (self.creator[1],))
        self.apply()
        self.assertEqual(self.query('SELECT vehicle_ref FROM vehicles'), old_car)
        self.assertEqual(self.query('SELECT device_ref FROM registered_devices'), old_device)
        self.assertEqual(self.query('SELECT device_identities_created FROM families'), [(1,)])
        self.assertEqual(self.query('SELECT creation_request_id,creation_fingerprint FROM registered_devices'), [(None, None)])
        with self.assertRaises(self.psycopg.errors.RaiseException):
            self.apply()
        self.assertEqual(self.query('SELECT device_identities_created FROM families'), [(1,)])

    def test_unmapped_device_backfill_fails_without_partial_columns(self):
        unmapped = self.person()
        self.query("INSERT INTO registered_devices(user_id,platform) VALUES(%s,'ios')", (unmapped[1],))
        with self.assertRaises(self.psycopg.errors.RaiseException):
            self.apply()
        self.assertEqual(self.query("SELECT count(*) FROM information_schema.columns WHERE table_schema=%s AND column_name='device_identities_created'", (self.schema,)), [(0,)])
