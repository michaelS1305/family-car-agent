"""Existing native binding regressions repeated with co-located families."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from tests import test_device_bindings as fixtures
from vehicle_identity import VehicleIdentityError

@unittest.skipUnless(os.environ.get('GEMINI_TEST_DATABASE_URL'), 'Isolated PostgreSQL not configured')
class SharedHomeIsolationPostgresTests(fixtures.BindingPostgresTests):
    def setUp(self):
        super().setUp()
        self.query("UPDATE families SET name='Same',home_address='Same',home_latitude=32,home_longitude=34")

    def test_shared_home_vehicle_device_bindings_and_sessions_are_independent(self):
        b=fixtures.bindings; lifecycle=fixtures.lifecycle
        a_vehicle, b_vehicle = self.vehicle(),self.vehicle(user=self.outsider)
        a_device, b_device = self.device(),self.device(user=self.outsider)
        self.bind(a_device,a_vehicle); self.bind(b_device,b_vehicle,self.outsider)
        for device,vehicle,user in [(a_device,b_vehicle,self.current),(a_device,a_vehicle,self.outsider),(b_device,b_vehicle,self.current)]:
            with self.assertRaises(VehicleIdentityError): self.bind(device,vehicle,user)
        a_take,b_take=self.event(a_vehicle,a_device),self.event(b_vehicle,b_device)
        self.assertEqual(self.call(b.admit_take,a_take).kind,'accepted')
        self.assertEqual(self.call(b.admit_take,b_take,user=self.outsider).kind,'accepted')
        self.assertEqual(self.query('SELECT count(DISTINCT family_id) FROM vehicle_events'),[(2,)])
        self.assertEqual(self.query('SELECT count(*) FROM vehicle_driver_sessions WHERE ended_at IS NULL'),[(2,)])
        event=self.event(a_vehicle,a_device,2,a_take.event_id)
        self.assertEqual(self.call(b.admit_return,event,self.return_evidence(event)).kind,'accepted')
        self.assertEqual(self.query('SELECT family_id FROM vehicle_driver_sessions WHERE ended_at IS NULL'),[(self.outsider.family_id,)])
        self.assertEqual([v.vehicle_ref for v in self.call(lifecycle.list_vehicles)],[a_vehicle.vehicle_ref])
        self.assertEqual([d.device_ref for d in self.call(lifecycle.list_devices)],[a_device.device_ref])
        self.assertEqual(self.query('SELECT count(*) FROM users WHERE family_id=%s',(self.outsider.family_id,)),[(1,)])

    def test_shared_coordinates_do_not_grant_realtime_topic_access(self):
        source=(Path(__file__).resolve().parents[2]/'supabase/schema_baseline/current_schema.sql').read_text()
        start='CREATE OR REPLACE FUNCTION public.can_receive_car_status_topic'
        sql=start+source.split(start,1)[1].split('$function$;',1)[0]+'$function$;'
        # Use the actual production predicate; substitute only isolated schema and
        # auth.uid() provider with a transaction-local synthetic identity.
        sql=sql.replace('public.',self.schema+'.').replace('auth.uid()',"current_setting('test.auth_uid')::uuid")
        self.query(sql)
        for user,other in [(self.current,self.outsider),(self.outsider,self.current)]:
            with self.connection() as conn:
                conn.execute("SELECT set_config('test.auth_uid',%s,true)",(str(user.auth_user_id),))
                self.assertTrue(conn.execute(f'SELECT {self.schema}.can_receive_car_status_topic(%s)',(f'family:{user.family_id}:car-status',)).fetchone()[0])
                self.assertFalse(conn.execute(f'SELECT {self.schema}.can_receive_car_status_topic(%s)',(f'family:{other.family_id}:car-status',)).fetchone()[0])

    def test_home_validation_uses_identity_and_preserves_500m_rule(self):
        b=fixtures.bindings
        with self.connection() as conn:
            for user in (self.current,self.outsider):
                b.verify_home(conn,user,SimpleNamespace(latitude=32.,longitude=34.,accuracy_m=500.))
                with self.assertRaises(VehicleIdentityError):
                    b.verify_home(conn,user,SimpleNamespace(latitude=32.,longitude=34.,accuracy_m=500.01))
            # Missing home in one family cannot borrow the other family's coordinates.
            conn.execute('UPDATE families SET home_latitude=NULL WHERE id=%s',(self.outsider.family_id,))
            with self.assertRaises(VehicleIdentityError) as rejected:
                b.verify_home(conn,self.outsider,SimpleNamespace(latitude=32.,longitude=34.,accuracy_m=10.))
            self.assertEqual(rejected.exception.code,'RETURN_HOME_UNAVAILABLE')
            b.verify_home(conn,self.current,SimpleNamespace(latitude=32.,longitude=34.,accuracy_m=10.))
