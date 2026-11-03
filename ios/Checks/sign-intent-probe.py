
"""Development probe signing on a disposable macOS runner. Never echo tool output."""

import argparse
import base64
import datetime
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

TEAM = "GT43M39TLK"
BUNDLE = "com.familycaragent.intentprobe"
PROFILE_NAME = "FCA Intent Probe Development"


class ProbeError(Exception):
    """A fixed, safe-to-print diagnostic."""


def require(condition, message):
    if not condition:
        raise ProbeError(message)


def command(label, *args):
    result = subprocess.run(args, capture_output=True)
    if result.returncode:
        raise ProbeError(
            f"{label} failed (exit {result.returncode}); "
            "private tool output suppressed"
        )
    return result.stdout


def signing_identity(keychain, certificates):
    """
    Select exactly one valid code-signing identity authorized
    by the provisioning profile, without relying on its display name.
    """
    output = command(
        "Signing identity lookup",
        "security", "find-identity",
        "-v", "-p", "codesigning",
        str(keychain),
    ).decode()

    # Extract SHA-1 fingerprints from numbered identity rows.
    # Certificate display names are intentionally ignored.
    row_pattern = r'^\s*\d+\)\s+([0-9A-Fa-f]{40})(?=\s|$)'

    valid_hashes = [
        value.upper()
        for value in re.findall(
            row_pattern,
            output,
            re.MULTILINE,
        )
    ]

    require(
        len(valid_hashes) == len(set(valid_hashes)),
        "Duplicate code-signing identity entries",
    )

    require(
        len(valid_hashes) > 0,
        "No valid code-signing identity found",
    )

    authorized_hashes = {
        hashlib.sha1(bytes(cert)).hexdigest().upper()
        for cert in certificates
    }

    matches = [
        value
        for value in valid_hashes
        if value in authorized_hashes
    ]

    require(
        len(matches) == 1,
        "Expected exactly one valid identity authorized by the profile",
    )

    return matches[0]


def validate_profile(profile, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)

    require(
        profile.get("Name") == PROFILE_NAME,
        "Unexpected profile name",
    )

    require(
        profile.get("TeamIdentifier") == [TEAM],
        "Unexpected profile team",
    )

    expiry = profile.get("ExpirationDate")

    require(
        isinstance(expiry, datetime.datetime),
        "Missing profile expiry",
    )

    require(
        expiry.replace(tzinfo=datetime.timezone.utc) > now,
        "Profile expired",
    )

    require(
        "iOS" in profile.get("Platform", []),
        "Expected an iOS-compatible profile",
    )

    require(
        len(profile.get("ProvisionedDevices", [])) == 1,
        "Expected one registered device",
    )

    require(
        not profile.get("ProvisionsAllDevices"),
        "Enterprise profile is not allowed",
    )

    allowed = profile.get("Entitlements", {})

    require(
        allowed.get("get-task-allow") is True,
        "Expected a development profile",
    )

    require(
        allowed.get("com.apple.developer.team-identifier") == TEAM,
        "Entitlement team mismatch",
    )

    prefixes = profile.get("ApplicationIdentifierPrefix", [])
    app_id = allowed.get("application-identifier")

    require(
        len(prefixes) == 1
        and app_id == prefixes[0] + "." + BUNDLE,
        "Profile must authorize the exact probe application identifier",
    )

    require(
        profile.get("DeveloperCertificates"),
        "Profile has no signing certificates",
    )

    return {
        "application-identifier": app_id,
        "com.apple.developer.team-identifier": TEAM,
        "get-task-allow": True,
    }


def workspace():
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    return root / "fca-probe-signing"


def cleanup():
    work = workspace()
    keychain = work / "probe.keychain-db"

    try:
        if keychain.exists():
            command(
                "Temporary keychain deletion",
                "security", "delete-keychain",
                str(keychain),
            )
    finally:
        if work.exists():
            shutil.rmtree(work)


def sign(app, evidence):
    require(
        sys.platform == "darwin",
        "Signing requires macOS",
    )

    require(
        os.environ.get("GITHUB_EVENT_NAME")
        in ("workflow_dispatch", "push")
        and os.environ.get("GITHUB_REF") == "refs/heads/develop",
        "Signing requires an authorized event on develop",
    )

    work = workspace()
    work.mkdir(mode=0o700, exist_ok=False)

    try:
        p12 = work / "certificate.p12"
        profile_file = work / "profile.mobileprovision"

        for env, destination in (
            ("FCA_PROBE_P12_BASE64", p12),
            ("FCA_PROBE_PROFILE_BASE64", profile_file),
        ):
            value = os.environ.get(env, "")

            require(
                bool(value),
                "Required signing secret is missing",
            )

            try:
                decoded = base64.b64decode(
                    "".join(value.split()),
                    validate=True,
                )
            except Exception:
                raise ProbeError(
                    "Signing secret is not valid Base64"
                ) from None

            require(
                bool(decoded),
                "Decoded signing secret is empty",
            )

            destination.write_bytes(decoded)
            destination.chmod(0o600)

        password = os.environ.get(
            "FCA_PROBE_P12_PASSWORD", ""
        )

        require(
            bool(password),
            "PKCS12 password is missing",
        )

        profile = plistlib.loads(
            command(
                "Profile decoding",
                "security", "cms", "-D", "-i",
                str(profile_file),
            )
        )

        expected = validate_profile(profile)

        info = plistlib.loads(
            (app / "Info.plist").read_bytes()
        )

        require(
            info.get("CFBundleIdentifier") == BUNDLE
            and info.get("CFBundleDisplayName") == "FCA Intent Probe"
            and info.get("FCAEnvironment") == "intentprobe",
            "Probe application identity mismatch",
        )

        require(
            not list(app.rglob("*.appex")),
            "Unexpected extension requires signing review",
        )

        keychain = work / "probe.keychain-db"
        key_password = secrets.token_urlsafe(32)

        command(
            "Keychain creation",
            "security", "create-keychain",
            "-p", key_password,
            str(keychain),
        )

        command(
            "Keychain timeout",
            "security", "set-keychain-settings",
            "-lut", "21600",
            str(keychain),
        )

        command(
            "Keychain unlock",
            "security", "unlock-keychain",
            "-p", key_password,
            str(keychain),
        )

        command(
            "Certificate import",
            "security", "import",
            str(p12),
            "-k", str(keychain),
            "-P", password,
            "-T", "/usr/bin/codesign",
        )

        command(
            "Key access",
            "security", "set-key-partition-list",
            "-S", "apple-tool:,apple:",
            "-s",
            "-k", key_password,
            str(keychain),
        )

        # Select the identity by certificate SHA-1, not its name.
        identity = signing_identity(
            keychain,
            profile["DeveloperCertificates"],
        )

        entitlements = work / "entitlements.plist"

        entitlements.write_bytes(
            plistlib.dumps(expected)
        )

        payload = work / "Payload"
        payload.mkdir()

        signed = payload / "FamilyCarAgent.app"

        shutil.copytree(
            app,
            signed,
            symlinks=True,
        )

        shutil.copyfile(
            profile_file,
            signed / "embedded.mobileprovision",
        )

        nested = (
            list(signed.rglob("*.dylib"))
            + list(signed.rglob("*.framework"))
        )

        for item in sorted(
            nested,
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            command(
                "Nested code signing",
                "codesign",
                "--force",
                "--sign", identity,
                "--keychain", str(keychain),
                "--timestamp=none",
                str(item),
            )

        command(
            "Application signing",
            "codesign",
            "--force",
            "--sign", identity,
            "--keychain", str(keychain),
            "--timestamp=none",
            "--entitlements", str(entitlements),
            str(signed),
        )

        command(
            "Signature verification",
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            str(signed),
        )

        actual = plistlib.loads(
            command(
                "Signed entitlements",
                "codesign",
                "-d",
                "--entitlements", ":-",
                str(signed),
            )
        )

        require(
            actual == expected,
            "Signed entitlements do not match "
            "the minimal probe entitlements",
        )

        leaf = work / "signer"

        command(
            "Signer verification",
            "codesign",
            "-d",
            "--extract-certificates", str(leaf),
            str(signed),
        )

        require(
            hashlib.sha1(
                (work / "signer0").read_bytes()
            ).hexdigest().upper() == identity,
            "Final signature uses an unexpected certificate",
        )

        require(
            (signed / "embedded.mobileprovision").read_bytes()
            == profile_file.read_bytes(),
            "Embedded profile differs from validated profile",
        )

        command(
            "Signed metadata verification",
            sys.executable,
            str(
                Path(__file__).with_name(
                    "app-intents-poc.py"
                )
            ),
            "verify",
            str(signed),
            str(evidence / "metadata-report.json"),
            "--probe",
        )

        ipa = (
            evidence
            / "FCA-Intent-Probe-Development.ipa"
        )

        command(
            "IPA packaging",
            "ditto",
            "-c", "-k",
            "--keepParent",
            str(payload),
            str(ipa),
        )

        unpacked = work / "verified-ipa"

        command(
            "IPA extraction",
            "ditto",
            "-x", "-k",
            str(ipa),
            str(unpacked),
        )

        packaged = (
            unpacked
            / "Payload"
            / "FamilyCarAgent.app"
        )

        command(
            "IPA signature verification",
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            str(packaged),
        )

        require(
            (packaged / "embedded.mobileprovision").read_bytes()
            == profile_file.read_bytes(),
            "IPA profile differs from validated profile",
        )

        require(
            plistlib.loads(
                (packaged / "Info.plist").read_bytes()
            ) == info,
            "IPA identity changed",
        )

        command(
            "IPA metadata verification",
            sys.executable,
            str(
                Path(__file__).with_name(
                    "app-intents-poc.py"
                )
            ),
            "verify",
            str(packaged),
            str(evidence / "metadata-report.json"),
            "--probe",
        )

        (evidence / "signing-report.json").write_text(
            json.dumps(
                {
                    "bundle_id": BUNDLE,
                    "team_id": TEAM,
                    "development_signature_verified": True,
                    "embedded_profile_verified": True,
                    "registered_device_count": 1,
                    "entitlements_verified": True,
                    "ipa_roundtrip_verified": True,
                    "ipa_sha256": hashlib.sha256(
                        ipa.read_bytes()
                    ).hexdigest(),
                    "device_installation_verified": False,
                },
                indent=2,
            ) + "\n"
        )

    finally:
        cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "mode",
        choices=["sign", "cleanup"],
    )

    parser.add_argument(
        "app",
        type=Path,
        nargs="?",
    )

    parser.add_argument(
        "evidence",
        type=Path,
        nargs="?",
    )

    args = parser.parse_args()

    try:
        if args.mode == "cleanup":
            cleanup()
        else:
            sign(args.app, args.evidence)

    except Exception as error:
        # Never print raw tool output or signing secrets.
        message = (
            str(error)
            if isinstance(error, ProbeError)
            else "Probe signing or cleanup failed"
        )

        print(message, file=sys.stderr)
        sys.exit(1)
