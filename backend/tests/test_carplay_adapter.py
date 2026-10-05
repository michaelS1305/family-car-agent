"""Causal Shortcut ingress, using the same isolated PostgreSQL engine fixture."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import carplay_adapter as adapter
import vehicle_admission as admission
from vehicle_identity import VehicleIdentityError
from tests import test_vehicle_admission as fixtures


class ShortcutContractTests(unittest.TestCase):
    def test_request_requires_uuid4_and_rejects_trusted_identity_injection(self):
        from models import CarConnection, CarDisconnectRequest, CarPlayVehicleBindingRequest
        from pydantic import ValidationError
        from uuid import uuid1
        for model in (CarConnection, CarDisconnectRequest):
            base = dict(shortcut_token='test', latitude=31, longitude=35)
            for acquisition in (None, 'invalid', str(uuid1())):
                with self.assertRaises(ValidationError):
                    model(**base, acquisition_id=acquisition)
            with self.assertRaises(ValidationError):
                model(**base)
            for field in ('user_id', 'family_id', 'vehicle_id', 'device_sequence', 'vehicle_ref'):
                with self.assertRaises(ValidationError):
                    model(**base, acquisition_id=uuid4(), **{field: 1})
        for field in ('user_id', 'family_id', 'admin'):
            with self.assertRaises(ValidationError):
                CarPlayVehicleBindingRequest(vehicle_ref=uuid4(), **{field: 1})

    def test_native_contract_still_rejects_missing_device_sequence(self):
        from datetime import datetime, timezone
        event = admission.NativeEvent(uuid4(), None, uuid4(), 'take', datetime.now(timezone.utc), None)
        self.assertEqual(admission.admit_native_event(None, None, event).kind, 'malformed')


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class CarPlayPostgresTests(unittest.TestCase):
    connection = fixtures.VehicleAdmissionPostgresTests.connection
    drop_schema = fixtures.VehicleAdmissionPostgresTests.drop_schema
    query = fixtures.VehicleAdmissionPostgresTests.query
    sessions = fixtures.VehicleAdmissionPostgresTests.sessions

    def setUp(self):
        fixtures.VehicleAdmissionPostgresTests.setUp(self)
        self.query('CREATE TABLE carplay_vehicle_bindings(user_id integer PRIMARY KEY, '
                   'family_id integer NOT NULL, vehicle_id bigint NOT NULL, '
                   'FOREIGN KEY(user_id,family_id) REFERENCES users(id,family_id) ON DELETE CASCADE, '
                   'FOREIGN KEY(vehicle_id,family_id) REFERENCES vehicles(id,family_id) ON DELETE CASCADE)')
        self.bind()
        self.bind(user=2)

    def bind(self, user=1, vehicle=0):
        with self.connection() as conn:
            return adapter.bind_vehicle(conn, self.users[user], self.vehicles[vehicle])

    def apply(self, acquisition, user=1, disconnect=False):
        with self.connection() as conn:
            return adapter.transition(conn, self.users[user], acquisition, disconnect=disconnect)[0]

    def test_connect_return_retries_and_no_legacy_or_device_identity(self):
        acquisition = uuid4()
        self.assertEqual(self.apply(acquisition).transition, 'opened')
        self.assertEqual(self.apply(acquisition).kind, 'retry')
        self.assertEqual(self.apply(acquisition, disconnect=True).transition, 'returned')
        self.assertEqual(self.apply(acquisition, disconnect=True).kind, 'retry')
        self.assertEqual(self.query('SELECT source,device_id,device_sequence FROM vehicle_events'),
                         [('legacy_shortcut', None, None)] * 2)
        self.assertEqual(len(self.sessions()), 1)

    def test_delayed_disconnect_handover_and_reacquisition(self):
        a, b, c = uuid4(), uuid4(), uuid4()
        self.apply(a)
        self.apply(b, user=2)
        self.apply(a, disconnect=True)
        self.assertEqual([s[1] for s in self.sessions() if s[5] is None], [2])
        self.apply(c)
        self.apply(a, disconnect=True)
        self.apply(b, user=2, disconnect=True)
        self.assertEqual([s[1] for s in self.sessions() if s[5] is None], [1])
        self.apply(c, disconnect=True)
        self.assertFalse(any(s[5] is None for s in self.sessions()))

    def test_missing_cause_never_closes_current(self):
        self.apply(uuid4())
        result = self.apply(uuid4(), disconnect=True)
        self.assertEqual((result.kind, result.admission_outcome), ('terminal', 'causal_conflict'))
        self.assertEqual(len([s for s in self.sessions() if s[5] is None]), 1)

    def test_new_acquisition_without_prior_return_is_not_closed_by_old_disconnect(self):
        a, b = uuid4(), uuid4()
        self.apply(a)
        self.apply(b)
        self.assertEqual(self.apply(a, disconnect=True).kind, 'conflict')
        self.assertTrue(any(s[5] is None for s in self.sessions()))
        self.assertEqual(self.apply(b, disconnect=True).transition, 'returned')

    def test_binding_is_family_scoped_missing_and_retired_fail_closed(self):
        with self.assertRaises(VehicleIdentityError):
            self.bind(vehicle=2)
        self.query('DELETE FROM carplay_vehicle_bindings WHERE user_id=1')
        with self.assertRaises(VehicleIdentityError):
            self.apply(uuid4())
        self.bind()
        self.query('UPDATE vehicles SET retired_at=clock_timestamp() WHERE vehicle_ref=%s', (self.vehicles[0],))
        with self.assertRaises(VehicleIdentityError):
            self.apply(uuid4())
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])

    def test_parallel_retries_one_receipt_one_session(self):
        acquisition = uuid4()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.apply, [acquisition, acquisition]))
        self.assertEqual(sorted(r.kind for r in results), ['accepted', 'retry'])
        self.assertEqual(len(self.sessions()), 1)

    def test_changed_binding_cannot_redirect_acquisition(self):
        acquisition = uuid4()
        self.apply(acquisition)
        self.bind(vehicle=1)
        self.assertEqual(self.apply(acquisition).kind, 'conflict')
        self.assertEqual(self.apply(acquisition, disconnect=True).admission_outcome, 'causal_conflict')
        self.assertEqual(len([s for s in self.sessions() if s[5] is None]), 1)

    def test_deletion_gate_blocks_receipt_and_binding(self):
        from deletion_gate import IdentityUnavailable
        self.query('INSERT INTO account_deletion_jobs VALUES(%s)', (self.users[1].auth_user_id,))
        with self.assertRaises(IdentityUnavailable):
            self.apply(uuid4())
        with self.assertRaises(IdentityUnavailable):
            self.bind(vehicle=1)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])

    def test_native_and_shortcut_concurrency_share_family_lock(self):
        from datetime import timedelta
        now = self.query('SELECT clock_timestamp()')[0][0]
        event = admission.NativeEvent(uuid4(), self.devices[2], self.vehicles[0], 'take',
                                      now - timedelta(seconds=1), 1)
        def native():
            with self.connection() as conn:
                return admission.admit_native_event(conn, self.users[2], event)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(native)
            second = executor.submit(self.apply, uuid4())
            self.assertEqual(first.result().kind, 'accepted')
            self.assertEqual(second.result().kind, 'accepted')
        self.assertEqual([s[1] for s in self.sessions() if s[5] is None], [1])

    def test_retry_after_database_rollback_reuses_operation_id(self):
        from unittest.mock import patch
        acquisition = uuid4()
        with patch.object(admission, '_materialize', side_effect=RuntimeError('test rollback')):
            with self.assertRaises(RuntimeError):
                self.apply(acquisition)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])
        self.assertEqual(self.apply(acquisition).kind, 'accepted')
        self.assertEqual(self.query('SELECT event_id FROM vehicle_events'),
                         [(adapter.operation_id(self.users[1].auth_user_id, acquisition, 'take'),)])

    def test_native_handover_shares_authority(self):
        acquisition = uuid4()
        self.apply(acquisition)
        now = self.query('SELECT clock_timestamp()')[0][0]
        event = admission.NativeEvent(uuid4(), self.devices[2], self.vehicles[0], 'take', now, 1)
        with self.connection() as conn:
            self.assertEqual(admission.admit_native_event(conn, self.users[2], event).kind, 'accepted')
        self.apply(acquisition, disconnect=True)
        self.assertEqual([s[1] for s in self.sessions() if s[5] is None], [2])

    def test_outer_rollback_does_not_leave_receipt(self):
        with self.assertRaises(RuntimeError), self.connection() as conn:
            with conn.transaction():
                adapter.transition(conn, self.users[1], uuid4())
                raise RuntimeError('rollback')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])
