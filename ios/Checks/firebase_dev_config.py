"""Dev-only Firebase configuration validation; never include input in errors."""
import base64
import os
from pathlib import Path
import plistlib
import re

BUNDLE = "XTL-255E706B.com.familycaragent.app.dev"
PROJECT = "family-car-agent-dev"
SENDER = "452367109329"
SDK_VERSION = "12.19.3"


def validate(path):
    try:
        if Path(path).name != "GoogleService-Info.plist":
            raise ValueError()
        value = plistlib.loads(Path(path).read_bytes())
        valid = (isinstance(value, dict) and value.get("BUNDLE_ID") == BUNDLE
                 and value.get("PROJECT_ID") == PROJECT and value.get("GCM_SENDER_ID") == SENDER
                 and isinstance(value.get("GOOGLE_APP_ID"), str)
                 and re.fullmatch(r"1:" + SENDER + r":ios:[0-9a-f]+", value["GOOGLE_APP_ID"]))
        if not valid:
            raise ValueError()
    except Exception:
        raise ValueError("Firebase Dev configuration missing or invalid") from None


def validate_bundle(app):
    app = Path(app)
    configs = list(app.rglob("GoogleService-Info.plist"))
    if configs != [app / "GoogleService-Info.plist"]:
        raise ValueError("Expected exactly one root Firebase Dev configuration")
    validate(configs[0])


def decode(destination):
    destination = Path(destination)
    try:
        raw = os.environ.get("FCA_IOS_DEV_GOOGLE_SERVICE_INFO_BASE64", "")
        data = base64.b64decode("".join(raw.split()), validate=True)
        if not data:
            raise ValueError()
        with destination.open("xb") as output:
            output.write(data)
        destination.chmod(0o600)
    except Exception:
        raise ValueError("Firebase Dev secret missing, invalid, or destination unavailable") from None
    validate(destination)


if __name__ == "__main__":
    import sys
    try:
        decode(sys.argv[1])
    except Exception:
        sys.exit("Firebase Dev configuration injection failed; private input suppressed")
