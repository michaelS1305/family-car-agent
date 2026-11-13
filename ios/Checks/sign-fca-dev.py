
#!/usr/bin/env python3
"""Sign Xcode-built FCA Dev on an ephemeral macOS GitHub Actions runner.

Never modifies the input .app.
No signing secrets or arbitrary tool output are logged.
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
import shlex
import shutil
import subprocess
import sys
import tempfile

from firebase_dev_config import validate_bundle

TEAM = "GT43M39TLK"
SOURCE_BUNDLE = "com.familycaragent.app.dev"
INSTALLED_BUNDLE = "com.familycaragent.app.dev"
PROFILE_NAME = "FCA iOS Dev Development"
IPA_NAME = "FCA-Dev-AppIntents-Development.ipa"
REPORT_NAME = "fca-dev-signing-report.json"


class SignError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SignError(message)


def sign_failure_category(stderr):
    lower = stderr.decode("utf-8", errors="replace").lower()

    if "no identity found" in lower:
        return "signing identity not found"
    if "errsecinternalcomponent" in lower:
        return "errSecInternalComponent"
    if "user interaction is not allowed" in lower:
        return "Keychain access denied"
    if "resource fork" in lower or "finder information" in lower:
        return "resource fork or Finder metadata"
    if "bundle format" in lower:
        return "invalid bundle format"
    if "unsupported" in lower and "entitlement" in lower:
        return "unsupported entitlement"
    if "unsealed contents" in lower:
        return "unsealed bundle contents"
    if "already signed" in lower:
        return "existing signature conflict"

    return "unclassified codesign failure"


def call(label, *args):
    diagnostic_only = label.startswith("Diagnostic ")
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **({"timeout": 30} if diagnostic_only else {}),
    )

    if result.returncode:
        if label == "Certificate import":
            diagnostic = result.stderr.decode(
                "utf-8", errors="replace"
            ).lower()

            if (
                "mac verify failure" in diagnostic
                or "mac verification failed" in diagnostic
                or "invalid password" in diagnostic
                or "wrong password" in diagnostic
                or "passphrase you entered is not correct" in diagnostic
            ):
                category = "PKCS12_INTEGRITY_PASSWORD_OR_COMPATIBILITY"
            elif (
                "unsupported" in diagnostic
                or "unknown pbe algorithm" in diagnostic
            ):
                category = "PKCS12_UNSUPPORTED_FORMAT"
            elif (
                "user interaction is not allowed" in diagnostic
                or "authorization" in diagnostic
            ):
                category = "KEYCHAIN_ACCESS_DENIED"
            elif (
                "already exists" in diagnostic
                or "duplicate" in diagnostic
            ):
                category = "KEYCHAIN_DUPLICATE_ITEM"
            else:
                category = "UNKNOWN_IMPORT_FAILURE"

            raise SignError(
                f"Certificate import failed (exit {result.returncode}); "
                f"diagnostic_category={category}"
            )

        if label in ("Preflight signing", "Application signing"):
            raise SignError(
                f"{label} failed (exit {result.returncode}); "
                f"diagnostic_category={sign_failure_category(result.stderr)}"
            )

        raise SignError(
            f"{label} failed (exit {result.returncode}); "
            "private tool output suppressed"
        )

    return result.stdout


def pkcs12_diagnostics(cert_file):
    """Best-effort diagnostics only; never change the Apple import decision.

    OpenSSL inherits the existing password environment variable. Neither the
    password nor raw tool output is printed, including on timeout or failure.
    """
    try:
        version = call("Diagnostic macOS version", "/usr/bin/sw_vers", "-productVersion").decode().strip()
        safe = re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}", version)
        print("macOS version: " + (version if safe else "UNAVAILABLE"))
    except (SignError, OSError, subprocess.TimeoutExpired, UnicodeError):
        print("macOS version: UNAVAILABLE")

    # The system openssl may be LibreSSL. Prefer OpenSSL 3 for this diagnostic
    # so its parser can distinguish a modern P12 from Apple import support.
    candidates = ["/opt/homebrew/opt/openssl@3/bin/openssl",
                  "/usr/local/opt/openssl@3/bin/openssl", shutil.which("openssl")]
    executable = None
    for candidate in dict.fromkeys(p for p in candidates if p):
        if not Path(candidate).is_file():
            continue
        try:
            raw = call("Diagnostic OpenSSL version", candidate, "version").decode()
            match = re.match(r"^(OpenSSL|LibreSSL) ([0-9]+\.[0-9]+\.[0-9]+[a-z]?)(?=\s|$)", raw)
            if match:
                print("Crypto tool version: " + match.group(1) + " " + match.group(2))
                if match.group(1) == "OpenSSL" and match.group(2).startswith("3."):
                    executable = candidate
                    break
        except (SignError, OSError, subprocess.TimeoutExpired, UnicodeError):
            continue
    if executable is None:
        print("PKCS12 preflight: FAIL; diagnostic_category=OPENSSL3_UNAVAILABLE")
        return
    try:
        # -noout suppresses all credential output. MAC verification remains on.
        call("Diagnostic PKCS12 validation", executable, "pkcs12",
             "-in", str(cert_file), "-noout", "-passin", "env:FCA_PROBE_P12_PASSWORD")
        print("PKCS12 preflight: PASS")
    except SignError:
        print("PKCS12 preflight: FAIL; diagnostic_category=PKCS12_VALIDATION_FAILED")
    except subprocess.TimeoutExpired:
        print("PKCS12 preflight: FAIL; diagnostic_category=VALIDATION_TIMEOUT")
    except OSError:
        print("PKCS12 preflight: FAIL; diagnostic_category=VALIDATOR_UNAVAILABLE")


def decode_secret(name, destination):
    raw = os.environ.get(name, "")
    require(bool(raw), f"Required signing secret missing: {name}")

    try:
        data = base64.b64decode(
            "".join(raw.split()),
            validate=True,
        )
    except Exception:
        raise SignError(
            f"Invalid Base64 signing secret: {name}"
        ) from None

    require(bool(data), f"Decoded signing secret empty: {name}")

    destination.write_bytes(data)
    destination.chmod(0o600)


def signing_identity(keychain, certificates):
    output = call(
        "Signing identity lookup",
        "security",
        "find-identity",
        "-v",
        "-p",
        "codesigning",
        str(keychain),
    ).decode()

    candidates = re.findall(
        r"^\s*\d+\)\s+([0-9A-Fa-f]{40})(?=\s|$)",
        output,
        re.MULTILINE,
    )

    permitted = {
        hashlib.sha1(bytes(cert)).hexdigest().upper()
        for cert in certificates
    }

    matches = [
        identity.upper()
        for identity in candidates
        if identity.upper() in permitted
    ]

    require(
        len(matches) == 1,
        "FCA Dev signing identity mismatch: "
        f"valid_keychain_identities={len(candidates)}, "
        f"profile_certificates={len(certificates)}, "
        f"matching_identities={len(matches)}",
    )

    return matches[0]


def app_info(app):
    return plistlib.loads(
        (app / "Info.plist").read_bytes()
    )


def metadata_snapshot(app):
    folder = app / "Metadata.appintents"

    require(
        folder.is_dir(),
        "App Intents metadata directory missing",
    )

    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file()
    )

    require(
        files and all(p.stat().st_size for p in files),
        "App Intents metadata missing or empty",
    )

    content = b"\n".join(
        p.read_bytes() for p in files
    )

    for action in (
        b"FCATakeVehicleIntent",
        b"FCAReturnVehicleIntent",
    ):
        require(
            action in content,
            "Expected TAKE/RETURN action missing from metadata",
        )

    return {
        str(p.relative_to(folder)): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in files
    }


def signed_entitlements(app):
    return plistlib.loads(
        call(
            "Signed entitlements read",
            "codesign",
            "-d",
            "--entitlements",
            ":-",
            str(app),
        )
    )


def verify_push_entitlements(entitlements):
    require(
        entitlements.get("aps-environment") == "development",
        "Development APNs entitlement required",
    )

    require(
        entitlements.get("com.apple.developer.applesignin")
        == ["Default"],
        "Sign in with Apple entitlement required",
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
        "Provisioning profile expiration missing",
    )

    if expiration.tzinfo is None:
        expiration = expiration.replace(
            tzinfo=dt.timezone.utc
        )

    require(
        expiration > dt.datetime.now(dt.timezone.utc),
        "Provisioning profile expired",
    )

    require(
        "iOS" in profile.get("Platform", []),
        "Provisioning profile is not for iOS",
    )

    require(
        bool(profile.get("ProvisionedDevices")),
        "Development profile has no registered devices",
    )

    require(
        not profile.get("ProvisionsAllDevices"),
        "Enterprise profile is not permitted",
    )

    require(
        bool(profile.get("DeveloperCertificates")),
        "Development profile has no signing certificates",
    )

    entitlements = dict(
        profile.get("Entitlements", {})
    )

    verify_push_entitlements(entitlements)

    require(
        entitlements.get("get-task-allow") is True,
        "Not a Development provisioning profile",
    )

    expected_app_id = f"{TEAM}.{INSTALLED_BUNDLE}"

    require(
        entitlements.get("application-identifier")
        == expected_app_id,
        "Provisioning App ID does not match FCA Dev",
    )

    require(
        entitlements.get(
            "com.apple.developer.team-identifier"
        ) == TEAM,
        "Entitlement team does not match",
    )

    groups = entitlements.get(
        "keychain-access-groups"
    )

    require(
        groups is not None,
        "Provisioning Keychain groups missing",
    )

    if groups is not None:
        require(
            isinstance(groups, list)
            and bool(groups)
            and all(
                isinstance(group, str)
                for group in groups
            ),
            "Provisioning keychain groups invalid",
        )

        require(
            any(
                group == expected_app_id
                or (
                    group.endswith("*")
                    and expected_app_id.startswith(
                        group[:-1]
                    )
                )
                for group in groups
            ),
            "Provisioning profile does not authorize "
            "the FCA Dev Keychain group",
        )

    entitlements["keychain-access-groups"] = [expected_app_id]

    return entitlements, expiration


def get_user_keychains():
    output = call(
        "Read user Keychain search list",
        "security",
        "list-keychains",
        "-d",
        "user",
    )

    return [
        item
        for line in output.decode().splitlines()
        for item in shlex.split(line)
    ]


def set_user_keychains(paths):
    call(
        "Set user Keychain search list",
        "security",
        "list-keychains",
        "-d",
        "user",
        "-s",
        *paths,
    )


def sign(input_app, evidence):
    require(
        sys.platform == "darwin",
        "FCA Dev signing requires macOS",
    )

    require(
        os.environ.get("GITHUB_REF") == "refs/heads/develop"
        and os.environ.get("GITHUB_EVENT_NAME")
        in ("push", "workflow_dispatch"),
        "Signing requires authorized develop workflow",
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

    info = app_info(input_app)

    require(
        info.get("CFBundleIdentifier") == SOURCE_BUNDLE,
        "Xcode source Bundle ID mismatch",
    )

    require(
        info.get("FCAEnvironment") == "development",
        "Source is not FCA Dev",
    )

    require(
        not list(input_app.rglob("*.appex")),
        "Unexpected app extension: separate signing review required",
    )

    original_metadata = metadata_snapshot(input_app)

    validate_bundle(input_app)

    with tempfile.TemporaryDirectory(
        prefix="fca-dev-sign-"
    ) as temporary:
        root = Path(temporary)

        cert_file = root / "certificate.p12"
        profile_file = root / "profile.mobileprovision"
        keychain = root / "fca-dev.keychain-db"

        key_password = secrets.token_urlsafe(32)

        # Environment names retained for ios.yml compatibility.
        decode_secret(
            "FCA_PROBE_P12_BASE64",
            cert_file,
        )

        decode_secret(
            "FCA_DEV_PROFILE_BASE64",
            profile_file,
        )

        cert_password = os.environ.get(
            "FCA_PROBE_P12_PASSWORD",
            "",
        )

        require(
            bool(cert_password),
            "P12 password missing",
        )

        pkcs12_diagnostics(cert_file)

        profile = plistlib.loads(
            call(
                "Provisioning profile decoding",
                "security",
                "cms",
                "-D",
                "-i",
                str(profile_file),
            )
        )

        entitlements, expiration = verify_profile(profile)

        entitlements_file = root / "entitlements.plist"
        entitlements_file.write_bytes(
            plistlib.dumps(entitlements)
        )

        payload = root / "Payload"
        payload.mkdir()

        signed = payload / "FamilyCarAgent.app"

        shutil.copytree(
            input_app,
            signed,
            symlinks=True,
        )

        # Preserve the original Info.plist.
        require(
            app_info(signed).get("CFBundleIdentifier")
            == INSTALLED_BUNDLE,
            "Copied FCA Dev Bundle ID mismatch",
        )

        shutil.copyfile(
            profile_file,
            signed / "embedded.mobileprovision",
        )

        require(
            metadata_snapshot(signed) == original_metadata,
            "App Intents metadata changed before signing",
        )

        original_keychains = None
        keychain_created = False

        try:
            call(
                "Temporary Keychain creation",
                "security",
                "create-keychain",
                "-p",
                key_password,
                str(keychain),
            )

            keychain_created = True

            call(
                "Temporary Keychain settings",
                "security",
                "set-keychain-settings",
                "-lut",
                "21600",
                str(keychain),
            )

            call(
                "Temporary Keychain unlock",
                "security",
                "unlock-keychain",
                "-p",
                key_password,
                str(keychain),
            )

            original_keychains = get_user_keychains()

            set_user_keychains(
                [str(keychain)]
                + [
                    p
                    for p in original_keychains
                    if p != str(keychain)
                ]
            )

            call(
                "Certificate import",
                "security",
                "import",
                str(cert_file),
                "-k",
                str(keychain),
                "-P",
                cert_password,
                "-T",
                "/usr/bin/codesign",
            )

            call(
                "Code-signing key access",
                "security",
                "set-key-partition-list",
                "-S",
                "apple-tool:,apple:",
                "-s",
                "-k",
                key_password,
                str(keychain),
            )

            identity = signing_identity(
                keychain,
                profile["DeveloperCertificates"],
            )

            # Verify imported identity independently.
            preflight = root / "signing-preflight"

            shutil.copyfile(
                "/usr/bin/true",
                preflight,
            )

            preflight.chmod(0o755)

            call(
                "Preflight signing",
                "codesign",
                "--force",
                "--sign",
                identity,
                "--keychain",
                str(keychain),
                "--timestamp=none",
                str(preflight),
            )

            call(
                "Preflight signature verification",
                "codesign",
                "--verify",
                "--strict",
                str(preflight),
            )

            nested = sorted(
                (
                    p
                    for p in signed.rglob("*")
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
                    "--sign",
                    identity,
                    "--keychain",
                    str(keychain),
                    "--timestamp=none",
                    str(item),
                )

            call(
                "Application signing",
                "codesign",
                "--force",
                "--sign",
                identity,
                "--keychain",
                str(keychain),
                "--timestamp=none",
                "--entitlements",
                str(entitlements_file),
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

            requirement = (
                '=certificate leaf = H"'
                + identity
                + '"'
            )

            call(
                "Signer certificate verification",
                "codesign",
                "--verify",
                "--strict",
                "-R",
                requirement,
                str(signed),
            )

            require(
                signed_entitlements(signed) == entitlements,
                "Signed entitlements differ from requested entitlements",
            )

            verify_push_entitlements(
                signed_entitlements(signed)
            )

            validate_bundle(signed)

            require(
                (
                    signed / "embedded.mobileprovision"
                ).read_bytes() == profile_file.read_bytes(),
                "Embedded provisioning profile mismatch",
            )

            require(
                app_info(signed).get("CFBundleIdentifier")
                == INSTALLED_BUNDLE,
                "Signed Bundle ID changed",
            )

            require(
                metadata_snapshot(signed) == original_metadata,
                "App Intents metadata changed after signing",
            )

            ipa = evidence / IPA_NAME

            call(
                "IPA packaging",
                "ditto",
                "-c",
                "-k",
                "--keepParent",
                str(payload),
                str(ipa),
            )

            extraction = root / "verified-ipa"

            call(
                "IPA extraction",
                "ditto",
                "-x",
                "-k",
                str(ipa),
                str(extraction),
            )

            packaged = (
                extraction
                / "Payload"
                / "FamilyCarAgent.app"
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

            verify_push_entitlements(
                signed_entitlements(packaged)
            )

            validate_bundle(packaged)

            require(
                (
                    packaged / "embedded.mobileprovision"
                ).read_bytes() == profile_file.read_bytes(),
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
                "entitlements_match_requested": True,
                "development_apns_entitlement_verified": True,
                "firebase_dev_configuration_verified": True,
                "app_intents_metadata_preserved": True,
                "ipa_roundtrip_verified": True,
                "preflight_signing_verified": True,
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
            # Restore original Keychain search list.
            try:
                if original_keychains is not None:
                    set_user_keychains(
                        original_keychains
                    )
            finally:
                if keychain_created:
                    subprocess.run(
                        [
                            "security",
                            "delete-keychain",
                            str(keychain),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "app",
        type=Path,
    )

    parser.add_argument(
        "evidence",
        type=Path,
    )

    args = parser.parse_args()

    try:
        sign(
            args.app,
            args.evidence,
        )
    except SignError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        print(
            "FCA Dev signing failed; "
            "private diagnostic details suppressed",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
