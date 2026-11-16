"""Static wiring/privacy checks, not a substitute for iPhone layout testing."""
from pathlib import Path
import hashlib
import sys

root = Path(__file__).resolve().parents[1]
source = root / "Sources/FamilyCarAgent"
screen = (source / "Family/FamilyScreen.swift").read_text(encoding="utf-8")
model = (source / "Family/FamilyModel.swift").read_text(encoding="utf-8")
shell = (source / "AuthenticatedAppShell.swift").read_text(encoding="utf-8")
assert "FamilyScreen(entry: entry" in shell and "destination == .family" in shell
assert "if !keyboardVisible && navigation.isRoot" in shell
assert "NavigationStack" not in screen and "Form {" not in screen
assert screen.index("ChatStyle.wordmark") < screen.index("ScrollView {")
assert screen.index("icons/archive/family_icon.png") > screen.index("ScrollView {")
for label in ("אנשי המשפחה", "כתובת", "קוד משפחתי", "חזרה לדשבורד", "הזמנת בן משפחה", "העתקת קוד משפחתי"):
    assert label in screen
assert "VerifiedAddressPreview(location: model.candidate?.location)" in screen
assert "MapKit" not in screen and "CLGeocoder" not in screen
assert ".rightToLeft" in screen and ".preferredColorScheme(" not in screen
assert "confirmationDialog" in screen and "Button(\"אשר\", action: model.regenerate)" in screen
assert ".localOnly: true" in screen and ".expirationDate:" in screen
assert "UIActivityViewController" in screen and "model.closeShare()" in screen
assert "model.stop()" in screen and "entry.familyIdentity" in screen
for path in (source / "Family").glob("*.swift"):
    text = path.read_text(encoding="utf-8")
    for forbidden in ("print(", "Logger(", "NSLog(", "UserDefaults", "URLSession("):
        assert forbidden not in text, (path.name, forbidden)
assets = ["icons/archive/family_icon.png", "branding/in-app-brand/Family Car Agent Road Logo(1).png"]
for relative in assets:
    original = source / "Resources/AppAssets" / relative
    assert original.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    if len(sys.argv) > 1:
        candidates = list(Path(sys.argv[1]).rglob(Path(relative).name))
        assert candidates and any(hashlib.sha256(p.read_bytes()).digest() == hashlib.sha256(original.read_bytes()).digest() for p in candidates)
print("PASS: Family static UI wiring, original assets, shared map and privacy checks (no rendering claim)")

family = screen
assert 'Button("עריכה", action: model.editAddress)' not in family
assert 'Button(action: model.editAddress)' in family
assert 'Image(systemName: "pencil").font(.system(size: 25)).frame(width: 44, height: 44)' in family
assert '.disabled(!model.canManage).accessibilityLabel("עריכת כתובת")' in family
assert 'profile.can_edit_roles && model.stage == .view' in family

address = family.split('private func address(', 1)[1].split('private func code(', 1)[0]
for action in ('verifyAddress', 'confirmAddress'):
    assert f'Button(action: model.{action})' in address
assert address.count('.buttonStyle(BookingCapsuleStyle())') == 2
assert address.count('.buttonStyle(BookingCapsuleStyle(secondary: true))') == 3
assert address.count('.frame(minHeight: 32)') == 2
assert address.count('.disabled(model.addressBusy || !model.canManage)') == 2
assert address.count('action: model.cancelAddress') == 2
assert 'action: model.reviseAddress' in address
assert 'VerifiedAddressPreview(location: model.candidate?.location)' in address
print('PASS: address action styles, original handlers and busy/permission guards')
