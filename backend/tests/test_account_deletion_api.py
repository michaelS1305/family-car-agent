import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth_service
from identity import AuthenticatedSupabaseUser
from deletion_gate import IdentityUnavailable


def load_api():
    spec = importlib.util.spec_from_file_location('deletion_api_test', Path(__file__).resolve().parents[1] / 'account_deletion_api.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'database': types.SimpleNamespace(pool=Mock())}):
        spec.loader.exec_module(module)
    return module


class DeletionApiTests(unittest.TestCase):
    def setUp(self):
        self.api = load_api()
        self.app = FastAPI()
        self.app.include_router(self.api.router)
        self.subject = str(uuid4())
        self.app.dependency_overrides[auth_service.get_deletion_identity] = lambda: AuthenticatedSupabaseUser(self.subject)
        self.client = TestClient(self.app)

    def test_explicit_confirmation_and_target_injection_rejection(self):
        with patch.object(self.api.deletion, 'confirm', return_value={'status':'draining'}) as confirm:
            for body in ({}, {'confirmation':True}, {'confirmation':'yes'},
                         {'confirmation':'DELETE_MY_ACCOUNT','user_id':17},
                         {'confirmation':'DELETE_MY_ACCOUNT','family_id':42},
                         {'confirmation':'DELETE_MY_ACCOUNT','successor':8}):
                self.assertEqual(self.client.post('/api/account/deletion',json=body).status_code, 422)
            confirm.assert_not_called()
            response = self.client.post('/api/account/deletion', json={'confirmation':'DELETE_MY_ACCOUNT'})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json(), {'status':'draining'})
            self.assertEqual(response.headers['Link'], self.api.APPLE_HELP_LINK)
            confirm.assert_called_once_with(self.api.pool, self.subject)

    def test_status_and_preview_only_use_verified_identity(self):
        for endpoint, service, result in (('/preview','preview',{'consequence':'personal'}),
                                          ('','status',{'status':'auth_pending'})):
            with patch.object(self.api.deletion, service, return_value=result) as call:
                response = self.client.get('/api/account/deletion'+endpoint, params={'user_id':'other'})
                self.assertEqual(response.json(),result)
                self.assertEqual(response.headers['Link'], self.api.APPLE_HELP_LINK)
                call.assert_called_once_with(self.api.pool,self.subject)

    def test_missing_bearer_cannot_confirm(self):
        self.app.dependency_overrides.clear()
        with patch.object(self.api.deletion,'confirm') as confirm:
            self.assertEqual(self.client.post('/api/account/deletion',json={'confirmation':'DELETE_MY_ACCOUNT'}).status_code,401)
            confirm.assert_not_called()

    def test_apple_help_is_generic_and_available_without_session(self):
        self.app.dependency_overrides.clear()
        with patch.object(self.api.deletion, 'status') as status, patch.object(self.api.pool, 'connection') as db:
            response = self.client.get('/api/account/deletion/apple-instructions')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.json()), {'instructions', 'url'})
            self.assertTrue(response.json()['url'].startswith('https://support.apple.com/'))
            self.assertNotIn(self.subject, response.text)
            status.assert_not_called()
            db.assert_not_called()

    def test_help_discoverable_before_confirmation_and_without_auth_afterwards(self):
        with patch.object(self.api.deletion, 'preview', return_value={'consequence': 'personal'}), \
             patch.object(self.api.deletion, 'confirm') as confirm:
            preview = self.client.get('/api/account/deletion/preview')
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.json(), {'consequence': 'personal'})
            help_path = preview.headers['Link'].split('>')[0][1:]
            confirm.assert_not_called()
        self.app.dependency_overrides.clear()
        response = self.client.get(help_path)
        self.assertEqual(response.status_code, 200)
        self.assertIn('support.apple.com', response.json()['url'])
        self.assertNotIn('delivered', response.json())

    def test_live_gate_applies_to_both_normal_auth_dependencies(self):
        credentials = types.SimpleNamespace(scheme='bearer',credentials='signed-token')
        with patch.object(auth_service,'_verify_authenticated_credentials',return_value=self.subject), \
             patch.object(auth_service,'check_live_identity',side_effect=IdentityUnavailable()), \
             patch.object(auth_service,'lookup_internal_user') as lookup:
            for dependency in (auth_service.get_current_user,auth_service.get_authenticated_supabase_user):
                with self.assertRaises(IdentityUnavailable):
                    dependency(credentials)
            lookup.assert_not_called()
            self.assertEqual(auth_service.get_deletion_identity(credentials).auth_user_id,self.subject)

    def test_recovery_startup_shutdown_and_retry_without_browser(self):
        async def scenario():
            started = asyncio.Event()
            def work(pool, should_stop):
                asyncio.get_running_loop()  # intentionally fails in worker thread
            with patch.object(self.api.deletion,'run_due',side_effect=work), \
                 patch.object(self.api.deletion,'_log',side_effect=lambda stage: started.set()) as log:
                # Event loop callback for thread-safe progress signal.
                loop = asyncio.get_running_loop()
                log.side_effect = lambda stage: loop.call_soon_threadsafe(started.set)
                async with self.api.deletion_lifespan(self.app):
                    await asyncio.wait_for(started.wait(),2)
                log.assert_called_once_with('worker_retry')
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
