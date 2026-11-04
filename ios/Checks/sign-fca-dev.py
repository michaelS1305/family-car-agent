#!/usr/bin/env python3
"""Sign an existing Xcode-built FCA Dev app on an ephemeral macOS Actions runner.

Input app is never modified. Private signing-tool output and secrets are not logged.
This script intentionally signs ONLY the existing XTL-prefixed FCA Dev identity.
"""

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

TEAM = "GT43M39TLK"
SOURCE_BUNDLE = "com.familycaragent.app.dev"
INSTALLED_BUNDLE = "XTL-255E706B.com.familycaragent.app.dev"
PROFILE_NAME = "XTL profile 8FC5U3CDL2"
IPA_NAME = "FCA-Dev-AppIntents-Development.ipa"
REPORT_NAME = "fca-dev-signing-report.json"


class SignError(Exception):
    """Safe diagnostic: never contains private subprocess output."""


def require(condition, message):
    if not condition:
        raise SignError(message)


def call(label, *args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise SignError(
            f"{label} failed (exit {result.returncode}); private tool output suppressed"
        )
    return result.stdout


def decode_secret(name, destination):
    value = os.environ.get(name, "")
    require(bool(value), f"Required signing secret missing: {name}")
    try:
        data = base64.b64decode("".join(value.split()), validate=True)
    except Exception:
        raise SignError(f"Invalid Base64 signing secret: {name}") from None

    require(bool(data), f"Decoded signing secret empty: {name}")
    destination.write_bytes(data)
    destination.chmod(0o600)


def signing_identity(keychain, certificates):
    output = call(
        "Signing identity lookup",
        "security", "find-identity",
        "-v", "-p", "codesigning",
        str(keychain),
    ).decode()

    candidates = re.findall(
        r"^\s*\d+\)\s+([0-9A-Fa-f]{40})(?=\s|$)",
        output,
        re.MULTILINE,
    )

    require(
        len(candidates) == len(set(candidates)),
        "Duplicate signing identity entries",
    )

    permitted = {
        hashlib.sha1(bytes(cert)).hexdigest().upper()
        for cert in certificates
    }

    matches = [
        value.upper()
        for value in candidates
        if value.upper() in permitted
    ]

    require(
        len(matches) == 1,
        "Expected exactly one signing certificate authorized by FCA Dev profile",
    )

    return matches[0]


def app_info(app):
    return plistlib.loads((app / "Info.plist").read_bytes())


def metadata_snapshot(app):
    folder = app / "Metadata.appintents"
    require(folder.is_dir(), "App Intents metadata directory missing")

    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file()
    )

    require(
        files and all(p.stat().st_size for p in files),
        "App Intents metadata missing or empty",
    )

    content = b"\n".join(p.read_bytes() for p in files)

    for action in (
        b"FCATakeVehicleIntent",
        b"FCAReturnVehicleIntent",
    ):
        require(
            action in content,
            "Expected TAKE/RETURN action missing from metadata",
        )

    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }


def signed_entitlements(app):
    return plistlib.loads(
        call(
            "Signed entitlements read",
            "codesign", "-d",
            "--entitlements", ":-",
            str(app),
        )
    )


def verify_profile(profile):
    require(
        profile.get("Name") == PROFILE_NAME,
        "Unexpected FCA Dev provisioning profile name",
    )

    require(
        profile.get("TeamIdentifier") == [TEAM],
        "Unexpected provisioning team",
    )

    expiration = profile.get("ExpirationDate")
    require(
        isinstance(expiration, dt.datetime),
        "Profile expiry missing",
    )

    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=dt.timezone.utc)

    require(
        expiration > dt.datetime.now(dt.timezone.utc),
        "Provisioning profile expired",
    )

    require(
        profile.get("Platform") and "iOS" in profile["Platform"],
        "Provisioning profile is not for iOS",
    )

    require(
        bool(profile.get("ProvisionedDevices")),
        "Development profile has no registered devices",
    )

    require(
        bool(profile.get("DeveloperCertificates")),
        "Development profile has no signing certificates",
    )

    entitlements = profile.get("Entitlements", {})

    require(
        entitlements.get("get-task-allow") is True,
        "Not a Development provisioning profile",
    )

    require(
        entitlements.get("application-identifier")
        == f"{TEAM}.{INSTALLED_BUNDLE}",
        "Provisioning App ID does not match installed FCA Dev",
    )

    require(
        entitlements.get("com.apple.developer.team-identifier") == TEAM,
        "Entitlement team does not match",
    )

    groups = entitlements.get("keychain-access-groups", [])

    require(
        isinstance(groups, list),
        "Provisioning keychain groups invalid",
    )

    require(
        f"{TEAM}.{INSTALLED_BUNDLE}" in groups,
        "Default installed FCA Dev Keychain access group not authorized",
    )

    return entitlements, expiration


def sign(input_app, evidence):
    require(
        sys.platform == "darwin",
        "FCA Dev signing requires macOS",
    )

    require(
        os.environ.get("GITHUB_REF") == "refs/heads/develop"
        and os.environ.get("GITHUB_EVENT_NAME")
        in ("push", "workflow_dispatch"),
        "Signing requires approved GitHub develop workflow",
    )

    require(
        input_app.is_dir()
        and (input_app / "Info.plist").is_file(),
        "Input .app not found",
    )

    require(
        evidence.is_dir(),
        "Evidence directory must exist",
    )

    require(
        not (evidence / IPA_NAME).exists()
        and not (evidence / REPORT_NAME).exists(),
        "Signing output already exists",
    )

    source_info = app_info(input_app)

    require(
        source_info.get("CFBundleIdentifier") == SOURCE_BUNDLE,
        "Xcode source Bundle ID mismatch",
    )

    require(
        source_info.get("FCAEnvironment") == "development",
        "Source is not FCA Dev",
    )

    require(
        not list(input_app.rglob("*.appex")),
        "Unexpected app extension: independent signing review required",
    )

    original_metadata = metadata_snapshot(input_app)

    with tempfile.TemporaryDirectory(prefix="fca-dev-sign-") as temporary:
        root = Path(temporary)

        cert_file = root / "certificate.p12"
        profile_file = root / "profile.mobileprovision"
        keychain = root / "fca-dev.keychain-db"
        key_password = secrets.token_urlsafe(32)

        decode_secret("FCA_PROBE_P12_BASE64", cert_file)
        decode_secret("FCA_DEV_PROFILE_BASE64", profile_file)

        cert_password = os.environ.get("FCA_PROBE_P12_PASSWORD", "")

        require(
            bool(cert_password),
            "P12 password missing",
        )

        profile = plistlib.loads(
            call(
                "Profile decoding",
                "security", "cms", "-D", "-i",
                str(profile_file),
            )
        )

        entitlements, expiration = verify_profile(profile)

        entitlement_file = root / "entitlements.plist"
        entitlement_file.write_bytes(plistlib.dumps(entitlements))

        payload = root / "Payload"
        payload.mkdir()

        signed = payload / "FamilyCarAgent.app"
        shutil.copytree(input_app, signed, symlinks=True)

        signed_info = dict(source_info)
        signed_info["CFBundleIdentifier"] = INSTALLED_BUNDLE

        (signed / "Info.plist").write_bytes(
            plistlib.dumps(signed_info)
        )

        shutil.copyfile(
            profile_file,
            signed / "embedded.mobileprovision",
        )

        require(
            metadata_snapshot(signed) == original_metadata,
            "App Intents metadata changed before signing",
        )

        try:
            call(
                "Temporary Keychain creation",
                "security", "create-keychain",
                "-p", key_password,
                str(keychain),
            )

            call(
                "Temporary Keychain settings",
                "security", "set-keychain-settings",
                "-lut", "21600",
                str(keychain),
            )

            call(
                "Temporary Keychain unlock",
                "security", "unlock-keychain",
                "-p", key_password,
                str(keychain),
            )

            call(
                "Certificate import",
                "security", "import",
                str(cert_file),
                "-k", str(keychain),
                "-P", cert_password,
                "-T", "/usr/bin/codesign",
            )

            call(
                "Code-signing key access",
                "security", "set-key-partition-list",
                "-S", "apple-tool:,apple:",
                "-s",
                "-k", key_password,
                str(keychain),
            )

            identity = signing_identity(
                keychain,
                profile["DeveloperCertificates"],
            )

            nested = sorted(
                (
                    p for p in signed.rglob("*")
                    if p.suffix in (".framework", ".dylib")
                ),
                key=lambda p: len(p.parts),
                reverse=True,
            )

            for item in nested:
                call(
                    "Nested code signing",
                    "codesign",
                    "--force",
                    "--sign", identity,
                    "--keychain", str(keychain),
                    "--timestamp=none",
                    str(item),
                )

            call(
                "Application signing",
                "codesign",
                "--force",
                "--sign", identity,
                "--keychain", str(keychain),
                "--timestamp=none",
                "--entitlements", str(entitlement_file),
                str(signed),
            )

            call(
                "Application signature verification",
                "codesign",
                "--verify",
                "--deep",
                "--strict",
                str(signed),
            )

            certificate_requirement = (
                '=certificate leaf = H"' + identity + '"'
            )

            call(
                "Signer certificate verification",
                "codesign",
                "--verify",
                "--strict",
                "-R", certificate_requirement,
                str(signed),
            )

            require(
                signed_entitlements(signed) == entitlements,
                "Signed entitlements do not match validated profile",
            )

            require(
                (signed / "embedded.mobileprovision").read_bytes()
                == profile_file.read_bytes(),
                "Embedded provisioning profile mismatch",
            )

            require(
                app_info(signed).get("CFBundleIdentifier")
                == INSTALLED_BUNDLE,
                "Signed bundle identity changed",
            )

            require(
                metadata_snapshot(signed) == original_metadata,
                "App Intents metadata changed after signing",
            )

            ipa = evidence / IPA_NAME

            call(
                "IPA packaging",
                "ditto",
                "-c", "-k",
                "--keepParent",
                str(payload),
                str(ipa),
            )

            extraction = root / "verified-ipa"

            call(
                "IPA extraction",
                "ditto",
                "-x", "-k",
                str(ipa),
                str(extraction),
            )

            packaged = (
                extraction / "Payload" / "FamilyCarAgent.app"
            )

            require(
                packaged.is_dir(),
                "Packaged FCA Dev app missing",
            )

            call(
                "Packaged signature verification",
                "codesign",
                "--verify",
                "--deep",
                "--strict",
                str(packaged),
            )

            require(
                app_info(packaged).get("CFBundleIdentifier")
                == INSTALLED_BUNDLE,
                "IPA Bundle ID mismatch",
            )

            require(
                signed_entitlements(packaged) == entitlements,
                "Packaged entitlements mismatch",
            )

            require(
                (packaged / "embedded.mobileprovision").read_bytes()
                == profile_file.read_bytes(),
                "Packaged provisioning mismatch",
            )

            require(
                metadata_snapshot(packaged) == original_metadata,
                "IPA lost App Intents metadata",
            )

            report = {
                "bundle_id": INSTALLED_BUNDLE,
                "environment": "development",
                "profile_name": PROFILE_NAME,
                "profile_expires": expiration.isoformat(),
                "development_signature_verified": True,
                "signing_certificate_authorized_by_profile": True,
                "embedded_profile_verified": True,
                "entitlements_match_profile": True,
                "app_intents_metadata_preserved": True,
                "ipa_roundtrip_verified": True,
                "ipa_sha256": hashlib.sha256(
                    ipa.read_bytes()
                ).hexdigest(),
                "device_installation_verified": False,
                "existing_keychain_session_preservation_verified": False,
            }

            (evidence / REPORT_NAME).write_text(
                json.dumps(report, indent=2) + "\n"
            )

        finally:
            subprocess.run(
                ["security", "delete-keychain", str(keychain)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()

    try:
        sign(args.app, args.evidence)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, SignError)
            else "FCA Dev signing failed; private diagnostic details suppressed"
        )

        print(message, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()