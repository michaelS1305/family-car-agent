"""Dashboard assets and wiring: source/bundle checks, not visual UI tests."""
import hashlib
import pathlib
import struct
import sys

root = pathlib.Path(__file__).resolve().parents[1]
assets = root / 'Sources/FamilyCarAgent/Resources/AppAssets'
paths = ['icons/archive/' + name + '_icon.png' for name in
         ['family', 'vehicles', 'settings', 'history', 'booking_center', 'logout']]
paths += ['branding/in-app-brand/Family Car Agent Road Logo(1).png']
for relative in paths:
    source = assets / relative
    data = source.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', relative
    width, height = struct.unpack('>II', data[16:24])
    assert width > 0 and height > 0
    if relative.startswith('icons/'):
        assert (width, height) == (512, 512), 'Geometry assumes complete square originals'
    if len(sys.argv) > 1:
        matches = list(pathlib.Path(sys.argv[1]).rglob(source.name))
        assert len(matches) == 1, relative
        assert hashlib.sha256(matches[0].read_bytes()).digest() == hashlib.sha256(data).digest(), relative
shell = (root / 'Sources/FamilyCarAgent/AuthenticatedAppShell.swift').read_text(encoding='utf-8')
screen = (root / 'Sources/FamilyCarAgent/Dashboard/DashboardScreen.swift').read_text(encoding='utf-8')
assert 'NavigationStack(path: $navigation.path)' in shell
assert 'if !keyboardVisible && navigation.isRoot' in shell
assert 'logout: entry.logout' in shell and 'busy: entry.busy' in shell
assert 'navigation.synchronize(identity)' in shell
assert 'ChatScreen(model: chat' in shell and '.opacity(chat.mode == .chat ? 1 : 0)' in shell
assert 'Canvas {' in screen and 'ForEach(DashboardDestination.allCases' in screen
assert 'AppAssetImage(path: destination.asset, monochromeControl: true)' in screen and '.accessibilityLabel(destination.label)' in screen
assert '.contentShape(Rectangle())' in screen and r'.environment(\.layoutDirection, .leftToRight)' in screen
assert 'glassEffect' not in screen and '.clipped()' not in screen
print('PASS: seven Dashboard PNGs' + (' packaged byte-for-byte' if len(sys.argv) > 1 else ' present') + '; navigation/logout wiring (static, not device-tested)')

# First-vehicle invitation: actual asset format and existing resource pipeline.
import zlib
image = assets / 'illustrations/first_vehicle_setup.png'
data = image.read_bytes()
assert struct.unpack('>II', data[16:24]) == (1672, 941)
assert data[24:26] == bytes([8, 6]), '8-bit RGBA'
pos, compressed = 8, b''
while pos < len(data):
    size = int.from_bytes(data[pos:pos+4], 'big')
    if data[pos+4:pos+8] == b'IDAT':
        compressed += data[pos+8:pos+8+size]
    pos += size + 12
scanlines = zlib.decompress(compressed)
assert scanlines[4] == 0, 'First pixel alpha is transparent (all PNG row filters)'
assert '.copy("Resources/AppAssets")' in (root / 'Package.swift').read_text()
dialog = (root / 'Sources/FamilyCarAgent/Dashboard/FirstVehicleSetupDialog.swift').read_text(encoding='utf-8')
for text in ['שנתחבר?', 'זה לוקח דקה והסוכן מחובר לרכב ומעדכן אוטומטית', 'להגדרה']:
    assert text in dialog
assert 'illustrations/first_vehicle_setup.png' in dialog
assert 'wordmark' not in dialog and 'logo' not in dialog.lower()
for token in ['ScrollView', 'isModal', 'accessibilityLabel', 'leftToRight', 'rightToLeft', 'ErrorPrimaryButtonStyle']:
    assert token in dialog
assert shell.count('VehiclesModel(gateway: entry)') == 1
assert '.allowsHitTesting(!errors.isPresented && !invitationVisible)' in shell
assert '.accessibilityHidden(errors.isPresented || invitationVisible)' in shell
cta = shell.split('private func configureFirstVehicle()')[1].split('// Only')[0]
assert 'guard invitationVisible' in cta and 'firstVehicleSetup.handle' in cta
assert 'chat.mode = .dashboard' in cta and 'navigation.open(.vehicles)' in cta
assert '.add' not in cta and 'AddVehicleScreen' not in cta
assert 'previous.contains(.vehicles)' in shell
print('PASS: invitation asset, safe shared-model wiring, existing Vehicles route, adaptive modal (static)')
