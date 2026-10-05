import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity import CurrentUser
from vehicle_identity import VehicleView, VehicleIdentityError
import vehicle_api as api
from tests import test_vehicle_lifecycle as fixtures


class VehicleApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(api.router)
        self.user = CurrentUser(7, 'Member', 11, auth_user_id=str(uuid4()))
        self.pool = Mock()
        self.pool.connection.return_value.__enter__ = Mock(return_value=Mock())
        self.pool.connection.return_value.__exit__ = Mock(return_value=False)
        app.dependency_overrides[api.get_current_user] = lambda: self.user
        app.dependency_overrides[api.vehicle_pool] = lambda: self.pool
        self.app = app
        self.client = TestClient(app)

    def test_creation_passes_only_current_user_name_and_stable_key(self):
        ref, key = uuid4(), uuid4()
        with patch.object(api.lifecycle, 'create_vehicle', return_value=VehicleView(
                vehicle_ref=ref, display_name='Hyundai', retired_at=None)) as create:
            response = self.client.post('/api/vehicles', json={'display_name': 'Hyundai', 'request_id': str(key)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'vehicle_ref', 'display_name', 'retired_at'})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(create.call_args.args[1:], (self.user, {'display_name': 'Hyundai'}))
        self.assertEqual(create.call_args.kwargs, {'request_id': key})

    def test_identity_injection_and_missing_key_rejected_before_lifecycle(self):
        with patch.object(api.lifecycle, 'create_vehicle') as create:
            for extra in ({'family_id': 22}, {'user_id': 1}, {'vehicle_ref': str(uuid4())}):
                self.assertEqual(self.client.post('/api/vehicles', json={
                    'display_name': 'Car', 'request_id': str(uuid4()), **extra}).status_code, 422)
            self.assertEqual(self.client.post('/api/vehicles', json={'display_name': 'Car'}).status_code, 422)
            create.assert_not_called()

    def test_quota_and_conflict_are_structured(self):
        for code in ('VEHICLE_ACTIVE_LIMIT', 'VEHICLE_LIFETIME_LIMIT', 'CREATION_IDEMPOTENCY_CONFLICT'):
            with patch.object(api.lifecycle, 'create_vehicle', side_effect=VehicleIdentityError(code, 'Limit', 409)):
                response = self.client.post('/api/vehicles', json={'display_name': 'Car', 'request_id': str(uuid4())})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['detail']['code'], code)

    def test_routes_require_authenticated_identity(self):
        from fastapi import HTTPException
        def denied():
            raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user] = denied
        self.assertEqual(self.client.get('/api/vehicles').status_code, 401)
        self.assertEqual(self.client.get('/api/vehicles/' + str(uuid4())).status_code, 401)
        self.assertEqual(self.client.post('/api/vehicles', json={}).status_code, 401)


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class VehicleApiPostgresTests(unittest.TestCase):
    setUp = fixtures.LifecyclePostgresTests.setUp
    connection = fixtures.LifecyclePostgresTests.connection
    drop_schema = fixtures.LifecyclePostgresTests.drop_schema
    query = fixtures.LifecyclePostgresTests.query
    person = fixtures.LifecyclePostgresTests.person
    call = fixtures.LifecyclePostgresTests.call
    vehicle = fixtures.LifecyclePostgresTests.vehicle
    device = fixtures.LifecyclePostgresTests.device
    event = fixtures.LifecyclePostgresTests.event

    def test_zero_one_many_retired_and_family_isolation(self):
        with self.connection() as conn:
            self.assertEqual(api._read(conn, self.current), [])
        first, second = self.vehicle(), self.vehicle()
        self.vehicle(user=self.outsider)
        with self.connection() as conn:
            rows = api._read(conn, self.current)
            self.assertEqual({row.vehicle_ref for row in rows}, {first.vehicle_ref, second.vehicle_ref})
            self.assertTrue(all(not row.in_use for row in rows))
            with self.assertRaises(VehicleIdentityError):
                api._read(conn, self.outsider, first.vehicle_ref)
        self.call(api.lifecycle.retire_vehicle, first.vehicle_ref)
        with self.connection() as conn:
            self.assertEqual([v.vehicle_ref for v in api._read(conn, self.current)], [second.vehicle_ref])
            with self.assertRaises(VehicleIdentityError):
                api._read(conn, self.current, first.vehicle_ref)

    def test_status_uses_real_sessions_and_exposes_no_internal_ids(self):
        import vehicle_admission
        vehicle, device = self.vehicle(), self.device()
        self.call(vehicle_admission.admit_native_event, self.event(vehicle, device))
        with self.connection() as conn:
            row = api._read(conn, self.current, vehicle.vehicle_ref)[0]
        self.assertTrue(row.in_use)
        self.assertIsNotNone(row.current_driver)
        self.assertEqual(set(row.model_dump()), {'vehicle_ref', 'display_name', 'retired_at', 'current_driver', 'in_use'})
