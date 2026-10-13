"""DB-free tests of real routing/lifecycle; the SQL double rejects unknown queries."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from itertools import combinations
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity import CurrentUser
from vehicle_identity import VehicleIdentityError
import vehicle_api as api
import vehicle_lifecycle as lifecycle
import vehicle_creation_policy as policy


class MemoryConnection:
    def __init__(self):
        self.queries = []
        self.rows = {}
        self.creators = {11: 7, 22: 9}
        self.members = {(7, 11, 'owner'), (8, 11, 'parent'), (9, 22, 'other')}
        self.manufacturers = {1: ('יצרן', True), 2: ('Inactive', False)}
        self.sessions = []
        self.clock = datetime(2026, 10, 13, tzinfo=timezone.utc)

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        one, many = None, []
        if sql.startswith('SELECT pg_advisory_xact_lock'):
            pass
        elif sql == 'SELECT id FROM families WHERE id=%s FOR UPDATE':
            one = (params[0],) if params[0] in self.creators else None
        elif sql.startswith('SELECT 1 FROM users WHERE id='):
            one = (1,) if params in self.members else None
        elif sql == "SELECT %s::text !~ '^[[:space:]]*$'":
            one = (bool(params[0].strip()),)
        elif sql.startswith('SELECT id,vehicle_ref,display_name,retired_at,creation_fingerprint'):
            stored = self.rows.get(params)
            if stored:
                row, digest, creator = stored
                one = (*row[:4], digest, creator)
        elif sql == 'SELECT created_by_user_id FROM families WHERE id=%s':
            one = (self.creators[params[0]],)
        elif sql == 'SELECT id FROM vehicle_manufacturers WHERE id=%s AND is_active FOR SHARE':
            value = self.manufacturers.get(params[0])
            one = (params[0],) if value and value[1] else None
        elif sql.startswith('SELECT retired_at FROM vehicles WHERE family_id='):
            many = [(v[0][3],) for k, v in self.rows.items() if k[0] == params[0]][:params[1]]
        elif sql.startswith('INSERT INTO vehicles('):
            family, creator, name, key, digest, category, manufacturer, model, plate = params
            row = [len(self.rows) + 1, uuid4(), name, None, self.clock, category,
                   manufacturer, None, model, plate]
            self.rows[(family, key)] = (row, digest, creator)
            one = row[:4]
        elif sql.startswith(lifecycle._VEHICLE_DETAILS):
            matches = [v[0][:] for k, v in self.rows.items() if k[0] == params[0]]
            for row in matches:
                row[7] = self.manufacturers[row[6]][0] if row[6] is not None else None
            if 'AND v.id=%s' in sql:
                one = next((row for row in matches if row[0] == params[1]), None)
            else:
                assert sql.endswith('ORDER BY v.created_at ASC,v.id ASC'), sql
                many = sorted(matches, key=lambda row: (row[4], row[0]))
        elif sql.startswith('SELECT id,vehicle_ref,display_name,retired_at FROM vehicles '):
            one = next((v[0][:4] for k, v in self.rows.items()
                        if k[0] == params[0] and v[0][1] == params[1]), None)
        elif sql.startswith('SELECT v.vehicle_ref,u.name,s.started_at FROM vehicles v '):
            many = [row for row in self.sessions if row[0] in params[1]]
        else:
            raise AssertionError('Unexpected database operation: ' + sql)
        return Mock(fetchone=lambda: one, fetchall=lambda: many)


class VehicleMetadataTests(unittest.TestCase):
    def setUp(self):
        self.conn = MemoryConnection()
        self.user = CurrentUser(7, 'Owner', 11, auth_user_id='owner')
        self.parent = CurrentUser(8, 'Parent', 11, auth_user_id='parent')
        self.other = CurrentUser(9, 'Other', 22, auth_user_id='other')
        self.full = dict(display_name=' רכב ', category='hatchback', manufacturer_id=1,
                         model=' דגם ', license_plate=' 12-ABC ')
        bounded = patch.object(lifecycle, '_bounded_connection', side_effect=lambda conn: nullcontext(conn))
        read_bounded = patch.object(api, '_bounded_connection', side_effect=lambda conn: nullcontext(conn))
        gate = patch.object(lifecycle, 'require_auth')
        for patcher in (bounded, read_bounded, gate):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.pool = Mock(connection=lambda: nullcontext(self.conn))
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_current_user] = lambda: self.user
        app.dependency_overrides[api.vehicle_pool] = lambda: self.pool
        self.client = TestClient(app)

    def create(self, payload=None, key=None, user=None):
        return lifecycle.create_vehicle(self.conn, user or self.user,
                                        payload or {'display_name': 'Old'}, request_id=key or uuid4())

    def assert_error(self, code, action):
        with self.assertRaises(VehicleIdentityError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_legacy_nulls_replay_and_original_digest(self):
        key = uuid4()
        first = self.create(key=key)
        self.assertEqual(self.conn.rows[(11, key)][1], policy.fingerprint('Old'))
        self.assertEqual(self.create(key=key), first)
        nulls = dict(display_name='Old', category=None, manufacturer_id=None, model=None, license_plate=None)
        self.assertEqual(self.create(nulls, key), first)
        self.assertEqual(len(self.conn.rows), 1)
        for field in ('category', 'manufacturer_id', 'manufacturer_name_he', 'model', 'license_plate'):
            self.assertIsNone(getattr(first, field))
        self.assertEqual(first.created_at, self.conn.clock)
        self.assert_error('CREATION_IDEMPOTENCY_CONFLICT', lambda: self.create({'display_name': 'Changed'}, key))

    def test_all_categories_and_exact_unmodified_text(self):
        for category in ('hatchback', 'sedan', 'crossover', 'minivan', 'suv'):
            with self.subTest(category=category):
                vehicle = self.create({**self.full, 'category': category})
                self.assertEqual(vehicle.category, category)
                for field in ('display_name', 'model', 'license_plate'):
                    self.assertEqual(getattr(vehicle, field), self.full[field])
                self.assertEqual(vehicle.manufacturer_name_he, 'יצרן')

    def test_full_replay_after_deactivation_and_retirement(self):
        key = uuid4()
        first = self.create(self.full, key)
        self.conn.manufacturers[1] = ('יצרן', False)
        stored = self.conn.rows[(11, key)][0]
        stored[3] = self.conn.clock + timedelta(days=1)
        self.conn.queries.clear()
        replay = self.create(self.full, key)
        self.assertEqual(replay.vehicle_ref, first.vehicle_ref)
        self.assertEqual(replay.retired_at, stored[3])
        self.assertEqual(replay.manufacturer_name_he, 'יצרן')
        self.assertFalse(any('FOR SHARE' in sql or sql.startswith('INSERT') for sql, _ in self.conn.queries))

    def test_each_changed_field_conflicts_and_modes_do_not_collide(self):
        key = uuid4()
        self.create(self.full, key)
        for field, value in dict(display_name='Other', category='suv', manufacturer_id=2,
                                 model='Other', license_plate='Other').items():
            with self.subTest(field=field):
                self.assert_error('CREATION_IDEMPOTENCY_CONFLICT',
                                  lambda: self.create({**self.full, field: value}, key))
        self.assert_error('CREATION_IDEMPOTENCY_CONFLICT', lambda: self.create({'display_name': self.full['display_name']}, key))
        # Length/boundary encoding matters, not concatenation of field strings.
        a = lifecycle.VehicleCreationMetadata(**{**self.full, 'model': 'a', 'license_plate': 'bc'})
        b = lifecycle.VehicleCreationMetadata(**{**self.full, 'model': 'ab', 'license_plate': 'c'})
        self.assertNotEqual(a.fingerprint(), b.fingerprint())

    def test_creator_authorization_and_parent_does_not_grant_it(self):
        for payload in ({'display_name': 'Old'}, self.full):
            self.assert_error('VEHICLE_CREATION_FORBIDDEN', lambda: self.create(payload, user=self.parent))
        self.assertEqual(self.conn.rows, {})
        self.create()
        sqls = [sql for sql, _ in self.conn.queries]
        self.assertTrue(any('created_by_user_id' in sql for sql in sqls))
        self.assertFalse(any('family_role' in sql for sql in sqls))
        lock = sqls.index('SELECT id FROM families WHERE id=%s FOR UPDATE')
        creator = sqls.index('SELECT created_by_user_id FROM families WHERE id=%s')
        self.assertLess(lock, creator)
        self.assertTrue(any('pg_advisory_xact_lock' in sql for sql in sqls[:creator]))

    def test_pre_transition_member_replay_does_not_create_new_vehicle(self):
        key = uuid4()
        self.conn.creators[11] = 8
        original = self.create(key=key, user=self.parent)
        self.conn.creators[11] = 7
        self.assertEqual(self.create(key=key, user=self.parent), original)
        self.assert_error('VEHICLE_CREATION_FORBIDDEN', lambda: self.create(user=self.parent))
        self.assertEqual(len(self.conn.rows), 1)

    def test_manufacturer_missing_inactive_and_whitespace(self):
        for manufacturer in (2, 999):
            self.assert_error('MANUFACTURER_NOT_AVAILABLE',
                              lambda: self.create({**self.full, 'manufacturer_id': manufacturer}))
        for field, code in (('model', 'INVALID_VEHICLE_MODEL'), ('license_plate', 'INVALID_VEHICLE_LICENSE_PLATE')):
            for value in ('', ' ', '\t\n'):
                self.assert_error(code, lambda: self.create({**self.full, field: value}))
        self.assertEqual(self.conn.rows, {})

    def test_api_rejects_every_partial_subset_and_invalid_types(self):
        fields = ('category', 'manufacturer_id', 'model', 'license_plate')
        partials = [{field: self.full[field] for field in subset}
                    for n in (1, 2, 3) for subset in combinations(fields, n)]
        invalid = [{**self.full, 'category': 'truck'}, {**self.full, 'manufacturer_id': True},
                   {**self.full, 'manufacturer_id': '1'}, {**self.full, 'manufacturer_id': 2**31},
                   {**self.full, 'model': 123}, {**self.full, 'license_plate': None}]
        for fields in partials + invalid:
            response = self.client.post('/api/vehicles', json={
                'display_name': 'Car', 'request_id': str(uuid4()), **fields})
            self.assertEqual(response.status_code, 422, fields)
        self.assertEqual(self.conn.queries, [])

    def test_full_http_contract_and_structured_forbidden(self):
        key = str(uuid4())
        response = self.client.post('/api/vehicles', json={**self.full, 'request_id': key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['license_plate'], self.full['license_plate'])
        self.assertEqual(self.client.post('/api/vehicles', json={**self.full, 'request_id': key}).json(), response.json())
        self.user = self.parent
        denied = self.client.post('/api/vehicles', json={'display_name': 'Old', 'request_id': str(uuid4())})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()['detail']['code'], 'VEHICLE_CREATION_FORBIDDEN')

    def test_list_default_opt_in_order_family_and_detail(self):
        keys = [uuid4() for _ in range(3)]
        cars = [self.create(key=key) for key in keys]
        self.create(user=self.other)
        self.conn.rows[(11, keys[0])][0][4] += timedelta(seconds=1)
        self.conn.rows[(11, keys[1])][0][3] = self.conn.clock
        self.conn.sessions = [(cars[2].vehicle_ref, 'Driver', self.conn.clock)]
        default = self.client.get('/api/vehicles').json()
        all_rows = self.client.get('/api/vehicles?include_retired=true').json()
        self.assertEqual([row['vehicle_ref'] for row in default], [str(cars[2].vehicle_ref), str(cars[0].vehicle_ref)])
        self.assertEqual([row['vehicle_ref'] for row in all_rows],
                         [str(cars[1].vehicle_ref), str(cars[2].vehicle_ref), str(cars[0].vehicle_ref)])
        self.assertFalse(all_rows[0]['in_use'])
        self.assertIsNone(all_rows[0]['started_at'])
        self.assertTrue(default[0]['in_use'])
        self.assertEqual(default[0]['current_driver'], 'Driver')
        self.assertIsNotNone(default[0]['started_at'])
        path = '/api/vehicles/' + str(cars[1].vehicle_ref)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.user = self.other
        self.assertEqual(self.client.get('/api/vehicles/' + str(cars[0].vehicle_ref)).status_code, 404)
        self.assertEqual(self.client.get('/api/vehicles/' + str(uuid4())).status_code, 404)

    def test_family_membership_is_revalidated(self):
        stale = CurrentUser(7, 'Owner', 22, auth_user_id='owner')
        self.assert_error('FAMILY_ACCESS_DENIED', lambda: self.create(user=stale))
        self.assertEqual(self.conn.rows, {})

    def test_quotas_and_replay_before_quota(self):
        key = uuid4()
        first = self.create(key=key)
        for _ in range(9):
            self.create()
        self.assert_error('VEHICLE_ACTIVE_LIMIT', self.create)
        self.assertEqual(self.create(key=key), first)
        for _ in range(40):
            for row, _, _ in self.conn.rows.values():
                row[3] = self.conn.clock
            self.create()
        self.assert_error('VEHICLE_LIFETIME_LIMIT', self.create)
        self.assertEqual(len(self.conn.rows), 50)
        self.assertEqual(self.create(key=key).vehicle_ref, first.vehicle_ref)


if __name__ == '__main__':
    unittest.main()
