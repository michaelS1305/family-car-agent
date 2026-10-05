"""Android authorization contracts; PostgreSQL fixtures are LOCAL-only."""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import uuid4
import device_api as api
import vehicle_bindings as bindings
import vehicle_lifecycle as lifecycle
from vehicle_identity import VehicleIdentityError
from tests import test_vehicle_api as api_fixtures
from tests import test_vehicle_lifecycle as fixtures


class DeviceApiTests(unittest.TestCase):
    # Reuse setup only; do not inherit unrelated test cases.
    def setUp(self):
        api_fixtures.VehicleApiTests.setUp(self)
        self.app.include_router(api.router)

    def test_registration_uses_android_and_current_identity(self):
        key = uuid4()
        with patch.object(api.lifecycle, 'register_device', return_value={}) as register:
            self.assertEqual(self.client.post('/api/devices', json={'request_id': str(key)}).status_code, 200)
            self.assertEqual(register.call_args.args[1:], (self.user, {'platform': 'android'}))
            self.assertEqual(register.call_args.kwargs, {'request_id': key})

    def test_take_rejects_identity_and_invalid_envelope(self):
        payload = {'event_id': str(uuid4()), 'vehicle_ref': str(uuid4()), 'device_sequence': 1,
                   'occurred_at': '2026-09-27T12:00:00Z'}
        with patch.object(api.vehicle_bindings, 'admit_take', return_value={'kind': 'accepted'}) as admit:
            path = '/api/devices/' + str(uuid4()) + '/events/take'
            for change in ({'user_id': 1}, {'source': 'native'}, {'device_sequence': True},
                           {'device_sequence': 0}, {'occurred_at': '2026-09-27T12:00:00'}):
                self.assertEqual(self.client.post(path, json={**payload, **change}).status_code, 422)
            admit.assert_not_called()
            self.assertEqual(self.client.post(path, json=payload).status_code, 200)
            self.assertEqual(admit.call_args.args[1], self.user)
            self.assertEqual(admit.call_args.args[2].event_type, 'take')

    def test_device_routes_authenticate(self):
        self.app.dependency_overrides[api.get_current_user] = lambda: (_ for _ in ()).throw(api.HTTPException(401))
        base = '/api/devices/' + str(uuid4())
        for method, path in [('GET', '/api/devices'), ('POST', '/api/devices'),
                             ('GET', base + '/vehicle-bindings'),
                             ('PUT', base + '/vehicle-bindings/' + str(uuid4())),
                             ('DELETE', base + '/vehicle-bindings/' + str(uuid4())),
                             ('POST', base + '/events/take')]:
            self.assertEqual(self.client.request(method, path, json={}).status_code, 401)

    def test_return_strict_contract_and_identity(self):
        body = {'event_id': str(uuid4()), 'vehicle_ref': str(uuid4()), 'device_sequence': 2,
                'take_event_id': str(uuid4()), 'occurred_at': '2026-09-28T12:00:00Z',
                'location_at': '2026-09-28T12:00:00Z', 'latitude': 32.0, 'longitude': 34.0, 'accuracy_m': 10.0}
        path = '/api/devices/' + str(uuid4()) + '/events/return'
        with patch.object(bindings, 'admit_return', return_value={'kind': 'accepted'}) as admit:
            for change in ({'user_id': 7}, {'family_id': 1}, {'is_home': True}, {'event_id': 'bad'},
                           {'device_sequence': True}, {'device_sequence': 0}, {'device_sequence': 2**63},
                           {'occurred_at': '2026-09-28T12:00:00'}, {'take_event_id': None},
                           {'latitude': 91}, {'longitude': -181}, {'accuracy_m': 101}, {'accuracy_m': 0},
                           {'latitude': '32'}, {'location_at': '2026-09-28T12:00:00'}):
                self.assertEqual(self.client.post(path, json={**body, **change}).status_code, 422, change)
            admit.assert_not_called()
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(admit.call_args.args[1], self.user)
            self.assertEqual(str(admit.call_args.args[2].take_event_id), body['take_event_id'])
        self.app.dependency_overrides[api.get_current_user] = lambda: (_ for _ in ()).throw(api.HTTPException(401))
        self.assertEqual(self.client.post(path, json=body).status_code, 401)
        self.assertEqual(self.client.get('/api/devices/' + str(uuid4()) + '/return-home').status_code, 401)


@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Local PostgreSQL not configured')
class BindingPostgresTests(unittest.TestCase):
    connection = fixtures.LifecyclePostgresTests.connection
    drop_schema = fixtures.LifecyclePostgresTests.drop_schema
    query = fixtures.LifecyclePostgresTests.query
    person = fixtures.LifecyclePostgresTests.person
    call = fixtures.LifecyclePostgresTests.call
    vehicle = fixtures.LifecyclePostgresTests.vehicle
    device = fixtures.LifecyclePostgresTests.device
    event = fixtures.LifecyclePostgresTests.event

    def setUp(self):
        fixtures.LifecyclePostgresTests.setUp(self)
        # Parent fixture rejects anything except localhost/test_gemini first.
        # Provider role placeholders have no LOGIN and no global privileges.
        self.query("""DO $$ DECLARE r text; BEGIN
          FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
            IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN
              EXECUTE format('CREATE ROLE %I NOLOGIN', r);
            END IF;
          END LOOP; END $$;""")
        self.source = (Path(__file__).resolve().parents[2] / 'supabase/manual_migrations/2026092701_registered_device_vehicle_bindings.sql').read_text()
        self.local_sql = self.source.replace('public.', self.schema + '.').replace("current_user <> 'postgres'", "current_user <> 'gemini_test'").replace('BEGIN;', '').replace('COMMIT;', '')
        self.query(self.local_sql)

    def bind(self, d, v, user=None, remove=False):
        with self.connection() as conn:
            return bindings.bindings(conn, user or self.current, d.device_ref, v.vehicle_ref, remove=remove)

    def return_evidence(self, event, **changes):
        return api.Return(event_id=event.event_id, vehicle_ref=event.vehicle_ref,
                          device_sequence=event.device_sequence, occurred_at=event.occurred_at,
                          take_event_id=event.take_event_id, **{
                              'latitude': 32.0, 'longitude': 34.0, 'accuracy_m': 10.0,
                              'location_at': event.occurred_at, **changes})

    def home(self):
        self.query('UPDATE families SET home_latitude=32,home_longitude=34 WHERE id=%s', (self.family,))

    def test_return_home_causal_replay_and_no_duplicate_session_change(self):
        self.home()
        d, v = self.device(), self.vehicle(); self.bind(d, v)
        take = self.event(v, d)
        self.call(bindings.admit_take, take)
        event = self.event(v, d, 2, take.event_id)
        evidence = self.return_evidence(event)
        self.assertEqual(self.call(bindings.return_home, d.device_ref), {'latitude': 32.0, 'longitude': 34.0})
        self.assertEqual(self.call(bindings.admit_return, event, evidence).kind, 'accepted')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions WHERE ended_at IS NULL'), [(0,)])
        sessions = self.query('SELECT * FROM vehicle_driver_sessions')
        self.bind(d, v, remove=True)
        self.query('UPDATE families SET home_latitude=NULL WHERE id=%s', (self.family,))
        self.assertEqual(self.call(bindings.admit_return, event, evidence).kind, 'retry')
        self.assertEqual(self.query('SELECT * FROM vehicle_driver_sessions'), sessions)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(2,)])

    def test_return_rejections_preserve_sequence_and_occupancy(self):
        from datetime import timedelta
        self.home()
        d, v = self.device(), self.vehicle(); self.bind(d, v)
        take = self.event(v, d); self.call(bindings.admit_take, take)
        event = self.event(v, d, 2, take.event_id)
        for evidence in (self.return_evidence(event, latitude=33.0),
                         self.return_evidence(event, location_at=event.occurred_at-timedelta(seconds=31))):
            with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_return, event, evidence)
        with self.assertRaises(VehicleIdentityError):
            self.call(bindings.admit_return, event, self.return_evidence(event), user=self.peer)
        foreign = replace(event, vehicle_ref=self.vehicle(user=self.outsider).vehicle_ref)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_return, foreign, self.return_evidence(foreign))
        self.bind(d, v, remove=True)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_return, event, self.return_evidence(event))
        self.bind(d, v)
        self.call(lifecycle.revoke_device, d.device_ref)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_return, event, self.return_evidence(event))
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions WHERE ended_at IS NULL'), [(1,)])

    def test_delayed_return_does_not_close_peer_handover_and_gap_is_preserved(self):
        self.home()
        d, peer, v = self.device(), self.device(user=self.peer), self.vehicle()
        self.bind(d, v); self.bind(peer, v, self.peer)
        take = self.event(v, d); self.call(bindings.admit_take, take)
        self.call(bindings.admit_take, self.event(v, peer), user=self.peer)
        event = self.event(v, d, 2, take.event_id)
        self.assertEqual(self.call(bindings.admit_return, replace(event, device_sequence=3), self.return_evidence(event)).kind, 'gap')
        self.call(bindings.admit_return, event, self.return_evidence(event))
        self.assertEqual(self.query('SELECT user_id FROM vehicle_driver_sessions WHERE ended_at IS NULL'), [(self.peer.user_id,)])

    def test_return_retired_vehicle_and_unknown_cause_fail_closed(self):
        self.home()
        d, v = self.device(), self.vehicle(); self.bind(d, v)
        event = self.event(v, d, 1, uuid4())
        self.call(bindings.admit_return, event, self.return_evidence(event))
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions'), [(0,)])
        self.call(lifecycle.retire_vehicle, v.vehicle_ref)
        other = replace(event, event_id=uuid4(), device_sequence=2)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_return, other, self.return_evidence(other))

    def test_return_of_reconnected_take_alias_ends_original_session(self):
        self.home()
        d, v = self.device(), self.vehicle(); self.bind(d, v)
        original = self.event(v, d); self.call(bindings.admit_take, original)
        alias = self.event(v, d, 2); self.call(bindings.admit_take, alias)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions'), [(1,)])
        event = self.event(v, d, 3, alias.event_id)
        self.assertEqual(self.call(bindings.admit_return, event, self.return_evidence(event)).kind, 'accepted')
        self.assertEqual(self.query('SELECT start_event_id FROM vehicle_driver_sessions WHERE ended_at IS NOT NULL'), [(original.event_id,)])
        conflict = replace(event, take_event_id=uuid4())
        self.assertEqual(self.call(bindings.admit_return, conflict, self.return_evidence(conflict)).kind, 'conflict')
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(3,)])

    def test_many_to_many_and_idempotent_delete(self):
        a, b, d, peer = self.vehicle(), self.vehicle(), self.device(), self.device(user=self.peer)
        self.bind(d, a); self.bind(d, a); self.bind(d, b); self.bind(peer, a, self.peer)
        self.assertEqual(len(self.query('SELECT * FROM registered_device_vehicle_bindings')), 3)
        self.assertEqual(len(self.call(bindings.bindings, d.device_ref)), 2)
        self.bind(d, a, remove=True); self.bind(d, a, remove=True)
        self.assertEqual(len(self.query('SELECT * FROM registered_device_vehicle_bindings')), 2)

    def test_foreign_owner_family_and_soft_lifecycle_fail_closed(self):
        d, v = self.device(), self.vehicle()
        with self.assertRaises(VehicleIdentityError): self.bind(d, v, self.peer)
        with self.assertRaises(VehicleIdentityError): self.bind(d, self.vehicle(user=self.outsider))
        self.bind(d, v)
        self.call(lifecycle.revoke_device, d.device_ref)
        self.call(lifecycle.retire_vehicle, v.vehicle_ref)
        self.assertFalse(self.call(bindings.bindings, d.device_ref)[0]['usable'])
        with self.assertRaises(VehicleIdentityError): self.bind(d, v)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_take, self.event(v, d))
        self.bind(d, v, remove=True)
        self.assertEqual(self.query('SELECT * FROM registered_device_vehicle_bindings'), [])

    def test_take_binding_replay_sequence_and_no_mutation_on_unbind(self):
        d, v = self.device(), self.vehicle()
        event = self.event(v, d)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_take, event)
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'), [(0,)])
        self.bind(d, v)
        self.assertEqual(self.call(bindings.admit_take, replace(event, device_sequence=2)).kind, 'gap')
        self.assertEqual(self.call(bindings.admit_take, event).kind, 'accepted')
        sessions = self.query('SELECT * FROM vehicle_driver_sessions')
        self.bind(d, v, remove=True)
        self.assertEqual(self.call(bindings.admit_take, event).kind, 'retry')
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_take, self.event(v, d, 2))
        self.assertEqual(self.query('SELECT * FROM vehicle_driver_sessions'), sessions)
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(1,)])

    def test_peer_take_handover_and_revocation_block_future_events(self):
        v, d, peer = self.vehicle(), self.device(), self.device(user=self.peer)
        self.bind(d, v); self.bind(peer, v, self.peer)
        self.call(bindings.admit_take, self.event(v, d))
        self.assertEqual(self.call(bindings.admit_take, self.event(v, peer), user=self.peer).kind, 'accepted')
        self.assertEqual(self.query('SELECT user_id FROM vehicle_driver_sessions WHERE ended_at IS NULL'), [(self.peer.user_id,)])
        self.call(lifecycle.revoke_device, peer.device_ref, user=self.peer)
        with self.assertRaises(VehicleIdentityError):
            self.call(bindings.admit_take, self.event(v, peer, 2), user=self.peer)
        self.assertEqual(len(self.query('SELECT * FROM registered_device_vehicle_bindings')), 2)

    def test_retirement_blocks_new_take_and_bind_rollback(self):
        d, v = self.device(), self.vehicle()
        with self.assertRaises(RuntimeError):
            with self.connection() as conn:
                with conn.transaction():
                    bindings.bindings(conn, self.current, d.device_ref, v.vehicle_ref)
                    raise RuntimeError('rollback')
        self.assertEqual(self.query('SELECT * FROM registered_device_vehicle_bindings'), [])
        self.bind(d, v)
        self.call(lifecycle.retire_vehicle, v.vehicle_ref)
        with self.assertRaises(VehicleIdentityError): self.call(bindings.admit_take, self.event(v, d))
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events'), [(0,)])

    def test_concurrent_take_and_delete_have_serial_outcome(self):
        d, v = self.device(), self.vehicle()
        self.bind(d, v)
        event = self.event(v, d)
        def take():
            try: return self.call(bindings.admit_take, event).kind
            except VehicleIdentityError: return 'denied'
        with ThreadPoolExecutor(2) as executor:
            admission = executor.submit(take)
            removal = executor.submit(self.bind, d, v, remove=True)
            result = admission.result(); removal.result()
        self.assertIn(result, ('accepted', 'denied'))
        self.assertEqual(self.query('SELECT * FROM registered_device_vehicle_bindings'), [])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_events')[0][0], int(result == 'accepted'))

    def test_migration_shape_privileges_cascade_and_rerun(self):
        rows = self.query("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema=%s AND table_name='registered_device_vehicle_bindings' ORDER BY ordinal_position", (self.schema,))
        self.assertEqual(rows, [('device_id', 'integer'), ('vehicle_id', 'integer')])
        for role in ('anon', 'authenticated'):
            self.assertFalse(self.query("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')", (role, self.schema + '.registered_device_vehicle_bindings'))[0][0])
        with self.assertRaises(Exception): self.query(self.local_sql)
        d, v = self.device(), self.vehicle()
        self.bind(d, v)
        self.query('DELETE FROM registered_devices WHERE device_ref=%s', (d.device_ref,))
        self.assertEqual(self.query('SELECT * FROM registered_device_vehicle_bindings'), [])
        d = self.device(); self.bind(d, v)
        self.query('DELETE FROM vehicles WHERE vehicle_ref=%s', (v.vehicle_ref,))
        self.assertEqual(self.query('SELECT * FROM registered_device_vehicle_bindings'), [])
