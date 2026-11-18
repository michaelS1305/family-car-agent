"""Native producer exercised through real Companion and Shortcut admission."""
from dataclasses import replace
from datetime import timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import carplay_adapter
import native_push_outbox as outbox
import vehicle_bindings
from tests import test_device_bindings as fixtures


@unittest.skipUnless(os.getenv('GEMINI_TEST_DATABASE_URL'),'Requires disposable PostgreSQL')
class IngressTests(unittest.TestCase):
    connection=fixtures.BindingPostgresTests.connection
    drop_schema=fixtures.BindingPostgresTests.drop_schema
    query=fixtures.BindingPostgresTests.query
    person=fixtures.BindingPostgresTests.person
    call=fixtures.BindingPostgresTests.call
    vehicle=fixtures.BindingPostgresTests.vehicle
    device=fixtures.BindingPostgresTests.device
    event=fixtures.BindingPostgresTests.event
    bind=fixtures.BindingPostgresTests.bind
    home=fixtures.BindingPostgresTests.home
    return_evidence=fixtures.BindingPostgresTests.return_evidence

    def setUp(self):
        fixtures.BindingPostgresTests.setUp(self)
        source=(Path(__file__).resolve().parents[2]/'supabase/manual_migrations/2026101801_native_push_foundation.sql').read_text()
        ddl='CREATE TABLE public.native_push_installations ('+source.split('CREATE TABLE public.native_push_installations (',1)[1].split('-- Remove inherited default grants',1)[0]
        self.query(ddl.replace('public.',self.schema+'.'))
        self.setting=patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'true'})
        self.setting.start(); self.addCleanup(self.setting.stop)
        outbox.wakeup.clear()

    def test_companion_take_return_retries_preserve_receipts(self):
        self.home()
        device,vehicle=self.device(),self.vehicle()
        self.bind(device,vehicle)
        take=self.event(vehicle,device)
        with outbox.commit_boundary():
            self.assertEqual(self.call(vehicle_bindings.admit_take,take).transition,'opened')
        self.assertTrue(outbox.wakeup.is_set()); outbox.wakeup.clear()
        self.assertEqual(self.call(vehicle_bindings.admit_take,take).kind,'retry')
        self.assertFalse(outbox.wakeup.is_set())
        returned=self.event(vehicle,device,2,take.event_id)
        self.assertEqual(self.call(vehicle_bindings.admit_return,returned,self.return_evidence(returned)).transition,'returned')
        self.assertEqual(self.query('SELECT event_type FROM native_push_events ORDER BY occurred_at'),[('vehicle_taken',),('vehicle_returned',)])
        self.assertEqual(self.query('SELECT last_processed_sequence FROM registered_devices'),[(2,)])

    def test_companion_replay_and_redundant_do_not_notify(self):
        device,vehicle=self.device(),self.vehicle(); self.bind(device,vehicle)
        take=self.event(vehicle,device)
        self.call(vehicle_bindings.admit_take,take)
        redundant=self.event(vehicle,device,2)
        self.call(vehicle_bindings.admit_take,redundant)
        earlier=replace(self.event(vehicle,device,3),occurred_at=take.occurred_at-timedelta(seconds=1))
        self.call(vehicle_bindings.admit_take,earlier)
        self.assertEqual(self.query('SELECT count(*) FROM native_push_events'),[(1,)])

    def test_carplay_uses_same_producer_without_duplicate(self):
        self.query('CREATE TABLE carplay_vehicle_bindings(user_id integer PRIMARY KEY,family_id integer,vehicle_id integer)')
        vehicle=self.vehicle()
        with self.connection() as conn:
            carplay_adapter.bind_vehicle(conn,self.current,vehicle.vehicle_ref)
        acquisition=uuid4()
        for disconnect,expected in [(False,'opened'),(False,None),(True,'returned'),(True,None)]:
            with outbox.commit_boundary(),self.connection() as conn:
                result=carplay_adapter.transition(conn,self.current,acquisition,disconnect=disconnect)[0]
                self.assertEqual(result.transition,expected)
        self.assertEqual(self.query('SELECT event_type FROM native_push_events ORDER BY occurred_at'),[('vehicle_taken',),('vehicle_returned',)])
