"""Synthetic configuration only; never reads the owner's Firebase plist."""
import base64
import hashlib
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
    def test_identity_requires_exact_profile_certificate(self):
        certificate = b"SYNTHETIC_CERTIFICATE"
        fingerprint = hashlib.sha1(certificate).hexdigest().upper()
        row = f'  1) {fingerprint} "PRIVATE_CERTIFICATE_NAME"\n'
        with patch.object(sign, "call", return_value=row.encode()) as call:
            self.assertEqual(sign.signing_identity(Path("temporary.keychain"), [certificate]), fingerprint)
            self.assertIn("-v", call.call_args.args)
        for output in (b"0 valid identities found", b"malformed", row.encode() * 2,
                       f' 1) {"0" * 40} "PRIVATE_OTHER"'.encode()):
            with self.subTest(output_kind=len(output)), patch.object(sign, "call", return_value=output):
                with self.assertRaises(sign.SignError) as caught:
                    sign.signing_identity(Path("temporary.keychain"), [certificate])
                self.assertNotIn("PRIVATE", str(caught.exception))
                self.assertNotIn(fingerprint, str(caught.exception))

    def test_signing_rejects_untrusted_invocation(self):
        for event, ref in (("pull_request", "refs/heads/develop"),
                           ("workflow_dispatch", "refs/heads/main"),
                           ("schedule", "refs/heads/develop")):
            with patch.object(sign.sys, "platform", "darwin"), patch.dict(sign.os.environ,
                    GITHUB_EVENT_NAME=event, GITHUB_REF=ref):
                with self.assertRaisesRegex(sign.SignError, "authorized develop workflow"):
                    sign.sign(Path("unused"), Path("unused"))

    def test_private_signing_output_is_suppressed(self):
        with patch.object(sign.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b"PRIVATE_SENTINEL"
            with self.assertRaises(sign.SignError) as caught:
                sign.call("Import", "security", "PRIVATE_SENTINEL")
            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_signing_failure_removes_temporary_workspace_and_keychain(self):
        entitlements = {"aps-environment":"development", "com.apple.developer.applesignin":["Default"],
                        "get-task-allow":True, "application-identifier":f"{sign.TEAM}.{BUNDLE}",
                        "com.apple.developer.team-identifier":sign.TEAM,
                        "keychain-access-groups":[f"{sign.TEAM}.*"]}
        profile = {"Name":sign.PROFILE_NAME, "TeamIdentifier":[sign.TEAM],
                   "ExpirationDate":dt.datetime.now()+dt.timedelta(days=1), "Platform":["iOS"],
                   "ProvisionedDevices":["synthetic"], "DeveloperCertificates":[b"synthetic"],
                   "Entitlements":entitlements}
        roots = []
        def decode(name, destination):
            roots.append(destination.parent)
            destination.write_bytes(b"synthetic")
        def call(label, *args):
            if label == "Provisioning profile decoding": return plistlib.dumps(profile)
            if label == "Read user Keychain search list": return b'"login.keychain"'
            if label == "Certificate import": raise sign.SignError("synthetic failure")
            return b""
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)/"FCA.app"; app.mkdir()
            (app/"Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":BUNDLE,"FCAEnvironment":"development"}))
            (app/"GoogleService-Info.plist").write_bytes(plistlib.dumps(self.config()))
            metadata=app/"Metadata.appintents"; metadata.mkdir()
            (metadata/"actions.data").write_bytes(b"FCATakeVehicleIntent FCAReturnVehicleIntent")
            with patch.object(sign.sys,"platform","darwin"), patch.dict(sign.os.environ,
                    GITHUB_EVENT_NAME="workflow_dispatch",GITHUB_REF="refs/heads/develop",FCA_PROBE_P12_PASSWORD="synthetic"), \
                 patch.object(sign,"decode_secret",side_effect=decode), patch.object(sign,"call",side_effect=call) as calls, \
                 patch.object(sign.subprocess,"run") as cleanup:
                with self.assertRaisesRegex(sign.SignError,"synthetic failure"):
                    sign.sign(app,Path(temp))
                cleanup.assert_called_once()
                self.assertEqual(cleanup.call_args.args[0][:2],["security","delete-keychain"])
                self.assertIn(("Set user Keychain search list","security","list-keychains","-d","user","-s","login.keychain"),
                              [item.args for item in calls.call_args_list])
            self.assertTrue(roots and all(not root.exists() for root in roots))

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
        for key, value in (("Name", "FCA Intent Probe Development"), ("TeamIdentifier", ["OTHER"]),
                           ("ProvisionsAllDevices", True), ("ProvisionedDevices", []),
                           ("DeveloperCertificates", []), ("Platform", ["macOS"]),
                           ("ExpirationDate", dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1))):
            with self.subTest(field=key), self.assertRaises(sign.SignError):
                sign.verify_profile(dict(profile, **{key:value}))
        for key in ("keychain-access-groups", "application-identifier", "com.apple.developer.team-identifier",
                    "com.apple.developer.applesignin", "get-task-allow"):
            invalid = dict(entitlements); del invalid[key]
            with self.subTest(missing=key), self.assertRaises(sign.SignError):
                sign.verify_profile(dict(profile, Entitlements=invalid))
        self.assertEqual(sign.SOURCE_BUNDLE, BUNDLE)
        self.assertEqual(sign.INSTALLED_BUNDLE, BUNDLE)
        self.assertEqual(BUNDLE, "com.familycaragent.app.dev")
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
        self.assertIn("remote-notification", info.get("UIBackgroundModes", []))
        workflow = (ios.parent / ".github/workflows/ios.yml").read_text()
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("inputs.build_signed_ipa == true", workflow)
        self.assertIn("secrets.FCA_IOS_DEV_CERT_P12_BASE64", workflow)
        self.assertIn("secrets.FCA_IOS_DEV_CERT_P12_PASSWORD", workflow)
        self.assertIn("github.ref == 'refs/heads/develop'", workflow)
        self.assertIn("--firebase-config", workflow)
        self.assertIn("if: always()", workflow)
        service = (source / "Push/NativePushService.swift").read_text(encoding="utf-8")
        self.assertNotIn("print(", service)
        self.assertNotIn("URLSession", service)
        self.assertIn("runtime.sessions.generation == identity.generation", service)


if __name__ == "__main__": unittest.main()
