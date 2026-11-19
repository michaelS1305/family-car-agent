"""Synthetic artifacts and mocked Apple processes only."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

spec = importlib.util.spec_from_file_location('upload', Path(__file__).with_name('testflight_upload.py'))
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.env = dict(GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/main',
                        GITHUB_REPOSITORY='michaelS1305/family-car-agent', GITHUB_RUN_ATTEMPT='1',
                        GITHUB_RUN_NUMBER='123', FCA_ASC_KEY_ID='ABCDEFGHIJ',
                        FCA_ASC_ISSUER_ID='11111111-1111-1111-1111-111111111111',
                        FCA_ASC_API_KEY_BASE64=base64.b64encode(b'-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----').decode())
        self.info = dict(CFBundleIdentifier='com.familycaragent.app', FCAEnvironment='production',
                         CFBundleVersion='1000.1.23', CFBundleShortVersionString='1.0.0')
        self.ipa = self.folder / 'FamilyCarAgent-Production.ipa'
        with zipfile.ZipFile(self.ipa, 'w') as archive:
            archive.writestr('Payload/FamilyCarAgent.app/Info.plist', plistlib.dumps(self.info))
        self.report = {key: True for key in (
            'distribution_signature_verified', 'signing_certificate_authorized_by_profile',
            'embedded_profile_verified', 'entitlements_match_requested', 'production_apns_entitlement_verified',
            'firebase_production_configuration_verified', 'app_intents_metadata_preserved',
            'ipa_roundtrip_verified', 'preflight_signing_verified')}
        self.report.update(bundle_id='com.familycaragent.app', environment='production',
                           ipa_sha256=hashlib.sha256(self.ipa.read_bytes()).hexdigest())
        self.write_report()

    def write_report(self):
        (self.folder / 'fca-production-signing-report.json').write_text(json.dumps(self.report))

    def test_build_numbers_unique_monotonic_and_bounded(self):
        numbers = [upload.build_number(str(n)) for n in (1, 99, 100, 9999, 10000)]
        self.assertEqual(numbers, ['1000.0.1', '1000.0.99', '1000.1.0', '1000.99.99', '1001.0.0'])
        for value in ('0', '-1', 'abc', '90000000'):
            with self.assertRaises(upload.UploadError): upload.build_number(value)

    def test_only_first_main_push_may_upload(self):
        for key, value in [('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                           ('GITHUB_REF', 'refs/heads/develop'), ('GITHUB_REPOSITORY', 'other/repo'),
                           ('GITHUB_RUN_ATTEMPT', '2')]:
            with patch.dict(os.environ, dict(self.env, **{key: value}), clear=True), patch.object(upload.subprocess, 'run') as run:
                with self.assertRaises(upload.UploadError): upload.upload(self.folder)
                run.assert_not_called()

    def test_exact_artifact_and_key_cleanup(self):
        def run(command, **kwargs):
            self.assertEqual(command[command.index('--file') + 1], str(self.ipa.resolve()))
            self.assertNotIn('FCA_ASC_API_KEY_BASE64', kwargs['env'])
            self.key_path = Path(command[command.index('--p8-file-path') + 1])
            self.assertTrue(self.key_path.exists())
            self.assertNotIn('synthetic', str(command))
            return Mock(returncode=0, stdout='{}')
        original = self.ipa.read_bytes()
        with patch.dict(os.environ, self.env, clear=True), patch.object(upload.subprocess, 'run', side_effect=run) as runner:
            upload.upload(self.folder)
            self.assertEqual(runner.call_count, 1)
        self.assertFalse(self.key_path.exists())
        self.assertEqual(original, self.ipa.read_bytes())

    def test_unverified_report_or_hash_or_build_blocks_upload(self):
        for field, value in [('entitlements_match_requested', False), ('ipa_sha256', 'wrong'), ('environment', 'development')]:
            original = self.report[field]
            self.report[field] = value
            self.write_report()
            with self.assertRaises(upload.UploadError): upload.verify_artifact(self.folder, '1000.1.23')
            self.report[field] = original
        self.write_report()
        with self.assertRaises(upload.UploadError): upload.verify_artifact(self.folder, '1')

    def test_apple_failure_is_private_and_never_retried(self):
        for outcome in [Mock(returncode=1, stdout=json.dumps({'product-errors': [{'code': -19232, 'message': 'PRIVATE'}]})),
                        subprocess.TimeoutExpired('PRIVATE', 1)]:
            with patch.dict(os.environ, self.env, clear=True), patch.object(upload.subprocess, 'run') as runner:
                if isinstance(outcome, Exception): runner.side_effect = outcome
                else: runner.return_value = outcome
                with self.assertRaises(upload.UploadError) as error: upload.upload(self.folder)
                self.assertNotIn('PRIVATE', str(error.exception))
                self.assertEqual(runner.call_count, 1)


if __name__ == '__main__': unittest.main()
