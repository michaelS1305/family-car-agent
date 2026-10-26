"""Source or built-resource checks. No network, device or credential output."""
import hashlib
import pathlib
import re
import struct
import sys

root = pathlib.Path(__file__).resolve().parents[1]
assets = root / 'Sources/FamilyCarAgent/Resources/EntryAssets'
expected = {'intro_logo.png': (1119, 1099), 'login_logo.png': (1254, 1254), 'google_sign_in.png': (720, 160)}
for name, size in expected.items():
    data = (assets / name).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    actual = struct.unpack('>II', data[16:24])
    assert actual == size, (name, actual)

# The local link targets are in-app document identifiers, not invented policy URLs.
legal = (root / 'Sources/FamilyCarAgent/EntryLegalDocument.swift').read_text(encoding='utf-8')
assert 'fca-entry-legal://privacy' in legal and 'fca-entry-legal://terms' in legal
android = root.parent / 'android/app/src/main/java/il/fca/companion/ui/LegalCopy.kt'
if android.exists():
    source = android.read_text(encoding='utf-8')
    copies = re.findall(r'LegalCopy\("[^"]+", """\n(.*?)\n"""', source, re.S)
    swift = re.findall(r'return """\n(.*?)\n            """', legal, re.S)
    assert copies == ['\n'.join(line[12:] for line in body.splitlines()) for body in swift]
    for name, original in [('login_logo.png', 'fca_logo.png'), ('google_sign_in.png', 'google_sign_in.png')]:
        assert (assets / name).read_bytes() == (root.parent / 'android/app/src/main/res/drawable-nodpi' / original).read_bytes()

manifest = (root / 'Package.swift').read_text(encoding='utf-8')
assert '.copy("Resources/EntryAssets")' in manifest
assert '.process("Resources/Assets.xcassets")' not in manifest
assert '"Resources/Assets.xcassets"' not in manifest
assert '"Resources/Assets.car"' not in manifest
assert not (root / 'Sources/FamilyCarAgent/Resources/Assets.xcassets').exists()
assert not (root / 'Sources/FamilyCarAgent/Resources/Assets.car').exists()
if len(sys.argv) == 2:
    app = pathlib.Path(sys.argv[1])
    for name in expected:
        matches = list(app.rglob('EntryAssets/' + name))
        assert len(matches) == 1, (name, 'missing or ambiguous packaged image')
        assert hashlib.sha256(matches[0].read_bytes()).digest() == hashlib.sha256((assets / name).read_bytes()).digest()
    assert not list(app.rglob('Assets.xcassets'))
    print('PASS: all three raw image resources packaged byte-for-byte; no xcassets catalog')
print('PASS: entry image dimensions, resource declaration, local legal links and available source-copy checks')
