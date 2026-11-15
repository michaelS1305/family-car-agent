import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import auth_service
from identity import AuthenticatedSupabaseUser


class AppleCredentialApiTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('apple_api_test', Path(__file__).resolve().parents[1] / 'apple_credentials_api.py')
        self.api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'database': types.SimpleNamespace(pool=Mock())}):
            spec.loader.exec_module(self.api)
        app = FastAPI()
        app.include_router(self.api.router)
        app.dependency_overrides[auth_service.get_authenticated_supabase_user] = lambda: AuthenticatedSupabaseUser('verified-owner')
        self.app, self.client = app, TestClient(app)
        self.body = {'code':'PRIVATE_CODE_SENTINEL','nonce':'PRIVATE_NONCE_SENTINEL'}

    def test_uses_verified_subject_only(self):
        with patch.object(self.api,'capture',return_value={'status':'stored'}) as call:
            response = self.client.post('/api/account/apple-credential',json=self.body)
            self.assertEqual(response.status_code,200)
            self.assertEqual(call.call_args.args[1:], ('verified-owner',self.body['code'],self.body['nonce']))
            self.assertEqual(response.json(),{'status':'stored'})

    def test_validation_never_echoes_secrets(self):
        with patch.object(self.api,'capture') as call:
            for body in (dict(self.body,user_id='other'),dict(self.body,code={'secret':'PRIVATE_CODE_SENTINEL'}),
                         dict(self.body,nonce='short'),dict(self.body,code='x'*9000)):
                response = self.client.post('/api/account/apple-credential',json=body)
                self.assertEqual(response.status_code,422)
                self.assertEqual(response.json(),{'status':'invalid_request'})
            call.assert_not_called()

    def test_no_bearer_and_safe_unavailable(self):
        with patch.object(self.api,'capture',return_value={'status':'unavailable'}):
            response = self.client.post('/api/account/apple-credential',json=self.body)
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.json(),{'status':'unavailable'})
        self.app.dependency_overrides.clear()
        with patch.object(self.api,'capture') as call:
            self.assertEqual(self.client.post('/api/account/apple-credential',json=self.body).status_code,401)
            call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
