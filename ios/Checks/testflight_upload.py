"""Upload the existing verified IPA once. No build, signing or distribution commands."""
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile


class UploadError(Exception):
    pass


def require(value, code):
    if not value:
        raise UploadError(code)


def build_number(number):
    require(isinstance(number, str) and re.fullmatch(r"[1-9][0-9]*", number), "invalid_run_number")
    number = int(number)
    major = 1000 + number // 10000
    require(major <= 9999, "build_number_namespace_exhausted")
    return f"{major}.{number // 100 % 100}.{number % 100}"


def authorize():
    require(os.environ.get("GITHUB_EVENT_NAME") == "push"
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_REPOSITORY") == "michaelS1305/family-car-agent",
            "untrusted_upload_event")
    # Includes rerun-failed-jobs: uncertainty must never cause an automatic resend.
    require(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "upload_replay_blocked")


def verify_artifact(folder, expected_build):
    ipa = Path(folder) / "FamilyCarAgent-Production.ipa"
    report = json.loads((Path(folder) / "fca-production-signing-report.json").read_text())
    require(report.get("bundle_id") == "com.familycaragent.app"
            and report.get("environment") == "production", "wrong_signing_identity")
    for field in (
        "distribution_signature_verified", "signing_certificate_authorized_by_profile",
        "embedded_profile_verified", "entitlements_match_requested",
        "production_apns_entitlement_verified", "firebase_production_configuration_verified",
        "app_intents_metadata_preserved", "ipa_roundtrip_verified", "preflight_signing_verified",
    ):
        require(report.get(field) is True, "signing_report_not_verified")
    require(hashlib.sha256(ipa.read_bytes()).hexdigest() == report.get("ipa_sha256"), "ipa_hash_mismatch")
    with zipfile.ZipFile(ipa) as archive:
        candidates = [name for name in archive.namelist()
                      if re.fullmatch(r"Payload/[^/]+\.app/Info.plist", name)]
        require(len(candidates) == 1, "invalid_ipa_layout")
        info = plistlib.loads(archive.read(candidates[0]))
    require(info.get("CFBundleIdentifier") == "com.familycaragent.app"
            and info.get("FCAEnvironment") == "production", "wrong_ipa_identity")
    require(info.get("CFBundleVersion") == expected_build, "wrong_ipa_build_number")
    require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", info.get("CFBundleShortVersionString", "")), "invalid_marketing_version")
    return ipa.resolve()


def upload(folder):
    authorize()
    ipa = verify_artifact(folder, build_number(os.environ.get("GITHUB_RUN_NUMBER", "")))
    key_id = os.environ.get("FCA_ASC_KEY_ID", "")
    issuer = os.environ.get("FCA_ASC_ISSUER_ID", "")
    require(re.fullmatch(r"[A-Z0-9]{10}", key_id), "invalid_asc_key_id")
    try:
        uuid.UUID(issuer)
        key = base64.b64decode(os.environ.get("FCA_ASC_API_KEY_BASE64", ""), validate=True)
    except (ValueError, TypeError):
        raise UploadError("invalid_asc_configuration") from None
    require(key.startswith(b"-----BEGIN PRIVATE KEY-----") and b"-----END PRIVATE KEY-----" in key,
            "invalid_asc_private_key")
    with tempfile.TemporaryDirectory(prefix="fca-asc-") as temp:
        private_key = Path(temp) / f"AuthKey_{key_id}.p8"
        private_key.write_bytes(key)
        private_key.chmod(0o600)
        # Never inherit the Base64 secret into Apple's subprocess or print raw tool output.
        environment = {k: v for k, v in os.environ.items() if not k.startswith("FCA_ASC_")}
        try:
            result = subprocess.run([
                "xcrun", "altool", "--upload-app", "--type", "ios", "--file", str(ipa),
                "--apiKey", key_id, "--apiIssuer", issuer, "--p8-file-path", str(private_key),
                "--output-format", "json",
            ], capture_output=True, text=True, timeout=1500, env=environment, cwd=temp)
        except subprocess.TimeoutExpired:
            raise UploadError("apple_upload_timeout_outcome_unknown_check_app_store_connect") from None
        except OSError:
            raise UploadError("apple_upload_tool_unavailable") from None
        if result.returncode:
            codes = []
            try:
                payload = json.loads(result.stdout)
                for error in payload.get("product-errors", []):
                    code = str(error.get("code", ""))
                    if re.fullmatch(r"-?[0-9]{1,8}", code):
                        codes.append(code)
            except (ValueError, TypeError, AttributeError):
                pass
            raise UploadError("apple_upload_failed_check_app_store_connect" + (" codes=" + ",".join(codes[:10]) if codes else ""))
    print("Apple upload accepted. TestFlight processing is pending; no distribution requested.")


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "build-number":
            print("FCA_IOS_PROD_BUILD_NUMBER=" + build_number(os.environ.get("GITHUB_RUN_NUMBER", "")))
        elif len(sys.argv) == 3 and sys.argv[1] == "upload":
            upload(sys.argv[2])
        else:
            raise UploadError("invalid_command")
    except UploadError as error:
        sys.exit("TESTFLIGHT: " + str(error))
    except Exception:
        sys.exit("TESTFLIGHT: local_verification_or_configuration_failed")
