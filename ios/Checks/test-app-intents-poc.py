import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("poc", Path(__file__).with_name("app-intents-poc.py"))
poc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poc)


class MetadataPoCTests(unittest.TestCase):
    def test_wrapper_references_real_sources_and_resources(self):
        ios = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "wrapper"
            poc.generate(ios, output)
            with (output / "FCAIntentPoC.xcodeproj/project.pbxproj").open("rb") as f:
                objects = plistlib.load(f)["objects"].values()
            settings = next(o["buildSettings"] for o in objects if o.get("buildSettings", {}).get("SDKROOT"))
            self.assertEqual(settings["SWIFT_ACTIVE_COMPILATION_CONDITIONS"], "DEBUG")
            self.assertEqual(settings["CODE_SIGNING_ALLOWED"], "NO")
            self.assertEqual(settings["SDKROOT"], "iphoneos")
            paths = [o.get("path", "") for o in objects]
            self.assertIn(str(ios / "Sources/FamilyCarAgent/FamilyCarAgentApp.swift"), paths)
            self.assertIn(str(ios / "Sources/FamilyCarAgent/FCAConnectionTestIntent.swift"), paths)
            self.assertEqual(sum(o.get("lastKnownFileType") == "folder" for o in objects), 2)
            with self.assertRaises(FileExistsError):
                poc.generate(ios, output)

    def test_metadata_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "FCA.app"
            app.mkdir()
            report = Path(temp) / "report.json"
            info = {"CFBundleIdentifier": "com.familycaragent.app.dev", "FCAEnvironment": "development"}
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):
                poc.verify(app, report)
            metadata = app / "Metadata.appintents"
            metadata.mkdir()
            data = metadata / "extract.actionsdata"
            for content in (b"", b'{"intent":"OtherIntent"}'):
                data.write_bytes(content)
                with self.assertRaises(ValueError):
                    poc.verify(app, report)
            data.write_bytes(b'{"intent":"FCAConnectionTestIntent"}')
            poc.verify(app, report)
            self.assertFalse(json.loads(report.read_text())["device_discovery_verified"])
            info["CFBundleIdentifier"] = "wrong.app"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):
                poc.verify(app, report)


if __name__ == "__main__":
    unittest.main()
