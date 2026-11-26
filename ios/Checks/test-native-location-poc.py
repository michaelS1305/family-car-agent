"""Local configuration/adapter contracts; not a replacement for Xcode/device validation."""
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "Sources/FamilyCarAgent/OfflineEvents/NativeLocationPOCCore.swift"
ADAPTER = CORE.with_name("NativeLocationPOC.swift")
spec = importlib.util.spec_from_file_location("wrapper", Path(__file__).with_name("app-intents-poc.py"))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)

class POCPolicy(unittest.TestCase):
    def test_signing_exception_fails_closed(self):
        spec = importlib.util.spec_from_file_location("poc_sign", ROOT / "Checks/sign-fca-dev.py")
        sign = importlib.util.module_from_spec(spec); spec.loader.exec_module(sign)
        for event in ("workflow_dispatch", "push", "pull_request", "pull_request_target", "schedule"):
            for ref in ("refs/heads/codex/native-offline-location-poc", "refs/heads/codex/other", "refs/heads/main"):
                for repo in ("michaelS1305/family-car-agent", "fork/family-car-agent", ""):
                    with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GITHUB_REPOSITORY": repo}, clear=True):
                        expected = event == "workflow_dispatch" and ref == "refs/heads/codex/native-offline-location-poc" and repo == "michaelS1305/family-car-agent"
                        if expected: sign.authorize_signing()
                        else:
                            with self.assertRaises(sign.SignError): sign.authorize_signing()
                        with self.assertRaises(sign.SignError): sign.authorize_signing(production=True)
        for event in ("push", "workflow_dispatch"):
            with patch.dict(os.environ, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": "refs/heads/develop"}, clear=True):
                sign.authorize_signing()

    def test_delegate_isolation_bridge(self):
        text = ADAPTER.read_text(encoding="utf-8")
        self.assertEqual(text.count("@preconcurrency CLLocationManagerDelegate"), 2)
        self.assertIn("@MainActor final class NativeLocationPOCAcquisition", text)
        self.assertIn("@MainActor private final class NativeLocationPOCPermission", text)
        self.assertNotIn("nonisolated(unsafe)", text)

    def test_development_configuration(self):
        info = plistlib.loads((ROOT / "Config/Info.Dev.plist").read_bytes())
        self.assertTrue(info["NSLocationWhenInUseUsageDescription"])
        self.assertEqual(info["UIBackgroundModes"], ["remote-notification", "location"])
        self.assertFalse(any("Always" in key for key in info))

    def test_actual_production_wrapper_excludes_location_configuration(self):
        config = {"BUNDLE_ID": "com.familycaragent.app", "PROJECT_ID": "family-car-agent",
                  "GCM_SENDER_ID": "249909620080", "GOOGLE_APP_ID": "1:249909620080:ios:12c8182ee0db3d93ee33b5"}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"FCA_IOS_PROD_SUPABASE_PUBLISHABLE_KEY": "sb_publishable_synthetic"}):
            base = Path(temp); firebase = base / "GoogleService-Info.plist"
            firebase.write_bytes(plistlib.dumps(config))
            wrapper.generate(ROOT, base / "wrapper", firebase_config=firebase, production=True)
            info = plistlib.loads((base / "wrapper/Production-Info.plist").read_bytes())
            self.assertFalse(any(key.startswith("NSLocation") for key in info))
            self.assertEqual(info["UIBackgroundModes"], ["remote-notification"])
            project = plistlib.loads((base / "wrapper/FCAIntentPoC.xcodeproj/project.pbxproj").read_bytes())
            settings = [v["buildSettings"] for v in project["objects"].values() if v["isa"] == "XCBuildConfiguration" and v["buildSettings"]]
            self.assertEqual(settings[0]["SWIFT_ACTIVE_COMPILATION_CONDITIONS"], "FCA_PRODUCTION")

    def test_compile_guards_and_ui_guard(self):
        for path in [CORE, ADAPTER]:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#if DEBUG && !FCA_PRODUCTION"))
            self.assertTrue(text.rstrip().endswith("#endif"))
        ui = (ROOT / "Sources/FamilyCarAgent/Vehicles/VehicleConnectionSetupView.swift").read_text(encoding="utf-8")
        self.assertIn("#if DEBUG && !FCA_PRODUCTION\n                    NativeLocationPOCPermissionView()\n                    #endif", ui)

    def test_no_mutation_or_network_dependencies(self):
        text = ADAPTER.read_text(encoding="utf-8") + CORE.read_text(encoding="utf-8")
        for forbidden in ["VehicleEventQueue", "VehicleSessionRuntime", "URLSession", "CLGeocoder", "Keychain", "recordShortcut", "requestAlwaysAuthorization", "requestTemporaryFullAccuracy"]:
            self.assertNotIn(forbidden, text)

    def test_permission_action_does_not_warm_location(self):
        text = ADAPTER.read_text(encoding="utf-8").split("private final class NativeLocationPOCPermission", 1)[1].split("struct NativeLocationPOCPermissionView", 1)[0]
        self.assertIn("requestWhenInUseAuthorization()", text)
        self.assertIn("applicationState == .active", text)
        for forbidden in ["startUpdatingLocation", "requestLocation()", "manager.location"]:
            self.assertNotIn(forbidden, text)

    def test_intent_and_native_policy(self):
        text = ADAPTER.read_text(encoding="utf-8")
        intent = text.split("struct FCANativeLocationPOCIntent", 1)[1]
        self.assertIn("openAppWhenRun = false", intent)
        self.assertNotIn("@Parameter", intent)
        self.assertNotIn("static var authenticationPolicy", intent)
        self.assertIn("await acquisition.acquire()", intent)
        self.assertIn("Date().timeIntervalSince(fix.timestamp)", text)
        self.assertIn("ContinuousClock()", text)
        self.assertIn("clock.sleep(until:", text)
        self.assertIn("requiresSource: false", CORE.read_text())
        self.assertIn("manager.stopUpdatingLocation()", text)
        self.assertIn("manager.delegate = nil", text)
        self.assertIn("timer?.cancel()", text)
        self.assertNotIn("requestWhenInUseAuthorization", text.split("private final class NativeLocationPOCPermission", 1)[0])

    def test_no_sensitive_log_interpolation(self):
        text = ADAPTER.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "emit(" in line or "logger.notice" in line:
                for forbidden in ["coordinate", "latitude", "longitude", "description", "token", "timestamp", "vehicle.id"]:
                    self.assertNotIn(forbidden, line)

if __name__ == "__main__": unittest.main()
