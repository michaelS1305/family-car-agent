"""Production compatibility with synthetic keys/providers only."""
import base64
from dataclasses import replace
import json
import os
import unittest
from unittest.mock import patch, MagicMock
from cryptography.hazmat.primitives import serialization
from apple_credentials_security import Config, CaptureUnavailable
from apple_credentials import capture
import apple_revocation as revocation
from tests import test_apple_credentials as existing
from tests.test_apple_credentials import configuration

PROD_URL = 'https://xrgijytfigcuxmdktvmd.supabase.co'

class ProductionCaptureRegression(existing.CaptureTests):
    def setUp(self):
        super().setUp()
        self.config = replace(self.config, environment='prod', client='com.familycaragent.app', team='GT43M39TLK')

class ProductionExchangeRegression(existing.ExchangeTests):
    def setUp(self):
        super().setUp()
        self.config = replace(self.config, environment='prod', client='com.familycaragent.app', team='GT43M39TLK')
        self.claims['aud'] = self.config.client

class ProductionConfigTests(unittest.TestCase):
    def environment(self):
        config=configuration()
        pem=config.private_key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        return dict(APPLE_CREDENTIAL_ENVIRONMENT='prod', APPLE_NATIVE_CLIENT_ID='com.familycaragent.app',
            SUPABASE_URL=PROD_URL, APPLE_TEAM_ID='GT43M39TLK', APPLE_KEY_ID='KLMNOPQRST',
            APPLE_PRIVATE_KEY_BASE64=base64.b64encode(pem).decode(), APPLE_CREDENTIAL_ACTIVE_KEY_ID='v1',
            APPLE_CREDENTIAL_KEYS_JSON=json.dumps({'v1':base64.b64encode(b'a'*32).decode()}))

    def test_production_config_missing_and_cross_environment_rejected(self):
        env=self.environment()
        with patch.dict(os.environ,env,clear=True):
            config=Config.load()
            self.assertEqual((config.environment,config.client),('prod','com.familycaragent.app'))
        for key in env:
            with self.subTest(missing=key),patch.dict(os.environ,{k:v for k,v in env.items() if k!=key},clear=True):
                with self.assertRaises(CaptureUnavailable): Config.load()
        for key,value in [('APPLE_NATIVE_CLIENT_ID','com.familycaragent.app.dev'),
                ('APPLE_CREDENTIAL_ENVIRONMENT','dev'),('APPLE_TEAM_ID','ABCDEFGHIJ'),
                ('SUPABASE_URL','https://jouhqvbxhsvkluwkqmdg.supabase.co')]:
            with patch.dict(os.environ,{**env,key:value},clear=True),self.assertRaises(CaptureUnavailable): Config.load()

    def test_all_push_key_cohorts_are_separate(self):
        env=self.environment()
        for key in ('NATIVE_PUSH_ENCRYPTION_KEY','NATIVE_PUSH_FINGERPRINT_KEY',
                    'NATIVE_PUSH_IOS_PROD_ENCRYPTION_KEY','NATIVE_PUSH_IOS_PROD_FINGERPRINT_KEY'):
            with patch.dict(os.environ,{**env,key:base64.b64encode(b'a'*32).decode()},clear=True):
                with self.assertRaises(CaptureUnavailable): Config.load()

    def test_ciphertext_cannot_cross_environment_owner_subject_or_generation(self):
        dev=configuration(); prod=replace(dev,environment='prod',client='com.familycaragent.app')
        encrypted=dev.seal('synthetic','owner','subject',1)
        for config,owner,subject,generation in [(prod,'owner','subject',1),(dev,'other','subject',1),
                (dev,'owner','other',1),(dev,'owner','subject',2)]:
            with self.assertRaises(CaptureUnavailable): config.open(encrypted,'v1',owner,subject,generation)
        self.assertEqual(dev.open(encrypted,'v1','owner','subject',1),'synthetic')

    def test_revocation_identity_uses_server_environment_including_resumed_jobs(self):
        for url,expected in [(PROD_URL,('prod','com.familycaragent.app')),
                ('https://jouhqvbxhsvkluwkqmdg.supabase.co',('dev','com.familycaragent.app.dev'))]:
            with patch.dict(os.environ,{'SUPABASE_URL':url},clear=True):
                row=(*expected,'subject',1,'v1',b'cipher','owner','stored')
                self.assertTrue(revocation._valid_credential(row,'owner'))
                self.assertFalse(revocation._valid_credential(row,'other'))
                other=('dev','com.familycaragent.app.dev') if expected[0]=='prod' else ('prod','com.familycaragent.app')
                self.assertFalse(revocation._valid_credential((*other,*row[2:]),'owner'))
        with patch.dict(os.environ,{},clear=True): self.assertFalse(revocation._valid_credential(row,'owner'))

    def test_production_revocation_uses_production_audience(self):
        config=replace(configuration(),environment='prod',client='com.familycaragent.app',team='GT43M39TLK')
        http=MagicMock(); http.__enter__.return_value=http
        http.post.return_value.__enter__.return_value.status_code=200
        self.assertEqual(revocation.revoke(config,'synthetic-refresh',http=http),'apple_revocation_confirmed')
        self.assertEqual(http.post.call_args.kwargs['data']['client_id'],'com.familycaragent.app')
