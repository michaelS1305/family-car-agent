import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from identity import CurrentUser
from vehicle_identity import VehicleDetailsView as VehicleView, VehicleIdentityError
import vehicle_api as api
from tests import test_vehicle_lifecycle as fixtures

VEHICLE_FIELDS = {'vehicle_ref', 'display_name', 'retired_at', 'created_at', 'category',
                  'manufacturer_id', 'manufacturer_name_he', 'model', 'license_plate'}
CREATED = datetime(2026, 10, 13, tzinfo=timezone.utc)


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
                vehicle_ref=ref, display_name='Hyundai', retired_at=None, created_at=CREATED)) as create:
            response = self.client.post('/api/vehicles', json={'display_name': 'Hyundai', 'request_id': str(key)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), VEHICLE_FIELDS)
        for field in ('category', 'manufacturer_id', 'manufacturer_name_he', 'model', 'license_plate'):
            self.assertIsNone(response.json()[field])
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

    def test_current_status_preserves_independent_session_times_and_public_fields(self):
        vehicles = [VehicleView(vehicle_ref=uuid4(), display_name=name, retired_at=None, created_at=CREATED)
                    for name in ('Available', 'First', 'Second')]
        times = [datetime(2026, 10, 12, 10, tzinfo=timezone.utc),
                 datetime(2026, 10, 12, 14, tzinfo=timezone(timedelta(hours=3)))]
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = [
            (vehicles[1].vehicle_ref, 'One', times[0]),
            (vehicles[2].vehicle_ref, 'Two', times[1])]
        with patch.object(api, '_bounded_connection', return_value=nullcontext(conn)), \
                patch.object(api.lifecycle, '_scope', return_value=nullcontext()) as scope, \
                patch.object(api.lifecycle, 'list_vehicles', return_value=vehicles) as listing:
            rows = api._read(conn, self.user)
        scope.assert_called_once_with(conn, self.user)
        listing.assert_called_once_with(conn, self.user)
        sql, params = conn.execute.call_args.args
        self.assertIn('v.family_id=%s', sql)
        self.assertIn('s.ended_at IS NULL', sql)
        self.assertIn('s.started_at', sql)
        self.assertEqual(params, (self.user.family_id, [v.vehicle_ref for v in vehicles]))
        self.assertFalse(rows[0].in_use)
        self.assertIsNone(rows[0].current_driver)
        self.assertIsNone(rows[0].started_at)
        for row, vehicle, name, started in zip(rows[1:], vehicles[1:], ('One', 'Two'), times):
            self.assertTrue(row.in_use)
            self.assertEqual(row.current_driver, name)
            self.assertEqual(row.started_at, started)
            self.assertEqual(row.vehicle_ref, vehicle.vehicle_ref)
            self.assertEqual(row.display_name, vehicle.display_name)
        with patch.object(api, '_read', return_value=rows):
            response = self.client.get('/api/vehicles')
        with patch.object(api, '_read', return_value=[rows[1]]):
            detail = self.client.get('/api/vehicles/' + str(vehicles[1].vehicle_ref))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json(), response.json()[1])
        for item, row in zip(response.json(), rows):
            self.assertEqual(set(item), VEHICLE_FIELDS | {'current_driver', 'in_use', 'started_at'})
            if row.started_at is not None:
                parsed = datetime.fromisoformat(item['started_at'].replace('Z', '+00:00'))
                self.assertEqual(parsed, row.started_at)
                self.assertIsNotNone(parsed.utcoffset())
            else:
                self.assertIsNone(item['started_at'])


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
            retired = api._read(conn, self.current, first.vehicle_ref)[0]
            self.assertIsNotNone(retired.retired_at)
            self.assertFalse(retired.in_use)

    def test_status_uses_real_sessions_and_exposes_no_internal_ids(self):
        import vehicle_admission
        vehicle, device = self.vehicle(), self.device()
        self.call(vehicle_admission.admit_native_event, self.event(vehicle, device))
        with self.connection() as conn:
            row = api._read(conn, self.current, vehicle.vehicle_ref)[0]
            stored_start = conn.execute(
                'SELECT s.started_at FROM vehicle_driver_sessions s '
                'JOIN vehicles v ON v.id=s.vehicle_id '
                'WHERE v.vehicle_ref=%s AND s.ended_at IS NULL',
                (vehicle.vehicle_ref,)).fetchone()[0]
        self.assertTrue(row.in_use)
        self.assertIsNotNone(row.current_driver)
        self.assertEqual(row.started_at, stored_start)
        self.assertEqual(set(row.model_dump()), VEHICLE_FIELDS | {'current_driver', 'in_use', 'started_at'})
