"""Offline configuration and FCM package-boundary regression tests."""
import base64
from dataclasses import replace
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from native_push_security import Config, ConfigurationError
from native_push_fcm import Fcm
import native_push_registration as registration
from tests.test_native_push import CONFIG
from tests import test_native_push_api


class IsolationTests(unittest.TestCase):
    def environment(self, name='dev'):
        return dict(NATIVE_PUSH_PROJECT='family-car-agent-dev',
            NATIVE_PUSH_CREDENTIALS_FILE=os.path.abspath('offline-unused.json'),
            NATIVE_PUSH_KEY_ID='fixture',
            NATIVE_PUSH_ENCRYPTION_KEY=base64.b64encode(b'e'*32).decode(),
            NATIVE_PUSH_FINGERPRINT_KEY=base64.b64encode(b'f'*32).decode(),
            NATIVE_PUSH_ENVIRONMENT=name,
            NATIVE_PUSH_ANDROID_PACKAGE='il.fca.companion.dev' if name=='dev' else 'il.fca.companion',
            SUPABASE_URL='https://jouhqvbxhsvkluwkqmdg.supabase.co' if name=='dev'
                else 'https://xrgijytfigcuxmdktvmd.supabase.co')

    def test_environment_matrix_and_missing_values(self):
        for name in ('dev','prod'):
            env=self.environment(name)
            with patch.dict(os.environ,env,clear=True):
                config=Config.load()
                self.assertEqual(config.environment,name)
                self.assertEqual(config.android_package,env['NATIVE_PUSH_ANDROID_PACKAGE'])
            for field in env:
                with self.subTest(name=name,missing=field):
                    missing={k:v for k,v in env.items() if k!=field}
                    with patch.dict(os.environ,missing,clear=True),self.assertRaises(ConfigurationError):
                        Config.load()
            for field,value in [('NATIVE_PUSH_ENVIRONMENT','unknown'),
                ('NATIVE_PUSH_ANDROID_PACKAGE',self.environment('prod' if name=='dev' else 'dev')['NATIVE_PUSH_ANDROID_PACKAGE']),
                ('SUPABASE_URL',self.environment('prod' if name=='dev' else 'dev')['SUPABASE_URL']),
                ('NATIVE_PUSH_PROJECT','another-project')]:
                with self.subTest(name=name,field=field):
                    with patch.dict(os.environ,{**env,field:value},clear=True),self.assertRaises(ConfigurationError):
                        Config.load()

    def test_mock_provider_rejects_cross_package_for_challenge_refresh_and_retry(self):
        # This models Google's documented restriction, not a live FCM proof.
        for package in ('il.fca.companion.dev','il.fca.companion'):
            transport=Mock()
            def send(url, **kwargs):
                message=kwargs['json']['message']
                self.assertEqual(message['android']['restricted_package_name'],package)
                self.assertNotIn('apns',message)
                return Mock(status_code=200 if message['token']==package else 400,
                            json=lambda:{},headers={})
            transport.post.side_effect=send
            provider=Fcm(replace(CONFIG,android_package=package),transport=transport,clock=lambda:1000)
            provider._token,provider._until='offline-access',2000
            for data in ({'kind':'registration_challenge'},{'kind':'refresh','version':'1'}):
                for attempt in range(2):
                    for token,expected in ((package,'accepted'),('other-package','invalid_payload')):
                        self.assertEqual(provider.send(token,data,expires_at=datetime.fromtimestamp(1060,timezone.utc),
                            platform='android').code,expected)

    def test_unsupported_platform_never_reaches_credentials_or_network(self):
        transport,loader=Mock(),Mock()
        provider=Fcm(CONFIG,transport=transport,loader=loader)
        for platform in ('ios','web','ANDROID',''):
            self.assertEqual(provider.send('fixture',{},expires_at=datetime.now(timezone.utc),
                platform=platform).code,'configuration')
            conn=Mock()
            self.assertEqual(registration.begin(conn,None,CONFIG,installation_ref=uuid4(),
                request_id=uuid4(),platform=platform,token='fixture')['code'],'REGISTRATION_UNAVAILABLE')
            conn.execute.assert_not_called()
        loader.assert_not_called()
        transport.post.assert_not_called()

    def test_activation_refuses_legacy_unsupported_installation(self):
        conn=Mock()
        conn.execute.return_value.fetchone.return_value=None
        with patch.object(registration,'scope'):
            result=registration.confirm(conn,Mock(user_id=1),CONFIG,installation_ref=uuid4(),
                                        challenge_ref=uuid4(),nonce='fixture')
        self.assertEqual(result['code'],'REGISTRATION_UNAVAILABLE')
        self.assertIn("platform='android'",conn.execute.call_args.args[0])


class IsolationApiTests(unittest.TestCase):
    def test_unsupported_platform_and_claimed_identity_rejected(self):
        import native_push_api as api
        fixture=test_native_push_api.ApiTests()
        fixture.setUp()
        with patch.object(api,'run') as run:
            for platform in ('ios','web',''):
                self.assertEqual(fixture.client.post('/api/native-push/registrations',
                    json={**fixture.body,'platform':platform}).status_code,422)
            for field in ('android_package','firebase_app_id','environment'):
                self.assertEqual(fixture.client.post('/api/native-push/registrations',
                    json={**fixture.body,field:'untrusted'}).status_code,422)
            run.assert_not_called()
