"""DB/network-free protocol tests. SQL concurrency/DDL still needs PostgreSQL validation."""
import copy
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

# Existing fixture imports the binding adapter without car_service/database I/O.
from tests.test_device_bindings import api, bindings
from tests.test_vehicle_api import VehicleApiTests
from vehicle_admission import NativeEvent, AdmissionResult
from vehicle_identity import VehicleIdentityError
import return_recovery as recovery

_real_verify_home = bindings.verify_home


class MemoryConnection:
    """Transactional mock, NOT an emulation/validation of PostgreSQL locks/FKs."""
    def __init__(self, now):
        self.now = now
        self.candidate = None
        self.attempts = {}
        self.receipt = False
        self.cause = True
        self.binding = True
        self.admissions = 0
        self.lock = RLock()
        self.queries = []

    @contextmanager
    def transaction(self):
        with self.lock:
            snapshot = copy.deepcopy((self.candidate, self.attempts, self.receipt, self.admissions))
            try:
                yield
            except BaseException:
                self.candidate, self.attempts, self.receipt, self.admissions = snapshot
                raise

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        row = None
        if sql.startswith('SELECT payload_fingerprint,rejection_code'):
            row = self.candidate
        elif sql.startswith('SELECT payload_fingerprint,result'):
            row = self.attempts.get(params)
        elif sql == 'SELECT clock_timestamp()':
            row = (self.now,)
        elif sql.startswith('SELECT 1 FROM vehicle_events'):
            row = (1,) if (self.cause if "event_type='take'" in sql else self.receipt) else None
        elif sql.startswith('SELECT 1 FROM registered_device_vehicle_bindings'):
            row = (1,) if self.binding else None
        elif sql.startswith('INSERT INTO return_recovery_candidates'):
            if self.candidate is None:
                self.candidate = (params[9], params[8])
        elif sql.startswith('INSERT INTO return_recovery_attempts'):
            key = params[:2]
            if key in self.attempts:
                raise AssertionError('Duplicate attempt insert')
            self.attempts[key] = (params[2], params[6].obj)
        else:
            raise AssertionError('Unexpected mock query: ' + sql)
        return Mock(fetchone=Mock(return_value=row))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        from identity import CurrentUser
        self.now = datetime(2026, 11, 22, 14, 40, tzinfo=timezone.utc)
        self.user = CurrentUser(7, 'Member', 11, auth_user_id=str(uuid4()))
        self.event = NativeEvent(uuid4(), uuid4(), uuid4(), 'return', self.now-timedelta(minutes=10), 2, uuid4())
        self.evidence = api.Return(event_id=self.event.event_id, vehicle_ref=self.event.vehicle_ref,
            device_sequence=2, occurred_at=self.event.occurred_at, take_event_id=self.event.take_event_id,
            latitude=32.0, longitude=34.0, accuracy_m=10.0, location_at=self.event.occurred_at)
        self.verification = api.ReturnVerification(invoked_at=self.now, location_at=self.now,
                                                   latitude=32.1, longitude=34.1, accuracy_m=10.0)
        self.device = (3, self.event.device_ref, 'ios', None)
        self.vehicle = (5, self.event.vehicle_ref, 'Car', None)
        self.conn = MemoryConnection(self.now)
        self.conn.candidate = (recovery.fingerprint(recovery.original(self.event, self.evidence)), 'RETURN_OUTSIDE_HOME')
        for target, value in (
            ('return_recovery._bounded_connection', lambda c: nullcontext(c)),
            ('return_recovery.lifecycle._scope', lambda c, u: c.transaction()),
            ('return_recovery.lifecycle._vehicle', Mock(return_value=self.vehicle)),
            ('vehicle_bindings._native', Mock(return_value=self.device)),
            ('vehicle_bindings.verify_home', Mock()),
            ('return_recovery.admit_native_event', Mock(side_effect=self.admit)),
        ):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def admit(self, conn, user, event):
        self.assertEqual(event, self.event)  # Original time, ID, sequence, cause unchanged.
        conn.receipt = True
        conn.admissions += 1
        return AdmissionResult('accepted', 'accepted', 'returned')

    def call(self, key=None, verification=None, evidence=None):
        return recovery.recover(self.conn, self.user, self.event, evidence or self.evidence,
                                key or uuid4(), verification or self.verification)

    def test_valid_recovery_and_identical_retry_after_expiration(self):
        key = uuid4()
        result = self.call(key)
        self.assertEqual(result['recovery_outcome'], 'recovered')
        self.conn.now += timedelta(days=4)
        self.assertEqual(self.call(key), result)
        self.assertEqual(self.conn.admissions, 1)
        self.assertEqual(len(self.conn.attempts), 1)

    def test_changed_verification_under_same_id_conflicts(self):
        key = uuid4()
        self.call(key)
        result = self.call(key, self.verification.model_copy(update={'latitude': 33.0}))
        self.assertEqual(result.code, 'RETURN_RECOVERY_IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.conn.admissions, 1)

    def test_concurrent_identical_attempts_and_distinct_attempts(self):
        key = uuid4()
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.call(key), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.conn.admissions, 1)
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_NOT_ELIGIBLE')

    def test_original_evidence_cannot_be_changed(self):
        for field, value in [('latitude', 33.0), ('accuracy_m', 11.0),
                             ('location_at', self.now)]:
            result = self.call(evidence=self.evidence.model_copy(update={field: value}))
            self.assertEqual(result.code, 'RETURN_RECOVERY_EVIDENCE_MISMATCH')
        self.assertEqual(self.conn.admissions, 0)

    def test_missing_legacy_proof_and_ineligible_candidate(self):
        self.conn.candidate = None
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_LEGACY_UNVERIFIED')
        self.conn.candidate = ('bad', 'RETURN_LOCATION_INVALID')
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_EVIDENCE_MISMATCH')
        self.conn.candidate = (recovery.fingerprint(recovery.original(self.event, self.evidence)), 'OTHER')
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_NOT_ELIGIBLE')

    def test_freshness_and_delivery_boundaries(self):
        for change in ({'location_at': self.now-timedelta(seconds=31)},
                       {'invoked_at': self.now+timedelta(seconds=1)},
                       {'location_at': self.now+timedelta(seconds=1)},
                       {'location_at': self.now-timedelta(seconds=121),
                        'invoked_at': self.now-timedelta(seconds=121)}):
            result = self.call(verification=self.verification.model_copy(update=change))
            self.assertEqual(result.code, 'RETURN_RECOVERY_VERIFICATION_EXPIRED')
        result = self.call(verification=self.verification.model_copy(update={
            'invoked_at': self.now-timedelta(seconds=120), 'location_at': self.now-timedelta(seconds=150)}))
        self.assertEqual(result['kind'], 'accepted')

    def test_invalid_home_is_persisted_without_admission(self):
        for code in recovery.HOME_CODES:
            key = uuid4()
            with patch.object(bindings, 'verify_home', side_effect=VehicleIdentityError(code, 'Home unavailable', 409)):
                self.assertEqual(self.call(key).code, code)
            self.assertEqual(self.call(key).code, code)  # Retry does not reinterpret prior evidence.
        self.assertEqual(self.conn.admissions, 0)

    def test_missing_take_binding_and_revocation(self):
        self.conn.cause = False
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_NOT_ELIGIBLE')
        self.conn.cause = True
        self.conn.binding = False
        self.assertEqual(self.call().code, 'RETURN_RECOVERY_NOT_ELIGIBLE')
        with patch.object(bindings, '_native', return_value=(*self.device[:3], self.now)):
            with self.assertRaises(VehicleIdentityError):
                self.call()

    def test_ordering_checkpoint_and_correction_window_refusals_rollback(self):
        for kind, outcome in [('gap', None), ('conflict', None), ('terminal', 'invalid_chronology'),
                              ('terminal', 'before_finalized_boundary'), ('terminal', 'causal_conflict'),
                              ('terminal', 'reconciliation_policy_exceeded')]:
            def rejected(conn, user, event):
                conn.receipt = True  # Model admission's terminal receipt side effect.
                return AdmissionResult(kind, outcome)
            with patch.object(recovery, 'admit_native_event', side_effect=rejected):
                self.assertEqual(self.call().code, 'RETURN_RECOVERY_ORDER_CONFLICT')
            self.assertFalse(self.conn.receipt)

    def test_failed_attempt_write_rolls_back_admission(self):
        execute = self.conn.execute
        def fail(sql, params=()):
            if sql.startswith('INSERT INTO return_recovery_attempts'):
                raise RuntimeError('simulated interruption')
            return execute(sql, params)
        with patch.object(self.conn, 'execute', side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.call()
        self.assertFalse(self.conn.receipt)
        self.assertEqual(self.conn.attempts, {})

    def test_record_only_home_rejections_and_valid_causes(self):
        self.conn.candidate = None
        for code in recovery.HOME_CODES:
            result = recovery.record_rejection(self.conn, self.user, self.event, self.evidence,
                self.device, self.vehicle, VehicleIdentityError(code, 'Home unavailable', 409))
            self.assertEqual(result.code, code)
            self.assertIsNotNone(self.conn.candidate)
        with self.assertRaises(VehicleIdentityError):
            recovery.record_rejection(self.conn, self.user, self.event, self.evidence,
                self.device, self.vehicle, VehicleIdentityError('RETURN_LOCATION_INVALID', 'Invalid', 422))
        self.conn.candidate = None
        self.conn.cause = False
        recovery.record_rejection(self.conn, self.user, self.event, self.evidence,
            self.device, self.vehicle, VehicleIdentityError('RETURN_OUTSIDE_HOME', 'Home unavailable', 409))
        self.assertIsNone(self.conn.candidate)

    def test_verification_gps_is_not_persisted(self):
        self.call()
        sql, params = next(q for q in self.conn.queries if q[0].startswith('INSERT INTO return_recovery_attempts'))
        self.assertNotIn('latitude', sql)
        self.assertNotIn(self.verification.latitude, params)
        self.assertNotIn('latitude', str(params[-1].obj))

    def test_normal_return_records_home_error_inside_transaction(self):
        self.conn.candidate = None
        with patch.object(bindings, '_bounded_connection', side_effect=lambda c: nullcontext(c)), \
                patch.object(bindings, 'verify_home', side_effect=VehicleIdentityError(
                    'RETURN_OUTSIDE_HOME', 'Home verification failed', 409)):
            with self.conn.transaction():
                result = bindings.admit_return(self.conn, self.user, self.event, self.evidence, record_rejection=True)
            self.assertEqual(result.code, 'RETURN_OUTSIDE_HOME')
            self.assertIsNotNone(self.conn.candidate)
            self.assertFalse(self.conn.receipt)

    def test_take_return_rejection_then_corrected_recovery(self):
        # Accepted TAKE is the mock's server-owned cause; normal RETURN must commit
        # its candidate before exposing HTTP 409, then use separate verification.
        self.conn.candidate = None
        pool = Mock()
        @contextmanager
        def connection():
            with self.conn.transaction():
                yield self.conn
        pool.connection.side_effect = connection
        with patch.object(bindings, '_bounded_connection', side_effect=lambda c: nullcontext(c)), \
                patch.object(bindings, 'verify_home', side_effect=VehicleIdentityError(
                    'RETURN_OUTSIDE_HOME', 'Home verification failed', 409)):
            with self.assertRaises(api.HTTPException) as error:
                api.return_event(self.event.device_ref, self.evidence, api.Response(), self.user, pool)
        self.assertEqual(error.exception.status_code, 409)
        self.assertIsNotNone(self.conn.candidate)
        self.assertFalse(self.conn.receipt)
        self.assertEqual(self.call()['recovery_outcome'], 'recovered')
        self.assertTrue(self.conn.receipt)

    def test_home_distance_includes_accuracy_and_boundary(self):
        conn = Mock()
        conn.execute.return_value.fetchone.return_value = (32.1, 34.1)
        for distance, allowed in ((490.0, True), (490.01, False), (float('nan'), False)):
            with patch.object(bindings, 'calculate_distance_meters', return_value=distance):
                if allowed:
                    _real_verify_home(conn, self.user, self.verification)
                else:
                    with self.assertRaises(VehicleIdentityError) as error:
                        _real_verify_home(conn, self.user, self.verification)
                    self.assertEqual(error.exception.code, 'RETURN_OUTSIDE_HOME')
        conn.execute.return_value.fetchone.return_value = (None, None)
        with self.assertRaises(VehicleIdentityError) as error:
            _real_verify_home(conn, self.user, self.verification)
        self.assertEqual(error.exception.code, 'RETURN_HOME_UNAVAILABLE')

    def test_ownership_is_checked_before_cached_outcome(self):
        key = uuid4()
        self.call(key)
        with patch.object(bindings, '_native', side_effect=VehicleIdentityError('DEVICE_NOT_FOUND', 'Unavailable')):
            with self.assertRaises(VehicleIdentityError):
                self.call(key)
        query, params = next(q for q in self.conn.queries if q[0].startswith('SELECT payload_fingerprint,rejection_code'))
        self.assertEqual(params, (self.event.event_id, self.user.user_id, self.user.family_id,
                                  self.device[0], self.vehicle[0]))


class RecoveryApiTests(unittest.TestCase):
    def setUp(self):
        VehicleApiTests.setUp(self)
        self.app.include_router(api.router)

    def test_refusal_is_raised_only_after_pool_commit(self):
        with patch.object(bindings, 'admit_return', return_value=recovery.Refusal(
                'RETURN_OUTSIDE_HOME', 'Home verification failed')):
            body = dict(event_id=str(uuid4()), vehicle_ref=str(uuid4()), device_sequence=2,
                take_event_id=str(uuid4()), occurred_at='2026-11-22T14:30:00Z',
                location_at='2026-11-22T14:30:00Z', latitude=32.0, longitude=34.0, accuracy_m=10.0)
            response = self.client.post('/api/devices/'+str(uuid4())+'/events/return', json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'RETURN_OUTSIDE_HOME')
        self.pool.connection.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_strict_verification_contract(self):
        for accuracy in (0, 101, float('inf')):
            with self.assertRaises(ValueError):
                api.ReturnVerification(invoked_at='2026-11-22T14:40:00Z', location_at='2026-11-22T14:40:00Z',
                    latitude=32.0, longitude=34.0, accuracy_m=accuracy)

    def test_recovery_route_contract_and_authentication(self):
        event_id, device_ref = uuid4(), uuid4()
        original = dict(event_id=str(event_id), vehicle_ref=str(uuid4()), device_sequence=2,
            take_event_id=str(uuid4()), occurred_at='2026-11-22T14:30:00Z',
            location_at='2026-11-22T14:30:00Z', latitude=32.0, longitude=34.0, accuracy_m=10.0)
        body = dict(recovery_id=str(uuid4()), original_return=original,
            verification=dict(invoked_at='2026-11-22T14:40:00Z', location_at='2026-11-22T14:40:00Z',
                              latitude=32.1, longitude=34.1, accuracy_m=10.0))
        path = f'/api/devices/{device_ref}/events/return/{event_id}/recovery'
        with patch.object(recovery, 'recover', return_value={'kind': 'accepted'}) as recover:
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(recover.call_args.args[2].event_id, event_id)
            self.assertEqual(recover.call_args.args[2].device_ref, device_ref)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(self.client.post(path, json={**body, 'rejection_code': 'RETURN_OUTSIDE_HOME'}).status_code, 422)
            self.assertEqual(self.client.post(path.replace(str(event_id), str(uuid4())), json=body).status_code, 409)
        self.app.dependency_overrides[api.get_current_user] = lambda: (_ for _ in ()).throw(api.HTTPException(401))
        self.assertEqual(self.client.post(path, json=body).status_code, 401)

    def test_commit_failure_does_not_return_success_or_refusal(self):
        self.pool.connection.return_value.__exit__.side_effect = RuntimeError('simulated commit failure')
        with self.assertRaises(RuntimeError):
            api.run(self.pool, api.Response(), lambda c: recovery.refused('NOT_ELIGIBLE'))

    def test_migration_deletion_and_immutability_contract(self):
        root = Path(__file__).resolve().parents[2]
        sql = (root/'supabase/manual_migrations/2026112201_return_recovery.sql').read_text()
        self.assertIn('REFERENCES public.vehicle_events(event_id, user_id, vehicle_id, family_id) ON DELETE CASCADE', sql)
        self.assertIn('REFERENCES public.return_recovery_candidates(event_id) ON DELETE CASCADE', sql)
        self.assertIn('UNIQUE (device_id, device_sequence)', sql)
        self.assertIn('PRIMARY KEY (event_id, recovery_id)', sql)
        self.assertIn('BEFORE UPDATE ON public.return_recovery_candidates', sql)
        self.assertIn('FROM PUBLIC, anon, authenticated', sql)
        self.assertNotIn('ALTER TABLE public.vehicle_events', sql)
        self.assertIn('DELETE FROM vehicle_events WHERE user_id=%s', (root/'backend/account_deletion.py').read_text())


if __name__ == '__main__':
    unittest.main()
