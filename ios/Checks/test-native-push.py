"""Synthetic configuration only; never reads the owner's Firebase plist."""
import base64
import datetime as dt
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
from firebase_dev_config import BUNDLE, PROJECT, SENDER, validate, validate_bundle, decode

spec = importlib.util.spec_from_file_location("sign_dev", Path(__file__).with_name("sign-fca-dev.py"))
sign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign)


class PushChecks(unittest.TestCase):
    def config(self):
        return dict(BUNDLE_ID=BUNDLE, PROJECT_ID=PROJECT, GCM_SENDER_ID=SENDER,
                    GOOGLE_APP_ID=f"1:{SENDER}:ios:abcdef")

    def test_configuration_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "GoogleService-Info.plist"
            with self.assertRaises(ValueError): validate(path)
            path.write_bytes(b"not a plist")
            with self.assertRaises(ValueError): validate(path)
            for field in self.config():
                for replacement in (None, "wrong", 123):
                    value = self.config()
                    if replacement is None: del value[field]
                    else: value[field] = replacement
                    path.write_bytes(plistlib.dumps(value))
                    with self.assertRaises(ValueError): validate(path)
            path.write_bytes(plistlib.dumps(self.config()))
            validate(path)
            validate_bundle(Path(temp))
            nested = Path(temp) / "nested"
            nested.mkdir()
            (nested / path.name).write_bytes(path.read_bytes())
            with self.assertRaises(ValueError): validate_bundle(Path(temp))

    def test_secret_decode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "GoogleService-Info.plist"
            for value in ("", "not-base64"):
                with patch.dict(os.environ, FCA_IOS_DEV_GOOGLE_SERVICE_INFO_BASE64=value):
                    with self.assertRaises(ValueError): decode(path)
            raw = base64.b64encode(plistlib.dumps(self.config())).decode()
            with patch.dict(os.environ, FCA_IOS_DEV_GOOGLE_SERVICE_INFO_BASE64=raw):
                decode(path)
                with self.assertRaises(ValueError): decode(path)
            validate(path)

    def test_profile_and_final_entitlement_guards(self):
        entitlements = {"aps-environment": "development", "com.apple.developer.applesignin": ["Default"],
                        "get-task-allow": True, "application-identifier": f"{sign.TEAM}.{BUNDLE}",
                        "com.apple.developer.team-identifier": sign.TEAM,
                        "keychain-access-groups": [f"{sign.TEAM}.*"]}
        profile = {"Name": sign.PROFILE_NAME, "TeamIdentifier": [sign.TEAM],
                   "ExpirationDate": dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10),
                   "Platform": ["iOS"], "ProvisionedDevices": ["synthetic"],
                   "DeveloperCertificates": [b"synthetic"], "Entitlements": entitlements}
        result, _ = sign.verify_profile(profile)
        self.assertEqual(result["keychain-access-groups"], [f"{sign.TEAM}.{BUNDLE}"])
        sign.verify_push_entitlements(result)
        for value in (None, "production", ""):
            invalid = dict(entitlements)
            if value is None: del invalid["aps-environment"]
            else: invalid["aps-environment"] = value
            with self.assertRaises(sign.SignError): sign.verify_profile(dict(profile, Entitlements=invalid))
            with self.assertRaises(sign.SignError): sign.verify_push_entitlements(invalid)

    def test_delegate_and_workflow_boundaries(self):
        ios = Path(__file__).resolve().parents[1]
        source = ios / "Sources/FamilyCarAgent"
        delegate = (source / "OfflineEvents/VehicleBackgroundUploadTransport.swift").read_text(encoding="utf-8")
        for method in ("handleEventsForBackgroundURLSession", "transport.handleBackgroundEvents", "didRegisterForRemoteNotificationsWithDeviceToken", "didFailToRegisterForRemoteNotificationsWithError"):
            self.assertIn(method, delegate)
        runtime = (source / "OfflineEvents/VehicleSessionRuntime.swift").read_text(encoding="utf-8")
        self.assertIn("self?.invalidate(old)", runtime)
        self.assertIn("NativePushService.shared.invalidate()", runtime)
        info = plistlib.loads((ios / "Config/Info.Dev.plist").read_bytes())
        self.assertIs(info["FirebaseAppDelegateProxyEnabled"], False)
        self.assertIs(info["FirebaseMessagingAutoInitEnabled"], False)
        self.assertIs(info["FirebaseMessagingInstallationIdEnabled"], False)
        self.assertNotIn("remote-notification", info.get("UIBackgroundModes", []))
        workflow = (ios.parent / ".github/workflows/ios-dev-app-intents.yml").read_text()
        self.assertNotIn("pull_request", workflow)
        self.assertIn("github.ref == 'refs/heads/develop'", workflow)
        self.assertIn("--firebase-config", workflow)
        self.assertIn("if: always()", workflow)
        service = (source / "Push/NativePushService.swift").read_text(encoding="utf-8")
        self.assertNotIn("print(", service)
        self.assertNotIn("URLSession", service)
        self.assertIn("runtime.sessions.generation == identity.generation", service)


if __name__ == "__main__": unittest.main()
