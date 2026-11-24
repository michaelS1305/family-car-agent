from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch
from tests import test_return_reconciliation as base
from take_session_metadata import MetadataRequest, snapshot
from vehicle_identity import VehicleIdentityError
from account_deletion import _checkpoint_vehicle_identity

class MetadataPostgresTests(base.ResolutionPostgresTests):
    def setUp(self):
        super().setUp()
        ddl=(Path(__file__).resolve().parents[2]/'supabase/manual_migrations/2026112401_take_session_metadata.sql').read_text()
        self.query(ddl.replace('public.',self.schema+'.').replace('BEGIN;','').replace('COMMIT;',''))
    def revision(self): return self.query('SELECT projection_revision FROM families WHERE id=10')[0][0]
    def metadata(self,event=None,user=1,device=None):
        e=event or self.taken
        body=MetadataRequest(request_id=uuid4(),takes=[dict(event_id=e.event_id,device_sequence=e.device_sequence,vehicle_ref=e.vehicle_ref)])
        with self.connection() as c: return snapshot(c,self.users[user],device or self.devices[user],body)
    def checkpoint_at_return(self):
        self.query('UPDATE families SET vehicle_finalized_through=%s,vehicle_reconciliation_generation=vehicle_reconciliation_generation+1 WHERE id=10',(self.original.occurred_at,))
        self.query('UPDATE vehicle_driver_sessions SET checkpoint_generation=(SELECT vehicle_reconciliation_generation FROM families WHERE id=10) WHERE family_id=10')
    def test_metadata_production_alias_backfill(self):
        self.checkpoint_at_return(); self.resolve(); before=self.revision()
        alias=replace(self.taken,event_id=uuid4(),device_sequence=15,occurred_at=self.now-timedelta(minutes=5))
        self.assertEqual(self.admit(alias).transition,'redundant_take')
        self.assertGreater(self.revision(),before)
        result=self.metadata(alias); item=result['items'][0]
        self.assertEqual(item['anchor_event_id'],str(self.taken.event_id))
        self.assertEqual(item['session_state'],'closed'); self.assertEqual(item['finality'],'provisional')
        revision=self.revision()
        self.assertEqual(self.metadata(alias)['items'],result['items'])
        self.assertEqual(self.revision(),revision); self.assertEqual(self.sequence(),15)
    def test_metadata_finalized(self):
        self.assertEqual(self.metadata()['items'][0]['session_state'],'open')
        self.checkpoint_at_return(); self.resolve(); before=self.revision()
        from vehicle_work import rolling_checkpoint,Budget
        with self.connection() as c:
            generation,boundary=c.execute('SELECT vehicle_reconciliation_generation,vehicle_finalized_through FROM families WHERE id=10 FOR UPDATE').fetchone()
            rolling_checkpoint(c,10,generation,boundary,self.now+timedelta(seconds=10),Budget())
        self.assertGreater(self.revision(),before)
        self.assertEqual(self.metadata()['items'][0]['finality'],'finalized')
    def test_metadata_replay_changes_alias(self):
        self.checkpoint_at_return(); self.resolve()
        alias=replace(self.taken,event_id=uuid4(),device_sequence=15,occurred_at=self.now-timedelta(minutes=5))
        self.admit(alias); old=self.metadata(alias)
        other=replace(self.taken,event_id=uuid4(),device_ref=self.devices[2],device_sequence=1,occurred_at=self.now-timedelta(minutes=10))
        self.admit(other,user=2); new=self.metadata(alias)
        self.assertGreater(new['projection_revision'],old['projection_revision'])
        self.assertEqual(new['items'][0]['anchor_event_id'],str(alias.event_id))
        self.assertEqual(new['items'][0]['session_state'],'open')
    def test_metadata_scope_and_revocation(self):
        for e in [replace(self.taken,device_sequence=12),replace(self.taken,vehicle_ref=self.vehicles[1]),replace(self.taken,event_id=uuid4())]:
            self.assertEqual(self.metadata(e)['items'][0]['status'],'unavailable')
        self.assertEqual(self.metadata(user=2)['items'][0]['status'],'unavailable')
        with self.assertRaises(VehicleIdentityError): self.metadata(user=2,device=self.devices[1])
        self.query('DELETE FROM registered_device_vehicle_bindings WHERE device_id=%s',(self.device_id,))
        self.assertEqual(self.metadata()['items'][0]['status'],'unavailable')
        self.query('UPDATE registered_devices SET revoked_at=clock_timestamp() WHERE id=%s',(self.device_id,))
        with self.assertRaises(VehicleIdentityError): self.metadata()
    def test_metadata_cleanup_and_rollback(self):
        before=self.revision()
        with self.assertRaises(RuntimeError):
            with self.connection() as c:
                c.execute('UPDATE vehicle_driver_sessions SET checkpoint_generation=checkpoint_generation WHERE family_id=10')
                raise RuntimeError('rollback')
        self.assertEqual(self.revision(),before)
        with self.connection() as c: _checkpoint_vehicle_identity(c,1,10)
        self.assertGreater(self.revision(),before)
        with self.assertRaises(VehicleIdentityError): self.metadata()

    def test_metadata_waits_for_projection_transaction(self):
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        from threading import Event
        from vehicle_lifecycle import _scope
        started=Event()
        def read():
            started.set()
            return self.metadata()
        before=self.revision()
        with ThreadPoolExecutor(max_workers=1) as threads:
            with self.connection() as c, _scope(c,self.users[1]):
                c.execute("UPDATE vehicle_driver_sessions SET ended_at=%s,end_reason='return' WHERE start_event_id=%s",(self.now,self.taken.event_id))
                future=threads.submit(read)
                self.assertTrue(started.wait(2))
                with self.assertRaises(TimeoutError): future.result(timeout=.1)
            result=future.result(timeout=10)
        self.assertGreater(result['projection_revision'],before)
        self.assertEqual(result['items'][0]['session_state'],'closed')


    def test_metadata_binding_and_retirement_order(self):
        self.checkpoint_at_return(); self.resolve()
        closed=self.metadata()
        self.query('DELETE FROM registered_device_vehicle_bindings WHERE device_id=%s',(self.device_id,))
        unavailable=self.metadata()
        self.assertEqual(unavailable['items'][0]['status'],'unavailable')
        self.assertGreater(unavailable['projection_revision'],closed['projection_revision'])
        self.assertGreaterEqual(unavailable['observed_at'],closed['observed_at'])
        self.query('INSERT INTO registered_device_vehicle_bindings(device_id,vehicle_id) VALUES(%s,%s)',(self.device_id,self.vehicle_id))
        restored=self.metadata()
        self.query('UPDATE vehicles SET retired_at=clock_timestamp() WHERE id=%s',(self.vehicle_id,))
        retired=self.metadata()
        self.assertEqual(retired['items'][0]['status'],'unavailable')
        self.assertGreater(retired['projection_revision'],restored['projection_revision'])


class MetadataApiTests(unittest.TestCase):
    def setUp(self):
        from tests.test_device_bindings import api
        from tests.test_vehicle_api import VehicleApiTests
        VehicleApiTests.setUp(self); self.api=api; self.app.include_router(api.router)
        self.url=f'/api/devices/{uuid4()}/take-session-metadata'
        self.body=dict(request_id=str(uuid4()),takes=[dict(event_id=str(uuid4()),device_sequence=15,vehicle_ref=str(uuid4()))])
    def test_bounds_and_identity(self):
        with patch.object(self.api,'take_metadata_snapshot',return_value={'items':[]}) as call:
            response=self.client.post(self.url,json=self.body)
            self.assertEqual(response.status_code,200); self.assertEqual(call.call_args.args[1],self.user)
            self.assertEqual(response.headers['cache-control'],'no-store')
            for takes in [[],self.body['takes']*65,self.body['takes']*2]:
                self.assertEqual(self.client.post(self.url,json={**self.body,'takes':takes}).status_code,422)
            self.assertEqual(self.client.post(self.url,json={**self.body,'projection_revision':1}).status_code,422)
