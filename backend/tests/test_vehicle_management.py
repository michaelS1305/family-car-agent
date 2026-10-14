"""DB-free execution of real management routes/services with strict SQL doubles."""
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import os
from unittest.mock import Mock, patch
from uuid import uuid4
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from identity import CurrentUser
import vehicle_api as api
import vehicle_lifecycle as lifecycle
import vehicle_maintenance as maintenance
from vehicle_identity import VehicleIdentityError
from tests.test_vehicle_metadata import MemoryConnection
from tests import test_vehicle_lifecycle as fixtures


class ManagementConnection(MemoryConnection):
    def __init__(self):
        super().__init__()
        self.reservations = []
        self.maintenance = []
        self.fail_cancel = False

    @contextmanager
    def transaction(self):
        snapshot = deepcopy((self.rows, self.reservations, self.maintenance))
        try:
            yield
        except Exception:
            self.rows, self.reservations, self.maintenance = snapshot
            raise

    def execute(self, sql, params=None):
        one, many = None, []
        if sql.startswith('UPDATE vehicles SET display_name='):
            row = next(v[0] for v in self.rows.values() if v[0][0] == params[-1])
            row[2], row[5], row[6], row[8], row[9] = params[:-1]
            one = row[:4]
        elif sql.startswith('SELECT 1 FROM vehicle_driver_sessions'):
            ref = next(v[0][1] for v in self.rows.values() if v[0][0] == params[0])
            one = (1,) if any(s[0] == ref for s in self.sessions) else None
        elif sql.startswith('UPDATE vehicles SET retired_at='):
            row = next(v[0] for v in self.rows.values() if v[0][0] == params[0])
            row[3] = self.clock
            one = row[:4]
        elif sql.startswith("UPDATE reservations SET status='cancelled'"):
            assert sql == ("UPDATE reservations SET status='cancelled' WHERE vehicle_id=%s AND status='active' "
                           'AND end_time::timestamp > %s::timestamp'), sql
            if self.fail_cancel:
                raise RuntimeError('simulated cancellation failure')
            for r in self.reservations:
                if r['vehicle'] == params[0] and r['status'] == 'active' and r['end'] > params[1]:
                    r['status'] = 'cancelled'
        elif sql.startswith('INSERT INTO vehicle_maintenance('):
            vehicle, description, scheduled, creator = params
            one = (uuid4(), description, scheduled, self.clock)
            self.maintenance.append((vehicle, len(self.maintenance) + 1, one, creator))
        elif sql.startswith('UPDATE vehicle_maintenance SET description='):
            assert sql == ('UPDATE vehicle_maintenance SET description=%s,scheduled_date=%s '
                           'WHERE vehicle_id=%s AND maintenance_ref=%s '
                           'RETURNING maintenance_ref,description,scheduled_date,created_at'), sql
            description, scheduled, vehicle, ref = params
            for i, r in enumerate(self.maintenance):
                if r[0] == vehicle and r[2][0] == ref:
                    one = (ref, description, scheduled, r[2][3])
                    self.maintenance[i] = (r[0], r[1], one, r[3])
                    break
        elif sql.startswith('DELETE FROM vehicle_maintenance '):
            assert sql == 'DELETE FROM vehicle_maintenance WHERE vehicle_id=%s AND maintenance_ref=%s RETURNING maintenance_ref', sql
            for i, r in enumerate(self.maintenance):
                if r[0] == params[0] and r[2][0] == params[1]:
                    one = (r[2][0],)
                    self.maintenance.pop(i)
                    break
        elif sql.startswith('SELECT maintenance_ref,description,scheduled_date,created_at FROM vehicle_maintenance '):
            assert sql.endswith('WHERE vehicle_id=%s ORDER BY scheduled_date ASC,id ASC'), sql
            many = [r[2] for r in sorted(self.maintenance, key=lambda r: (r[2][2], r[1])) if r[0] == params[0]]
        else:
            return super().execute(sql, params)
        self.queries.append((sql, params))
        return Mock(fetchone=lambda: one, fetchall=lambda: many)


class VehicleManagementTests(unittest.TestCase):
    def setUp(self):
        self.conn = ManagementConnection()
        self.owner = CurrentUser(7, 'Owner', 11, auth_user_id='owner')
        self.peer = CurrentUser(8, 'Parent', 11, auth_user_id='parent')
        self.other = CurrentUser(9, 'Other', 22, auth_user_id='other')
        self.user = self.owner
        for p in (patch.object(lifecycle, '_bounded_connection', side_effect=lambda c: nullcontext(c)),
                  patch.object(api, '_bounded_connection', side_effect=lambda c: nullcontext(c)),
                  patch.object(lifecycle, 'require_auth')):
            p.start()
            self.addCleanup(p.stop)
        self.app = FastAPI()
        self.app.include_router(api.router)
        self.app.dependency_overrides[api.get_current_user] = lambda: self.user
        self.app.dependency_overrides[api.vehicle_pool] = lambda: Mock(connection=lambda: nullcontext(self.conn))
        self.client = TestClient(self.app)
        self.payload = dict(display_name=' Car ', category='sedan', manufacturer_id=1,
                            model=' Model ', license_plate='ABC / 12')
        self.vehicle = lifecycle.create_vehicle(self.conn, self.owner, self.payload, request_id=uuid4())
        self.path = '/api/vehicles/' + str(self.vehicle.vehicle_ref)
        self.now = self.conn.clock.replace(tzinfo=None)
        p = patch.object(lifecycle, 'reservation_now', return_value=self.now)
        p.start()
        self.addCleanup(p.stop)

    def test_retired_detail_member_metadata_and_list_behavior(self):
        self.assertEqual(self.client.post(self.path + '/retire').status_code, 200)
        self.user = self.peer
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        row = response.json()
        for field, value in self.payload.items():
            self.assertEqual(row[field], value)
        self.assertEqual(row['manufacturer_name_he'], 'יצרן')
        self.assertIsNotNone(row['retired_at'])
        self.assertFalse(row['in_use'])
        self.assertIsNone(row['current_driver'])
        self.assertIsNone(row['started_at'])
        self.assertEqual(self.client.get('/api/vehicles').json(), [])
        self.assertEqual(self.client.get('/api/vehicles?include_retired=true').json(), [row])

    def test_edit_full_payload_and_no_internal_identity(self):
        self.conn.manufacturers[3] = ('New maker', True)
        updated = dict(display_name=' New ', category='suv', manufacturer_id=3, model='Z', license_plate='not-a-regex')
        response = self.client.put(self.path, json=updated)
        self.assertEqual(response.status_code, 200)
        for field, value in updated.items():
            self.assertEqual(response.json()[field], value)
        self.assertEqual(response.json()['manufacturer_name_he'], 'New maker')
        self.assertEqual(response.json()['vehicle_ref'], str(self.vehicle.vehicle_ref))
        self.assertNotIn('id', response.json())
        self.assertEqual(self.client.put(self.path, json=updated).json(), response.json())

    def test_edit_validation(self):
        invalid = [{k: v for k, v in self.payload.items() if k != field} for field in self.payload]
        invalid += [{**self.payload, k: v} for k, v in (
            ('category', 'truck'), ('manufacturer_id', True), ('manufacturer_id', '1'),
            ('manufacturer_id', 2), ('manufacturer_id', 999), ('model', None),
            ('display_name', ' \t'), ('model', '\n'), ('license_plate', ' '), ('family_id', 22))]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.put(self.path, json=payload).status_code, 422)
        self.assertEqual(self.client.get(self.path).json()['display_name'], self.payload['display_name'])

    def test_non_creator_forbidden_but_reads_work(self):
        self.user = self.peer
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [])
        for method, suffix, body in [('put', '', self.payload), ('post', '/retire', None),
                                     ('post', '/maintenance', {'description': 'Oil', 'scheduled_date': '2026-01-01'})]:
            result = getattr(self.client, method)(self.path + suffix, **({'json': body} if body else {}))
            self.assertEqual(result.status_code, 403)
        self.assertIsNone(self.client.get(self.path).json()['retired_at'])

    def test_family_isolation_for_all_routes(self):
        self.user = self.other
        for path in (self.path, '/api/vehicles/' + str(uuid4())):
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.put(path, json=self.payload).status_code, 404)
            self.assertEqual(self.client.post(path + '/retire').status_code, 404)
            self.assertEqual(self.client.get(path + '/maintenance').status_code, 404)
            self.assertEqual(self.client.post(path + '/maintenance', json={
                'description': 'Oil', 'scheduled_date': '2026-01-01'}).status_code, 404)

    def test_retire_cancels_unfinished_active_only_and_replay_is_read_only(self):
        vehicle_id = next(iter(self.conn.rows.values()))[0][0]
        for vehicle, end, status in [(vehicle_id, 1, 'active'), (vehicle_id, -1, 'active'),
                                     (vehicle_id, 0, 'active'), (vehicle_id, 1, 'cancelled'),
                                     (999, 1, 'active')]:
            self.conn.reservations.append(dict(vehicle=vehicle, end=self.now + timedelta(hours=end), status=status))
        result = self.client.post(self.path + '/retire')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([r['status'] for r in self.conn.reservations],
                         ['cancelled', 'active', 'active', 'cancelled', 'active'])
        self.conn.queries.clear()
        self.assertEqual(self.client.post(self.path + '/retire').json(), result.json())
        self.assertFalse(any(q.startswith('UPDATE') for q, _ in self.conn.queries))

    def test_ongoing_reservation_uses_existing_end_boundary_and_shared_lock(self):
        vehicle_id = next(iter(self.conn.rows.values()))[0][0]
        self.conn.reservations = [dict(vehicle=vehicle_id, start=self.now - timedelta(hours=1),
                                      end=self.now + timedelta(hours=1), status='active')]
        self.conn.queries.clear()
        self.assertEqual(self.client.post(self.path + '/retire').status_code, 200)
        self.assertEqual(self.conn.reservations[0]['status'], 'cancelled')
        sqls = [q for q, _ in self.conn.queries]
        self.assertLess(sqls.index('SELECT pg_advisory_xact_lock(%s,%s)'),
                        next(i for i, q in enumerate(sqls) if q.startswith('UPDATE vehicles')))

    def test_null_creator_fails_closed(self):
        self.conn.creators[11] = None
        self.assertEqual(self.client.put(self.path, json=self.payload).status_code, 403)
        self.assertEqual(self.client.post(self.path + '/retire').status_code, 403)
        self.assertEqual(self.client.post(self.path + '/maintenance', json={
            'description': 'x', 'scheduled_date': '2026-01-01'}).status_code, 403)

    def test_retirement_rollback_and_open_session_conflict(self):
        self.conn.sessions = [(self.vehicle.vehicle_ref, 'Driver', self.conn.clock)]
        self.assertTrue(self.client.get(self.path).json()['in_use'])
        result = self.client.post(self.path + '/retire')
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['detail']['code'], 'VEHICLE_IN_USE')
        self.conn.sessions = []
        self.conn.fail_cancel = True
        with self.assertRaises(RuntimeError):
            self.client.post(self.path + '/retire')
        self.assertIsNone(self.client.get(self.path).json()['retired_at'])

    def test_maintenance_order_dates_retention_and_retired_mutations(self):
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [])
        refs = []
        for description, scheduled in [('future', '2030-01-01'), ('past', '2020-01-01'), ('tie', '2020-01-01')]:
            result = self.client.post(self.path + '/maintenance', json={'description': description, 'scheduled_date': scheduled})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(set(result.json()), {'maintenance_ref', 'description', 'scheduled_date', 'created_at'})
            refs.append(result.json()['maintenance_ref'])
            if len(refs) == 1:
                self.assertEqual(len(self.client.get(self.path + '/maintenance').json()), 1)
        rows = self.client.get(self.path + '/maintenance').json()
        self.assertEqual([r['maintenance_ref'] for r in rows], [refs[1], refs[2], refs[0]])
        self.client.post(self.path + '/retire')
        self.assertEqual(self.client.put(self.path, json=self.payload).status_code, 409)
        self.assertEqual(self.client.post(self.path + '/maintenance', json={
            'description': 'New', 'scheduled_date': '2031-01-01'}).status_code, 409)
        self.user = self.peer
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), rows)

    def test_maintenance_invalid_payloads(self):
        valid = dict(description=' Service ', scheduled_date='2026-10-14')
        for payload in ({}, {'description': 'Oil'}, {**valid, 'description': '\t\n'},
                        {**valid, 'description': 1}, {**valid, 'scheduled_date': '2026-02-30'},
                        {**valid, 'scheduled_date': 0}, {**valid, 'scheduled_date': '2026-10-14T00:00:00'},
                        {**valid, 'vehicle_id': 99}, {**valid, 'completed': True}):
            self.assertEqual(self.client.post(self.path + '/maintenance', json=payload).status_code, 422)
        self.assertEqual(self.conn.maintenance, [])

    def maintenance_item(self):
        body = {'description': 'Oil', 'scheduled_date': '2020-01-01'}
        item = self.client.post(self.path + '/maintenance', json=body).json()
        return self.path + '/maintenance/' + item['maintenance_ref'], item

    def test_maintenance_edit_delete_public_identity_and_order(self):
        path, original = self.maintenance_item()
        updated = self.client.put(path, json={'description': 'Service', 'scheduled_date': '2019-01-01'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.headers['cache-control'], 'no-store')
        self.assertEqual(updated.json(), {**original, 'description': 'Service', 'scheduled_date': '2019-01-01'})
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [updated.json()])
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b'')
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [])
        self.assertEqual(self.client.delete(path).status_code, 404)

    def test_maintenance_mutation_authorization_retired_and_scope(self):
        path, item = self.maintenance_item()
        body = {'description': 'Updated', 'scheduled_date': '2026-01-01'}
        for user, expected in ((self.peer, 403), (self.other, 404)):
            self.user = user
            self.assertEqual(self.client.put(path, json=body).status_code, expected)
            self.assertEqual(self.client.delete(path).status_code, expected)
        self.user = self.owner
        second = lifecycle.create_vehicle(self.conn, self.owner, {**self.payload, 'display_name': 'Other'}, request_id=uuid4())
        wrong = '/api/vehicles/' + str(second.vehicle_ref) + '/maintenance/' + item['maintenance_ref']
        for p in (wrong, self.path + '/maintenance/' + str(uuid4())):
            self.assertEqual(self.client.put(p, json=body).status_code, 404)
            self.assertEqual(self.client.delete(p).status_code, 404)
        self.conn.creators[11] = None
        self.assertEqual(self.client.put(path, json=body).status_code, 403)
        self.assertEqual(self.client.delete(path).status_code, 403)
        self.conn.creators[11] = self.owner.user_id
        self.client.post(self.path + '/retire')
        self.assertEqual(self.client.put(path, json=body).status_code, 409)
        self.assertEqual(self.client.delete(path).status_code, 409)
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [item])

    def test_maintenance_edit_invalid_and_unauthenticated(self):
        path, item = self.maintenance_item()
        for body in ({}, {'description': ' ', 'scheduled_date': '2026-01-01'},
                     {'description': 'x', 'scheduled_date': '2026-01-01T00:00:00'},
                     {'description': 'x', 'scheduled_date': '2026-01-01', 'vehicle_id': 5}):
            self.assertEqual(self.client.put(path, json=body).status_code, 422)
        self.assertEqual(self.client.get(self.path + '/maintenance').json(), [item])
        def denied():
            raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user] = denied
        self.assertEqual(self.client.put(path, json={'description': 'x', 'scheduled_date': '2026-01-01'}).status_code, 401)
        self.assertEqual(self.client.delete(path).status_code, 401)

    def test_auth_required(self):
        def denied():
            raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user] = denied
        for method, suffix, payload in [('get', '', None), ('put', '', self.payload),
                                         ('post', '/retire', None), ('get', '/maintenance', None),
                                         ('post', '/maintenance', {'description': 'x', 'scheduled_date': '2026-01-01'})]:
            self.assertEqual(getattr(self.client, method)(self.path + suffix,
                **({'json': payload} if payload else {})).status_code, 401)

    def test_migration_backend_only_and_minimal(self):
        sql = (Path(__file__).resolve().parents[2] / 'supabase/manual_migrations/2026101401_vehicle_maintenance.sql').read_text()
        for fragment in ('BEGIN;', 'COMMIT;', 'ENABLE ROW LEVEL SECURITY', 'NO FORCE ROW LEVEL SECURITY',
                         'ON DELETE SET NULL', 'ON DELETE CASCADE', 'UNIQUE (maintenance_ref)',
                         'vehicle_id,scheduled_date,id', 'scheduled_date date NOT NULL',
                         'FROM PUBLIC, anon, authenticated, service_role'):
            self.assertIn(fragment, sql)
        self.assertNotIn('CREATE POLICY', sql)


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class VehicleManagementPostgresTests(unittest.TestCase):
    connection = fixtures.LifecyclePostgresTests.connection
    drop_schema = fixtures.LifecyclePostgresTests.drop_schema
    query = fixtures.LifecyclePostgresTests.query
    person = fixtures.LifecyclePostgresTests.person
    call = fixtures.LifecyclePostgresTests.call
    vehicle = fixtures.LifecyclePostgresTests.vehicle

    def setUp(self):
        fixtures.LifecyclePostgresTests.setUp(self)
        source = (Path(__file__).resolve().parents[2] / 'supabase/manual_migrations/2026101401_vehicle_maintenance.sql').read_text()
        start = 'CREATE TABLE public.vehicle_maintenance ('
        statement = start + source.split(start, 1)[1].split(';', 1)[0] + ';'
        # Isolated local schema DDL only, not migration execution or public ACL changes.
        self.query(statement.replace('public.', self.schema + '.'))
        self.car = self.vehicle()
        self.vehicle_id = self.query('SELECT id FROM vehicles WHERE vehicle_ref=%s', (self.car.vehicle_ref,))[0][0]

    def test_atomic_retirement_cancellation_and_rollback(self):
        now = lifecycle.reservation_now()
        for end, status in [(now + timedelta(days=1), 'active'), (now - timedelta(days=1), 'active'),
                            (now + timedelta(days=1), 'cancelled')]:
            self.query('INSERT INTO reservations(user_id,vehicle_id,end_time,status) VALUES(%s,%s,%s,%s)',
                       (self.creator[1], self.vehicle_id, end.isoformat(), status))
        before = self.query('SELECT * FROM reservations')
        with self.assertRaises(RuntimeError), self.connection() as conn:
            with conn.transaction():
                lifecycle.retire_vehicle(conn, self.current, self.car.vehicle_ref)
                raise RuntimeError('caller rollback')
        self.assertEqual(self.query('SELECT * FROM reservations'), before)
        self.assertIsNone(self.call(lifecycle.get_vehicle, self.car.vehicle_ref).retired_at)
        retired = self.call(lifecycle.retire_vehicle, self.car.vehicle_ref)
        self.assertEqual(self.query("SELECT count(*) FROM reservations WHERE status='cancelled'"), [(2,)])
        self.assertEqual(self.query("SELECT count(*) FROM reservations WHERE status='active'"), [(1,)])
        self.assertEqual(self.call(lifecycle.retire_vehicle, self.car.vehicle_ref), retired)

    def test_maintenance_scope_order_retirement_and_creator_deletion_attribution(self):
        for description, scheduled in [('later', '2030-01-01'), ('past', '2020-01-01'), ('tie', '2020-01-01')]:
            self.call(maintenance.create_item, self.car.vehicle_ref,
                      {'description': description, 'scheduled_date': scheduled})
        rows = self.call(maintenance.list_items, self.car.vehicle_ref, user=self.peer)
        self.assertEqual([r.description for r in rows], ['past', 'tie', 'later'])
        for user in (self.peer, self.outsider):
            with self.assertRaises(VehicleIdentityError):
                self.call(maintenance.create_item, self.car.vehicle_ref,
                          {'description': 'No', 'scheduled_date': '2026-01-01'}, user=user)
        with self.assertRaises(VehicleIdentityError):
            self.call(maintenance.list_items, self.car.vehicle_ref, user=self.outsider)
        self.call(lifecycle.retire_vehicle, self.car.vehicle_ref)
        self.assertEqual(self.call(maintenance.list_items, self.car.vehicle_ref, user=self.peer), rows)
        with self.assertRaises(VehicleIdentityError):
            self.call(maintenance.create_item, self.car.vehicle_ref,
                      {'description': 'No', 'scheduled_date': '2026-01-01'})
        # FK retention semantics without invoking provider account deletion.
        self.query('UPDATE vehicle_maintenance SET created_by_user_id=%s', (self.member[1],))
        self.query('DELETE FROM users WHERE id=%s', (self.member[1],))
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_maintenance WHERE created_by_user_id IS NULL'), [(3,)])


if __name__ == '__main__':
    unittest.main()
