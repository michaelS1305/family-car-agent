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
assert 'AppAssetImage(path: destination.asset)' in screen and '.accessibilityLabel(destination.label)' in screen
assert '.contentShape(Rectangle())' in screen and r'.environment(\.layoutDirection, .leftToRight)' in screen
assert 'glassEffect' not in screen and '.clipped()' not in screen
print('PASS: seven Dashboard PNGs' + (' packaged byte-for-byte' if len(sys.argv) > 1 else ' present') + '; navigation/logout wiring (static, not device-tested)')
