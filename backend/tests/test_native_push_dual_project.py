"""Synthetic multi-project routing; no provider credentials or database required."""
import asyncio
import base64
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from native_push_security import Config, ConfigurationError, for_platform, for_installation
from native_push_fcm import Fcm
from native_push_process import Supervisor, child_pass
import native_push_api as api
import native_push_registration as registration
import native_push_revocation as revocation
import native_push_reminders as reminders
from tests.test_native_push import CONFIG


def environment(mode='prod'):
    values = dict(NATIVE_PUSH_ENVIRONMENT=mode,
        NATIVE_PUSH_ANDROID_PACKAGE='com.familycaragent.app' if mode == 'prod' else 'il.fca.companion.dev',
        SUPABASE_URL='https://xrgijytfigcuxmdktvmd.supabase.co' if mode == 'prod' else 'https://jouhqvbxhsvkluwkqmdg.supabase.co',
        NATIVE_PUSH_IOS_PROD_ENABLED='true')
    for prefix, project, enc, fp in [('NATIVE_PUSH_', 'family-car-agent-dev', b'e', b'f'),
            ('NATIVE_PUSH_IOS_PROD_', 'family-car-agent', b'g', b'h')]:
        values.update({prefix+'PROJECT':project, prefix+'CREDENTIALS_FILE':os.path.abspath('unused-'+project+'.json'),
            prefix+'KEY_ID':project, prefix+'ENCRYPTION_KEY':base64.b64encode(enc*32).decode(),
            prefix+'FINGERPRINT_KEY':base64.b64encode(fp*32).decode()})
    return values


class DualProjectTests(unittest.TestCase):
    def test_registration_confirm_refresh_and_revoke_share_trusted_cohort(self):
        for mode in ('dev', 'prod'):
            with patch.dict(os.environ, environment(mode), clear=True):
                config = Config.load()
            for platform in ('android', 'ios'):
                conn, user, response = Mock(), Mock(user_id=1), Mock(headers={})
                ref = uuid4()
                conn.execute.return_value.fetchone.return_value = (platform, config.project)
                with patch.object(api, 'run', side_effect=lambda pool, op: op(conn)):
                    operations = [
                        (api.begin, registration, 'begin', (api.Begin(installation_ref=ref,
                            request_id=uuid4(), platform=platform, token='synthetic-token-value'), response, user, config, Mock())),
                        (api.confirm, registration, 'confirm', (ref, api.Confirm(challenge_ref=uuid4(),
                            nonce='a'*43), response, user, config, Mock())),
                        (api.revoke, registration, 'revoke', (ref, api.Revoke(expected_generation=1),
                            response, user, config, Mock())),
                        (api.events, api.refresh, 'events', (ref, response, 1, 20, None, user, config, Mock())),
                    ]
                    for operation, module, name, args in operations:
                        with self.subTest(mode=mode, platform=platform, operation=name), \
                                patch.object(module, name, return_value={}) as call:
                            operation(*args)
                            self.assertEqual(call.call_args.args[2], config)

    def test_trusted_matrix_and_no_fallback(self):
        for mode in ('dev', 'prod'):
            with patch.dict(os.environ, environment(mode), clear=True):
                android, ios = Config.load(), Config.load('ios')
                self.assertEqual(android.project, 'family-car-agent' if mode == 'prod' else 'family-car-agent-dev')
                self.assertEqual(ios.project, 'family-car-agent' if mode == 'prod' else android.project)
                self.assertEqual(ios.ios_topic, 'com.familycaragent.app' if mode == 'prod' else 'com.familycaragent.app.dev')
                self.assertTrue(android.supports('android'))
                self.assertTrue(ios.supports('ios'))
                self.assertEqual(android, ios)
                self.assertTrue(android.supports('ios'))
                self.assertTrue(ios.supports('android'))
                other = replace(android, project='family-car-agent-dev' if mode == 'prod' else 'family-car-agent')
                self.assertNotEqual(android.fingerprint('same-token'), other.fingerprint('same-token'))
                self.assertFalse(other.supports('android'))
                self.assertFalse(other.supports('ios'))
        env = environment()
        for key in [k for k in env if k.startswith('NATIVE_PUSH_IOS_PROD_')]:
            with self.subTest(missing=key), patch.dict(os.environ, {k:v for k,v in env.items() if k != key}, clear=True):
                with self.assertRaises(ConfigurationError): Config.load()
                with self.assertRaises(ConfigurationError): Config.load('ios')
        for key, value in [('NATIVE_PUSH_IOS_PROD_PROJECT','family-car-agent-push'),
                ('NATIVE_PUSH_IOS_PROD_PROJECT','family-car-agent-dev'),
                ('NATIVE_PUSH_IOS_PROD_ENABLED','false'), ('SUPABASE_URL','https://invalid.example')]:
            with patch.dict(os.environ, {**env,key:value}, clear=True), self.assertRaises(ConfigurationError):
                Config.load('ios')

    def test_stored_identity_routes_all_followup_operations(self):
        conn, user, ref = Mock(), Mock(user_id=1), uuid4()
        with patch.dict(os.environ, environment(), clear=True):
            base = Config.load()
            for platform, project in [('android','family-car-agent'),('ios','family-car-agent')]:
                conn.execute.return_value.fetchone.return_value = (platform,project)
                self.assertEqual(for_installation(conn,user,base,ref).project,project)
                self.assertEqual(conn.execute.call_args.args[1],(ref,1))
            for row in [None, ('ios','family-car-agent-dev'),('android','family-car-agent-dev'),('web','family-car-agent')]:
                conn.execute.return_value.fetchone.return_value = row
                with self.assertRaises(ConfigurationError): for_installation(conn,user,base,ref)
            response = Mock(headers={})
            conn.execute.return_value.fetchone.return_value = ('ios','family-car-agent')
            with patch.object(api,'run',side_effect=lambda pool,op:op(conn)):
                for operation, target, args in [
                    (api.confirm,api.registration.confirm,(ref,api.Confirm(challenge_ref=uuid4(),nonce='a'*43),response,user,base,Mock())),
                    (api.revoke,api.registration.revoke,(ref,api.Revoke(expected_generation=1),response,user,base,Mock())),
                ]:
                    with patch.object(api.registration, target.__name__,return_value={'code':'ACTIVE'}) as call:
                        operation(*args)
                        self.assertEqual(call.call_args.args[2].project,'family-car-agent')
                with patch.object(api.refresh,'events',return_value={'items':[]}) as call:
                    api.events(ref,response,1,20,None,user,base,Mock())
                    self.assertEqual(call.call_args.args[2].project,'family-car-agent')

    def test_prod_ios_registration_and_capability_use_same_project(self):
        with patch.dict(os.environ,environment(),clear=True):
            base, ios = Config.load(), Config.load('ios')
            self.assertEqual(for_platform(base,'ios'),ios)
            conn, ref, user = Mock(), uuid4(), Mock(user_id=1)
            with patch.object(registration,'scope'), patch.object(revocation,'permitted',return_value=False) as permitted:
                result = registration.begin(conn,user,ios,installation_ref=ref,request_id=uuid4(),platform='ios',token='synthetic')
                self.assertEqual(result['code'],'REGISTRATION_UNAVAILABLE')
                self.assertEqual(permitted.call_args.args[2],ios.project)
            conn.execute.return_value.fetchone.return_value = (1,revocation.digest('a'*64))
            self.assertEqual(revocation.cancel(conn,ios,ref,'a'*64)['code'],'REVOKED')
            self.assertEqual(conn.execute.call_args_list[0].args[1],(ref,ios.project))
            conn.reset_mock()
            self.assertEqual(registration.begin(conn,user,ios,installation_ref=ref,request_id=uuid4(),platform='web',token='synthetic')['code'],'REGISTRATION_UNAVAILABLE')
            conn.execute.assert_not_called()

    def test_dispatch_project_topic_and_cross_platform(self):
        with patch.dict(os.environ,environment(),clear=True):
            config = Config.load('ios')
        http, loader = Mock(), Mock()
        http.post.return_value.status_code = 200
        provider = Fcm(config,transport=http,loader=loader,clock=lambda:1000)
        provider._token, provider._until = 'synthetic', 2000
        for data in [{'kind':'registration_challenge','nonce':'synthetic'},
                     {'kind':'event','alert':{'title':'synthetic','body':'synthetic'}}]:
            result=provider.send('synthetic',data,expires_at=datetime.fromtimestamp(1100,timezone.utc),platform='ios')
            self.assertEqual(result.code,'accepted')
            self.assertIn('/projects/family-car-agent/messages:send',http.post.call_args.args[0])
            message=http.post.call_args.kwargs['json']['message']
            self.assertEqual(message['apns']['headers']['apns-topic'],'com.familycaragent.app')
            self.assertNotIn('android',message)
        result = provider.send('synthetic',{'kind':'event'},
            expires_at=datetime.fromtimestamp(1100,timezone.utc),platform='android')
        self.assertEqual(result.code,'accepted')
        message=http.post.call_args.kwargs['json']['message']
        self.assertEqual(message['android']['restricted_package_name'],'com.familycaragent.app')
        self.assertNotIn('apns',message)
        http.reset_mock()
        self.assertEqual(provider.send('synthetic',{},expires_at=datetime.now(timezone.utc),platform='web').code,'configuration')
        http.post.assert_not_called(); loader.assert_not_called()
        for project,email in [('family-car-agent-dev','fca-push-prod@family-car-agent.iam.gserviceaccount.com'),
                ('family-car-agent','wrong@family-car-agent.iam.gserviceaccount.com')]:
            loader.return_value={'type':'service_account','project_id':project,'client_email':email,
                'token_uri':'https://oauth2.googleapis.com/token','private_key':'never-used'}
            provider._until=0
            with self.assertRaises(ConfigurationError): provider.prepare()
            http.post.assert_not_called()

    def test_worker_single_project_bounded_passes_and_same_loader(self):
        async def check():
            supervisor=Supervisor()
            child=Mock(returncode=0); child.poll.return_value=0
            with patch('native_push_process.subprocess.Popen',return_value=child) as spawn:
                for _ in range(4): self.assertEqual(await supervisor.run(asyncio.Event()),'complete')
            self.assertEqual([c.args[0][-1] for c in spawn.call_args_list],['--run-pass']*4)
            self.assertEqual(supervisor.seconds,20)
        with patch.dict(os.environ,environment(),clear=True): asyncio.run(check())
        with patch.dict(os.environ,{**environment(),'NATIVE_PUSH_ENABLED':'true'},clear=True), \
                patch('native_push_worker.run_once') as run, patch('native_push_cleanup.cleanup'), \
                patch('native_push_process.ChildConnections'), patch('native_push_fcm.Fcm') as provider:
            self.assertEqual(child_pass('ios'),0)
            self.assertEqual(run.call_args.args[1],Config.load('ios'))
            self.assertEqual(provider.call_args.args[0],Config.load('ios'))

    def test_reminders_enqueue_all_projects_in_one_event(self):
        conn=Mock()
        conn.execute.return_value.fetchone.side_effect=[(True,),('event',)]
        conn.execute.return_value.fetchall.return_value=[('reservation_reminder',uuid4(),1,2,3,datetime.now(timezone.utc))]
        @contextmanager
        def connection(): yield conn
        with patch.dict(os.environ,{'NATIVE_PUSH_ENABLED':'true','NATIVE_PUSH_REMINDERS_ENABLED':'true'}):
            reminders.schedule(Mock(connection=connection),'family-car-agent-dev')
        sql, params=conn.execute.call_args.args
        self.assertIn('INSERT INTO native_push_deliveries',sql)
        self.assertNotIn('provider_project=%s',sql)
        self.assertIn("user_id=%s AND status='active'",sql)
        self.assertEqual(len(params),2)

    def test_missing_ios_credentials_never_fall_back_or_open_database(self):
        env=environment(); del env['NATIVE_PUSH_IOS_PROD_CREDENTIALS_FILE']
        with patch.dict(os.environ,{**env,'NATIVE_PUSH_ENABLED':'true'},clear=True), \
                patch('native_push_process.ChildConnections') as pool, \
                patch('native_push_fcm.Fcm') as provider:
            self.assertEqual(child_pass('ios'),1)
            pool.assert_not_called(); provider.assert_not_called()
            with self.assertRaises(ConfigurationError): Config.load()
        with patch.dict(os.environ,environment(),clear=True):
            config=Config.load('ios')
        http=Mock()
        provider=Fcm(config,transport=http,loader=Mock(side_effect=FileNotFoundError('synthetic')))
        self.assertEqual(provider.send('synthetic',{'kind':'registration_challenge'},
            expires_at=datetime.now(timezone.utc),platform='ios').code,'configuration')
        http.post.assert_not_called()

    def test_unknown_owned_installation_denies_without_config_fallback(self):
        conn=Mock(); conn.execute.return_value.fetchone.return_value=None
        operation=Mock()
        with patch.dict(os.environ,environment(),clear=True): base=Config.load()
        with patch.object(Config,'load') as load, patch.object(registration,'scope') as scope:
            result=api.owned_operation(conn,Mock(user_id=1),base,uuid4(),operation)
            self.assertEqual(result,{'code':'REGISTRATION_UNAVAILABLE'})
            scope.assert_called_once()
            with self.assertRaises(api.refresh.RefreshError) as caught:
                api.owned_operation(conn,Mock(user_id=1),base,uuid4(),operation,inbox=True)
            self.assertEqual(caught.exception.code,'NATIVE_PUSH_ACCESS_DENIED')
            self.assertEqual(caught.exception.status,403)
            load.assert_not_called(); operation.assert_not_called()
