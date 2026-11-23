"""Focused authenticated route contract, no service startup or external I/O."""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from tests.test_device_bindings import api
from tests import test_vehicle_api


class ResolutionApiTests(unittest.TestCase):
    def setUp(self):
        test_vehicle_api.VehicleApiTests.setUp(self)
        self.app.include_router(api.router)
        self.event=uuid4()
        self.url=f'/api/devices/{uuid4()}/events/return/{self.event}/reconciliation'
        self.body={'reconciliation_id':str(uuid4()),'original_return':{
            'event_id':str(self.event),'vehicle_ref':str(uuid4()),'device_sequence':14,
            'occurred_at':'2026-11-23T11:22:46Z','take_event_id':str(uuid4()),
            'latitude':0.,'longitude':0.,'accuracy_m':10.,'location_at':'2026-11-23T11:22:46Z'},
            'verification':{'invoked_at':'2026-11-23T14:06:00Z','location_at':'2026-11-23T14:06:00Z',
                'latitude':0.,'longitude':0.,'accuracy_m':10.}}

    def test_disabled_until_owner_rollout(self):
        with patch.dict(os.environ,{'RETURN_RECONCILIATION_ENABLED':'false'}), patch.object(api.return_reconciliation,'reconcile_return',return_value=api.return_recovery.Refusal('RETURN_RECONCILIATION_DISABLED','Unavailable',503)) as call:
            self.assertEqual(self.client.post(self.url,json=self.body).status_code,503)
            self.assertFalse(call.call_args.kwargs['allow_new'])

    def test_route_passes_authenticated_identity_and_keeps_receipt_distinct(self):
        with patch.dict(os.environ,{'RETURN_RECONCILIATION_ENABLED':'true'}), patch.object(api.return_reconciliation,'reconcile_return',return_value={'kind':'resolved_current_state'}) as call:
            response=self.client.post(self.url,json=self.body)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['kind'],'resolved_current_state')
            self.assertEqual(call.call_args.args[1],self.user)
            self.assertEqual(call.call_args.args[2].device_sequence,14)
            self.assertEqual(response.headers['cache-control'],'no-store')

    def test_path_identity_and_extra_fields_fail(self):
        with patch.dict(os.environ,{'RETURN_RECONCILIATION_ENABLED':'true'}), patch.object(api.return_reconciliation,'reconcile_return') as call:
            self.body['original_return']['event_id']=str(uuid4())
            self.assertEqual(self.client.post(self.url,json=self.body).status_code,409)
            self.body['server_now']='2026-11-23T14:06:00Z'
            self.assertEqual(self.client.post(self.url,json=self.body).status_code,422)
            call.assert_not_called()

    def test_disabled_route_allows_committed_acknowledgment(self):
        with patch.dict(os.environ,{'RETURN_RECONCILIATION_ENABLED':'false'}), patch.object(api.return_reconciliation,'reconcile_return',return_value={'kind':'resolved_current_state'}) as call:
            response=self.client.post(self.url,json=self.body)
            self.assertEqual(response.status_code,200)
            self.assertFalse(call.call_args.kwargs['allow_new'])
            self.assertEqual(call.call_args.args[1],self.user)
