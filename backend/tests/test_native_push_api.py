import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from identity import CurrentUser
import native_push_api as api
from tests.test_native_push import CONFIG


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app=FastAPI()
        self.app.include_router(api.router)
        self.user=CurrentUser(1,'Test',10,auth_user_id=str(uuid4()))
        self.app.dependency_overrides[api.get_current_user]=lambda:self.user
        self.app.dependency_overrides[api.configuration]=lambda:CONFIG
        self.app.dependency_overrides[api.vehicle_pool]=lambda:Mock()
        self.client=TestClient(self.app)
        self.body={'installation_ref':str(uuid4()),'request_id':str(uuid4()),'platform':'android','token':'mock-token-'+uuid4().hex}

    def test_unauthenticated(self):
        def denied(): raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user]=denied
        for path in ['/registrations','/installations/'+str(uuid4())+'/confirm','/installations/'+str(uuid4())+'/revoke']:
            self.assertEqual(self.client.post('/api/native-push'+path,json=self.body).status_code,401)

    def test_identity_and_project_injection_rejected(self):
        with patch.object(api,'run') as run:
            for field in ('user_id','family_id','provider_project'):
                self.assertEqual(self.client.post('/api/native-push/registrations',json={**self.body,field:'override'}).status_code,422)
            run.assert_not_called()

    def test_identity_passed_from_dependency_only(self):
        with patch.object(api,'run',side_effect=lambda pool,op:op(None)),patch.object(api.registration,'begin',return_value={'code':'CHALLENGE_PENDING'}) as begin:
            response=self.client.post('/api/native-push/registrations',json=self.body)
        self.assertEqual(response.status_code,202)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(begin.call_args.args[1],self.user)
        self.assertNotIn(self.body['token'],response.text)

    def test_commit_failure_does_not_wake(self):
        @contextmanager
        def connection():
            yield Mock()
            raise RuntimeError('commit failed')
        pool=Mock(); pool.connection=connection
        with patch.object(api.wakeup,'set') as wake,self.assertRaises(RuntimeError):
            api.run(pool,lambda conn:{'code':'CHALLENGE_PENDING'})
        wake.assert_not_called()

    def test_application_validation_never_echoes_token_or_nonce(self):
        import asyncio
        from types import SimpleNamespace
        from tests.test_main_identity import main
        request=SimpleNamespace(url=SimpleNamespace(path='/api/native-push/registrations'))
        response=asyncio.run(main.safe_disconnect_validation_error(request,Exception('private-token-and-nonce')))
        self.assertEqual(response.status_code,422)
        self.assertNotIn(b'private-token',response.body)
        self.assertIn(b'INVALID_NATIVE_PUSH_REQUEST',response.body)

    def test_events_requires_auth_and_valid_generation(self):
        path='/api/native-push/installations/'+str(uuid4())+'/events'
        for query in ('','?expected_generation=0','?expected_generation=1&limit=51','?expected_generation=1&cursor=bad'):
            self.assertEqual(self.client.get(path+query).status_code,422)
        def denied(): raise HTTPException(401)
        self.app.dependency_overrides[api.get_current_user]=denied
        self.assertEqual(self.client.get(path+'?expected_generation=1').status_code,401)

    def test_events_owner_from_auth_and_no_store(self):
        installation=uuid4()
        with patch.object(api,'run',side_effect=lambda pool,op:op(None)),patch.object(api.refresh,'events',return_value={'items':[],'has_more':False,'next_cursor':None}) as fetch:
            response=self.client.get('/api/native-push/installations/'+str(installation)+'/events?expected_generation=2&family_id=999&user_id=999')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(fetch.call_args.args[1],self.user)
        self.assertEqual(fetch.call_args.args[3:5],(installation,2))
