
import importlib.util
import json
import hashlib
from pathlib import Path
import plistlib
import tempfile
import unittest
import datetime
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "poc", Path(__file__).with_name("app-intents-poc.py")
)
poc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poc)

sign_spec = importlib.util.spec_from_file_location(
    "sign_probe", Path(__file__).with_name("sign-intent-probe.py")
)
sign_probe = importlib.util.module_from_spec(sign_spec)
sign_spec.loader.exec_module(sign_probe)


class MetadataPoCTests(unittest.TestCase):
    def test_signing_identity_matches_profile_regardless_of_name(self):
        certificate = b"SYNTHETIC_CERTIFICATE"
        fingerprint = hashlib.sha1(certificate).hexdigest().upper()

        for name in (
            "Apple Development: Example Developer",
            "Apple Development: Example Developer (GT43M39TLK)",
            "Completely Different Certificate Name",
        ):
            row = f'  1) {fingerprint} "{name}"\n'

            with self.subTest(name=name), \
                 patch.object(
                     sign_probe,
                     "command",
                     return_value=row.encode(),
                 ) as mocked:
                result = sign_probe.signing_identity(
                    Path("temporary.keychain"),
                    [certificate],
                )

                self.assertEqual(result, fingerprint)
                mocked.assert_called_once_with(
                    "Signing identity lookup",
                    "security",
                    "find-identity",
                    "-v",
                    "-p",
                    "codesigning",
                    "temporary.keychain",
                )

    def test_signing_identity_rejects_wrong_certificate(self):
        certificate = b"AUTHORIZED_CERTIFICATE"
        different = b"UNAUTHORIZED_CERTIFICATE"
        wrong_hash = hashlib.sha1(different).hexdigest().upper()
        row = f'1) {wrong_hash} "PRIVATE_CERTIFICATE_NAME"\n'

        with patch.object(sign_probe, "command", return_value=row.encode()):
            with self.assertRaisesRegex(
                sign_probe.ProbeError,
                "Expected exactly one valid identity authorized by the profile",
            ) as caught:
                sign_probe.signing_identity(
                    Path("temporary.keychain"),
                    [certificate],
                )

        self.assertNotIn(wrong_hash, str(caught.exception))
        self.assertNotIn("PRIVATE_CERTIFICATE_NAME", str(caught.exception))

    def test_signing_identity_rejects_multiple_matches(self):
        cert_a = b"CERTIFICATE_A"
        cert_b = b"CERTIFICATE_B"
        hash_a = hashlib.sha1(cert_a).hexdigest().upper()
        hash_b = hashlib.sha1(cert_b).hexdigest().upper()

        output = (
            f'1) {hash_a} "First Certificate"\n'
            f'2) {hash_b} "Second Certificate"\n'
        )

        with patch.object(sign_probe, "command", return_value=output.encode()):
            with self.assertRaisesRegex(
                sign_probe.ProbeError,
                "Expected exactly one valid identity authorized by the profile",
            ):
                sign_probe.signing_identity(
                    Path("temporary.keychain"),
                    [cert_a, cert_b],
                )

    def test_signing_identity_rejects_duplicate_entries(self):
        certificate = b"SYNTHETIC_CERTIFICATE"
        fingerprint = hashlib.sha1(certificate).hexdigest().upper()
        row = f'1) {fingerprint} "Certificate"\n'

        with patch.object(
            sign_probe,
            "command",
            return_value=(row + row).encode(),
        ):
            with self.assertRaisesRegex(
                sign_probe.ProbeError,
                "Duplicate code-signing identity entries",
            ):
                sign_probe.signing_identity(
                    Path("temporary.keychain"),
                    [certificate],
                )

    def test_signing_identity_rejects_missing_or_malformed_output(self):
        certificate = b"SYNTHETIC_CERTIFICATE"

        for output in (
            "0 valid identities found",
            "PRIVATE_UNKNOWN",
            '1) INVALID_HASH "Private Certificate"',
        ):
            with self.subTest(output=output), \
                 patch.object(
                     sign_probe,
                     "command",
                     return_value=output.encode(),
                 ):
                with self.assertRaisesRegex(
                    sign_probe.ProbeError,
                    "No valid code-signing identity found",
                ) as caught:
                    sign_probe.signing_identity(
                        Path("temporary.keychain"),
                        [certificate],
                    )

                self.assertNotIn("PRIVATE", str(caught.exception))

    def test_probe_wrapper_is_standalone_and_debug(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "wrapper"
            poc.generate(
                Path(__file__).resolve().parents[1],
                output,
                probe=True,
            )

            objects = plistlib.loads(
                (output / "FCAIntentPoC.xcodeproj/project.pbxproj").read_bytes()
            )["objects"].values()

            settings = next(
                o["buildSettings"]
                for o in objects
                if o.get("buildSettings", {}).get("SDKROOT")
            )

            self.assertEqual(settings["PRODUCT_BUNDLE_IDENTIFIER"], poc.PROBE_ID)
            self.assertEqual(settings["SWIFT_ACTIVE_COMPILATION_CONDITIONS"], "DEBUG")
            self.assertEqual(
                plistlib.loads(Path(settings["CODE_SIGN_ENTITLEMENTS"]).read_bytes()),
                {},
            )

            info = plistlib.loads(Path(settings["INFOPLIST_FILE"]).read_bytes())
            self.assertEqual(info["CFBundleDisplayName"], "FCA Intent Probe")
            self.assertNotIn("CFBundleURLTypes", info)

            swift_names = {
                Path(o["path"]).name
                for o in objects
                if o.get("lastKnownFileType") == "sourcecode.swift"
            }

            self.assertEqual(
                swift_names,
                {
                    "FCAConnectionTestIntent.swift",
                    "ProbeApp.swift",
                    "OfflineUpload.swift",
                    "OfflineUploadCore.swift",
                    "PackageResourceAccessor.swift",
                },
            )

            metadata = output / "Metadata.appintents"
            metadata.mkdir()
            (metadata / "extract.actionsdata").write_text(
                '{"intents":["FCAConnectionTestIntent","FCATestOfflineUploadIntent"]}'
            )

            info["CFBundleIdentifier"] = poc.PROBE_ID
            (output / "Info.plist").write_bytes(plistlib.dumps(info))

            poc.verify(output, output / "report.json", probe=True)

            (metadata / "extract.actionsdata").write_text('{"intent":"FCAConnectionTestIntent"}')
            with self.assertRaises(ValueError):
                poc.verify(output, output / "report.json", probe=True)

            with self.assertRaises(ValueError):
                poc.verify(output, output / "report.json")

    def test_development_profile_is_exact_and_unexpired(self):
        now = datetime.datetime.now(datetime.timezone.utc)

        profile = {
            "Name": sign_probe.PROFILE_NAME,
            "TeamIdentifier": [sign_probe.TEAM],
            "ExpirationDate": now + datetime.timedelta(days=1),
            "Platform": ["iOS"],
            "ProvisionedDevices": ["SYNTHETIC_DEVICE"],
            "ApplicationIdentifierPrefix": [sign_probe.TEAM],
            "DeveloperCertificates": [b"SYNTHETIC_CERTIFICATE"],
            "Entitlements": {
                "application-identifier": sign_probe.TEAM + "." + sign_probe.BUNDLE,
                "com.apple.developer.team-identifier": sign_probe.TEAM,
                "get-task-allow": True,
            },
        }

        self.assertEqual(
            sign_probe.validate_profile(profile, now),
            profile["Entitlements"],
        )

        multi_platform = dict(
            profile,
            Platform=["iOS", "xrOS", "visionOS"],
        )
        self.assertEqual(
            sign_probe.validate_profile(multi_platform, now),
            profile["Entitlements"],
        )

        for key, value in (
            ("Name", "Other"),
            ("TeamIdentifier", ["OTHER"]),
            ("ExpirationDate", now - datetime.timedelta(days=1)),
            ("ProvisionedDevices", []),
            ("ProvisionsAllDevices", True),
            ("DeveloperCertificates", []),
            ("Platform", ["macOS"]),
        ):
            with self.subTest(key=key), \
                 self.assertRaises(sign_probe.ProbeError):
                sign_probe.validate_profile(
                    dict(profile, **{key: value}),
                    now,
                )

        for key, value in (
            ("application-identifier", sign_probe.TEAM + ".*"),
            (
                "application-identifier",
                sign_probe.TEAM + ".com.familycaragent.app.dev",
            ),
            ("get-task-allow", False),
            ("com.apple.developer.team-identifier", "OTHER"),
        ):
            modified = dict(
                profile,
                Entitlements=dict(
                    profile["Entitlements"],
                    **{key: value},
                ),
            )

            with self.subTest(key=key, value=value), \
                 self.assertRaises(sign_probe.ProbeError):
                sign_probe.validate_profile(modified, now)

    def test_private_tool_output_is_suppressed(self):
        with patch.object(sign_probe.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b"PRIVATE_SENTINEL"

            with self.assertRaises(sign_probe.ProbeError) as caught:
                sign_probe.command(
                    "Import",
                    "security",
                    "PRIVATE_SENTINEL",
                )

            self.assertNotIn("PRIVATE_SENTINEL", str(caught.exception))

    def test_failure_cleans_up_signing_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "signing"

            with patch.object(sign_probe, "workspace", return_value=work), \
                 patch.object(sign_probe.sys, "platform", "darwin"), \
                 patch.dict(
                     sign_probe.os.environ,
                     {
                         "GITHUB_EVENT_NAME": "workflow_dispatch",
                         "GITHUB_REF": "refs/heads/develop",
                         "FCA_PROBE_P12_BASE64": "",
                     },
                 ):
                with self.assertRaises(sign_probe.ProbeError):
                    sign_probe.sign(Path(temp), Path(temp))

                self.assertFalse(work.exists())

    def test_signing_rejects_unauthorized_events(self):
        for event, ref in (
            ("pull_request", "refs/heads/develop"),
            ("workflow_dispatch", "refs/heads/main"),
            ("push", "refs/heads/main"),
            ("schedule", "refs/heads/develop"),
        ):
            with self.subTest(event=event, ref=ref), \
                 patch.object(sign_probe.sys, "platform", "darwin"), \
                 patch.dict(
                     sign_probe.os.environ,
                     {
                         "GITHUB_EVENT_NAME": event,
                         "GITHUB_REF": ref,
                     },
                 ):
                with self.assertRaisesRegex(
                    sign_probe.ProbeError,
                    "Signing requires an authorized event on develop",
                ):
                    sign_probe.sign(
                        Path("unused"),
                        Path("unused"),
                    )

    def test_develop_push_is_authorized(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "signing"

            with patch.object(sign_probe, "workspace", return_value=work), \
                 patch.object(sign_probe.sys, "platform", "darwin"), \
                 patch.dict(
                     sign_probe.os.environ,
                     {
                         "GITHUB_EVENT_NAME": "push",
                         "GITHUB_REF": "refs/heads/develop",
                         "FCA_PROBE_P12_BASE64": "",
                     },
                 ):
                with self.assertRaisesRegex(
                    sign_probe.ProbeError,
                    "Required signing secret is missing",
                ):
                    sign_probe.sign(Path(temp), Path(temp))

                self.assertFalse(work.exists())

    def test_wrapper_references_real_sources_and_resources(self):
        ios = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "wrapper"
            poc.generate(ios, output)

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

            paths = [o.get("path", "") for o in objects]

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
                poc.generate(ios, output)

    def test_metadata_and_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / "FCA.app"
            app.mkdir()
            report = Path(temp) / "report.json"

            info = {
                "CFBundleIdentifier": "com.familycaragent.app.dev",
                "FCAEnvironment": "development",
            }

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

            poc.verify(app, report)

            self.assertFalse(
                json.loads(report.read_text())["device_discovery_verified"]
            )

            info["CFBundleIdentifier"] = "wrong.app"
            (app / "Info.plist").write_bytes(plistlib.dumps(info))

            with self.assertRaises(ValueError):
                poc.verify(app, report)


if __name__ == "__main__":
    unittest.main()
