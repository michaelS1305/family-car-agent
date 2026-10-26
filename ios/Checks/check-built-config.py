"""Read-only validation of public build metadata. Never print key values."""
import pathlib
import plistlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
with (root / "xtool/FamilyCarAgent.app/Info.plist").open("rb") as stream:
    info = plistlib.load(stream)
assert info["CFBundleIdentifier"] == "com.familycaragent.app.dev"
assert info["FCAEnvironment"] == "development"
assert info["CFBundleDisplayName"] == "FCA Dev"
assert info["CFBundleURLTypes"][0]["CFBundleURLSchemes"] == ["com.familycaragent.app.dev"]
key = info.get("FCASupabasePublishableKey", "")
assert not key or re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key)
with (root / "Config/Dev.entitlements").open("rb") as stream:
    entitlements = plistlib.load(stream)
assert entitlements == {"com.apple.developer.applesignin": ["Default"]}
print("PASS: built Dev identity, display name, environment and URL scheme; source Apple entitlement.")
print("Public key is configured; operator must verify its Dev project." if key else "MANUAL SETUP REQUIRED: Dev public publishable key is missing.")
print("Signing/provisioning and live providers are NOT verified by this check.")
