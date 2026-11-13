"""Synthetic-only iOS payload and cancellation authority checks."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from tests.test_native_push import CONFIG
from native_push_fcm import Fcm
from native_push_ios import alert, TOPIC
import native_push_revocation as revocation


class IosTests(unittest.TestCase):
    def test_four_events_and_missing_authoritative_data(self):
        for kind in ('vehicle_taken','vehicle_returned','reservation_reminder','maintenance_reminder'):
            value=alert(kind,'Synthetic member','Synthetic vehicle',datetime.now(timezone.utc))
            self.assertIn('Synthetic vehicle',value['body'])
            self.assertIsNone(alert(kind,'Synthetic member',None))
        self.assertIsNone(alert('vehicle_taken',None,'vehicle'))
        self.assertIsNone(alert('reservation_reminder','member','vehicle'))
        self.assertIsNone(alert('other','member','vehicle'))
        when=datetime(2026,11,12,10,tzinfo=timezone.utc)
        reservation=alert('reservation_reminder','member','vehicle',when,when+timedelta(hours=1))
        self.assertIn('12:00',reservation['body']); self.assertIn('13:00',reservation['body'])
        maintenance=alert('maintenance_reminder','member','vehicle',when,description='Synthetic maintenance')
        self.assertIn('Synthetic maintenance',maintenance['body'])

    def test_apns_and_android_are_separate(self):
        http=Mock(); http.post.return_value.status_code=200
        provider=Fcm(CONFIG,transport=http,clock=lambda:1000)
        provider._token,provider._until='synthetic',2000
        for platform,data in [('android',{'kind':'refresh','version':'1'}),
            ('ios',{'kind':'event','alert':alert('vehicle_taken','Member','Vehicle')}),
            ('ios',{'kind':'registration_challenge','nonce':'synthetic'})]:
            result=provider.send('synthetic-token',data,expires_at=datetime.fromtimestamp(2000,timezone.utc),platform=platform)
            self.assertEqual(result.code,'accepted')
            message=http.post.call_args.kwargs['json']['message']
            if platform=='android':
                self.assertNotIn('apns',message); self.assertEqual(message['data'],data)
            else:
                self.assertNotIn('android',message)
                headers=message['apns']['headers']
                self.assertEqual(headers['apns-topic'],TOPIC)
                self.assertEqual(headers['apns-expiration'],'1120')
                challenge=data['kind']=='registration_challenge'
                self.assertEqual(headers['apns-push-type'],'background' if challenge else 'alert')
                self.assertEqual(headers['apns-priority'],'5' if challenge else '10')
                self.assertEqual('alert' in message['apns']['payload']['aps'],not challenge)

    def test_prod_ios_fails_before_credentials(self):
        loader=Mock(); http=Mock()
        provider=Fcm(replace(CONFIG,environment='prod'),transport=http,loader=loader)
        self.assertEqual(provider.send('x',{},expires_at=datetime.now(timezone.utc),platform='ios').code,'configuration')
        loader.assert_not_called(); http.post.assert_not_called()

    def test_wrong_capability_does_not_mutate(self):
        conn=Mock(); conn.execute.return_value.fetchone.return_value=(1,revocation.digest('a'*64))
        self.assertEqual(revocation.cancel(conn,CONFIG,uuid4(),'b'*64)['code'],'REGISTRATION_UNAVAILABLE')
        self.assertEqual(conn.execute.call_count,1)

    def test_valid_capability_retires_all_generations_and_pending_challenges(self):
        conn=Mock(); conn.execute.return_value.fetchone.return_value=(1,revocation.digest('a'*64))
        self.assertEqual(revocation.cancel(conn,CONFIG,uuid4(),'a'*64)['code'],'REVOKED')
        queries=[call.args[0] for call in conn.execute.call_args_list]
        self.assertTrue(any('COALESCE(revoked_at' in q for q in queries))
        update=next(q for q in queries if 'UPDATE native_push_installations' in q)
        self.assertIn("platform='ios'",update)
        self.assertNotIn('generation=%s',update)
        self.assertTrue(any("status='cancelled'" in q for q in queries))

    def test_preparation_cannot_replace_authority_or_restore_retired_ref(self):
        for owner,secret,retired in [(2,'a'*64,None),(1,'b'*64,None),(1,'a'*64,datetime.now(timezone.utc))]:
            conn=Mock(); conn.execute.return_value.fetchone.return_value=(owner,revocation.digest(secret),retired)
            with patch.object(revocation,'scope'):
                result=revocation.prepare(conn,Mock(user_id=1),CONFIG,uuid4(),'a'*64)
            self.assertEqual(result['code'],'REGISTRATION_UNAVAILABLE')
            self.assertEqual(conn.execute.call_count,1)
