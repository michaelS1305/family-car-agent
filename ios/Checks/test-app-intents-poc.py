
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
import struct

spec = importlib.util.spec_from_file_location(
    "poc", Path(__file__).with_name("app-intents-poc.py")
)
poc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poc)

class MetadataPoCTests(unittest.TestCase):
    def firebase_fixture(self, directory):
        from firebase_dev_config import BUNDLE, PROJECT, SENDER
        path = Path(directory) / "GoogleService-Info.plist"
        path.write_bytes(plistlib.dumps({"BUNDLE_ID": BUNDLE, "PROJECT_ID": PROJECT,
                                        "GCM_SENDER_ID": SENDER, "GOOGLE_APP_ID": f"1:{SENDER}:ios:abcdef"}))
        return path

    def test_wrapper_references_real_sources_and_resources(self):
        ios = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "wrapper"
            poc.generate(ios, output, firebase_config=self.firebase_fixture(temp))

            with (
                output / "FCAIntentPoC.xcodeproj/project.pbxproj"
            ).open("rb") as f:
                objects = plistlib.load(f)["objects"].values()

            settings = next(
                o["buildSettings"]
                for o in objects
                if o.get("buildSettings", {}).get("SDKROOT")
            )

            self.assertEqual(
                settings["SWIFT_ACTIVE_COMPILATION_CONDITIONS"],
                "DEBUG",
            )
            self.assertEqual(settings["CODE_SIGNING_ALLOWED"], "NO")
            self.assertEqual(settings["SDKROOT"], "iphoneos")
            self.assertEqual(settings["ENABLE_APP_INTENTS_METADATA_EXTRACTION"], "YES")
            self.assertEqual(settings["ASSETCATALOG_COMPILER_APPICON_NAME"], "AppIcon")
            catalog = next(o for o in objects if o.get("lastKnownFileType") == "folder.assetcatalog")
            self.assertEqual(catalog["path"], str(ios / "Config/AppIcon.xcassets"))
            resources_phase = next(o for o in objects if o["isa"] == "PBXResourcesBuildPhase")
            objects_by_id = plistlib.loads((output / "FCAIntentPoC.xcodeproj/project.pbxproj").read_bytes())["objects"]
            self.assertTrue(any(objects_by_id[objects_by_id[b]["fileRef"]].get("path") == catalog["path"]
                                for b in resources_phase["files"]))

            self.assertTrue(any(o.get("productName") == "FirebaseMessaging" for o in objects))
            self.assertTrue(any(o.get("requirement", {}).get("version") == "12.19.3" for o in objects))
            paths = [o.get("path", "") for o in objects]
            self.assertIn(str(Path(temp) / "GoogleService-Info.plist"), paths)
            self.assertTrue(
                {str(p) for p in (ios / "Sources/FamilyCarAgent").rglob("*.swift")}
                .issubset(set(paths))
            )

            self.assertIn(
                str(ios / "Sources/FamilyCarAgent/FamilyCarAgentApp.swift"),
                paths,
            )
            self.assertIn(
                str(ios / "Sources/FamilyCarAgent/FCAConnectionTestIntent.swift"),
                paths,
            )
            self.assertEqual(
                sum(o.get("lastKnownFileType") == "folder" for o in objects),
                2,
            )

            with self.assertRaises(FileExistsError):
                poc.generate(ios, output, firebase_config=self.firebase_fixture(temp))

    def test_dev_target_generates_launch_screen(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "wrapper"
            poc.generate(Path(__file__).resolve().parents[1], output, firebase_config=self.firebase_fixture(temp))
            objects = plistlib.loads(
                (output / "FCAIntentPoC.xcodeproj/project.pbxproj").read_bytes()
            )["objects"]
            target = next(o for o in objects.values() if o["isa"] == "PBXNativeTarget")
            configs = objects[target["buildConfigurationList"]]["buildConfigurations"]
            for config in configs:
                settings = objects[config]["buildSettings"]
                self.assertEqual(settings["PRODUCT_BUNDLE_IDENTIFIER"], "com.familycaragent.app.dev")
                self.assertEqual(settings["GENERATE_INFOPLIST_FILE"], "YES")
                self.assertEqual(settings["INFOPLIST_KEY_UILaunchScreen_Generation"], "YES")

    def test_metadata_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "FCA.app"
            app.mkdir()
            self.firebase_fixture(app)
            report = Path(temp) / "report.json"

            info = {
                "CFBundleIdentifier": "com.familycaragent.app.dev",
                "FCAEnvironment": "development",
                "UILaunchScreen": {},
                "CFBundleIcons": {"CFBundlePrimaryIcon": {
                    "CFBundleIconName": "AppIcon", "CFBundleIconFiles": ["AppIcon60x60"]}},
            }
            (app / "Assets.car").write_bytes(b"synthetic compiled catalog")
            (app / "AppIcon60x60@2x.png").write_bytes(b"synthetic compiled icon")

            (app / "Info.plist").write_bytes(plistlib.dumps(info))

            with self.assertRaises(ValueError):
                poc.verify(app, report)

            metadata = app / "Metadata.appintents"
            metadata.mkdir()
            data = metadata / "extract.actionsdata"

            for content in (
                b"",
                b'{"intent":"OtherIntent"}',
            ):
                data.write_bytes(content)

                with self.assertRaises(ValueError):
                    poc.verify(app, report)

            data.write_bytes(
                b'{"intent":"FCAConnectionTestIntent"}'
            )

            with self.assertRaises(ValueError):
                poc.verify(app, report)
            data.write_bytes(b'["FCAConnectionTestIntent","FCATakeVehicleIntent"]')
            with self.assertRaises(ValueError):
                poc.verify(app, report)
            data.write_bytes(b'["FCAConnectionTestIntent","FCATakeVehicleIntent","FCAReturnVehicleIntent"]')
            poc.verify(app, report)

            for missing in ("Assets.car", "AppIcon60x60@2x.png"):
                path = app / missing
                content = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, "compiled AppIcon"):
                    poc.verify(app, report)
                path.write_bytes(content)
            without_icon = dict(info)
            del without_icon["CFBundleIcons"]
            (app / "Info.plist").write_bytes(plistlib.dumps(without_icon))
            with self.assertRaisesRegex(ValueError, "compiled AppIcon"):
                poc.verify(app, report)
            (app / "Info.plist").write_bytes(plistlib.dumps(info))

            # Synthetic processed plist: missing/wrong types must fail even with valid metadata.
            for launch_screen in (None, "", []):
                invalid_info = dict(info)
                if launch_screen is None:
                    del invalid_info["UILaunchScreen"]
                else:
                    invalid_info["UILaunchScreen"] = launch_screen
                (app / "Info.plist").write_bytes(plistlib.dumps(invalid_info))
                with self.assertRaisesRegex(ValueError, "UILaunchScreen dictionary"):
                    poc.verify(app, report)
            (app / "Info.plist").write_bytes(plistlib.dumps(info))
            poc.verify(app, report)

            self.assertFalse(
                json.loads(report.read_text())["device_discovery_verified"]
            )

            info["CFBundleIdentifier"] = "wrong.app"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))

            with self.assertRaises(ValueError):
                poc.verify(app, report)

    def test_app_icon_source_is_square_opaque_srgb(self):
        catalog = Path(__file__).resolve().parents[1] / "Config/AppIcon.xcassets/AppIcon.appiconset"
        contents = json.loads((catalog / "Contents.json").read_text())
        self.assertEqual(contents["images"], [{"filename": "AppIcon.png", "idiom": "universal",
                                             "platform": "ios", "size": "1024x1024"}])
        png = (catalog / "AppIcon.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">IIBB", png[16:26]), (1024, 1024, 8, 2))
        chunks = {}
        offset = 8
        while offset < len(png):
            size = struct.unpack(">I", png[offset:offset + 4])[0]
            chunks[png[offset + 4:offset + 8]] = png[offset + 8:offset + 8 + size]
            offset += size + 12
        self.assertNotIn(b"tRNS", chunks)
        self.assertEqual(chunks[b"sRGB"], b"\x00")


if __name__ == "__main__":
    unittest.main()
