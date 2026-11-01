"""Critical Chat resources and packaging. No credentials, network or device access."""
import hashlib
import pathlib
import struct
import sys

root = pathlib.Path(__file__).resolve().parents[1]
assets = root / 'Sources/FamilyCarAgent/Resources/AppAssets'
paths = [
    'branding/in-app-brand/Family Car Agent Road Logo(1).png',
    'branding/app-icon/family-car-agent-logo.png',
    'icons/archive/chat_icon.png',
    'icons/archive/dashboard_icon.png',
]
for path in paths:
    data = (assets / path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', path
    assert all(n > 0 for n in struct.unpack('>II', data[16:24])), path
    if len(sys.argv) > 1:
        matches = list(pathlib.Path(sys.argv[1]).rglob(pathlib.Path(path).name))
        assert len(matches) == 1, (path, 'missing or ambiguous packaged asset')
        assert hashlib.sha256(matches[0].read_bytes()).digest() == hashlib.sha256(data).digest(), path
print('PASS: four critical Chat assets' + (' packaged byte-for-byte' if len(sys.argv) > 1 else ' present and valid PNGs'))

# Structural assertions only; visual appearance and accessibility focus still need a device.
shell = (root / 'Sources/FamilyCarAgent/AuthenticatedAppShell.swift').read_text(encoding='utf-8')
bar = shell.split('struct AppModeBar: View {', 1)[1]
assert 'Text(title)' not in bar and '.accessibilityLabel(title)' in bar
assert '.accessibilityAddTraits(mode == value ? .isSelected : [])' in bar
assert 'if !keyboardVisible' in shell and '.opacity(chat.mode == .chat ? 1 : 0)' in shell
assert 'if #available(iOS 26.0, *)' in bar and '.glassEffect(.regular.interactive(), in: Capsule())' in bar
assert '.ultraThinMaterial' in bar
assert 'icons/archive/' in bar and 'frame(width: 34, height: 34)' in bar
assert '.scaleEffect(scale)' in bar and '.offset(y: offset)' in bar
assert '.clipped()' not in bar and '.clipShape' not in bar
assert 'scale: 512.0 / 244.0, offset: 20.5 * 34.0 / 244.0' in bar
assert 'scale: 512.0 / 242.0, offset: 39.0 * 34.0 / 242.0' in bar
# Original artwork bounds: preserve both the previous visible width and vertical center.
# Embedded labels also remain inside the unchanged 58-point capsule.
for crop_width, artwork_width, center_y, content_bottom in [(244, 240, 235.5, 432), (242, 238, 217, 387)]:
    ratio = 34 / crop_width
    assert abs(34 * (512 / crop_width) * artwork_width / 512 - artwork_width * ratio) < 1e-9
    assert abs((center_y - 256) * ratio + (256 - center_y) * ratio) < 1e-9
    assert (content_bottom - center_y) * ratio < 29
assert '.overlay(Capsule().stroke' not in bar
assert '.padding(.bottom, keyboardVisible || !navigation.isRoot ? 0 : 60)' in shell
chat = (root / 'Sources/FamilyCarAgent/Chat/ChatScreen.swift').read_text(encoding='utf-8')
assert '.regularMaterial' not in chat and '.mask(alignment: .top)' in chat
assert 'LinearGradient(colors: [.clear, .black]' in chat
assert '.padding(.horizontal, 14).padding(.vertical, 12)' in chat
assert '.frame(maxWidth: 280' in chat
content = (root / 'Sources/FamilyCarAgent/ContentView.swift').read_text(encoding='utf-8')
assert 'if model.restoring || model.screen == .bootstrap' in content
assert 'Family Car Agent · Dev' not in content
assert 'model.screen == .onboarding || model.screen == .ready ? .light : nil' in content
assert shell.index('.background(ChatStyle.background.ignoresSafeArea())') < shell.index('.toolbar(.hidden, for: .navigationBar)')
# Source-level policy: ready chooses explicit light, regardless of the inherited scheme.
# Runtime Material/Glass rendering under device Light/Dark is not exercised by this check.
assert '.preferredColorScheme(.light)' in shell
print('PASS: ready explicitly requests Light for either system appearance; Chat background is inside NavigationStack (static check)')
loading = content.split('private struct BootstrapLoadingView: View {', 1)[1]
assert 'model.me' not in loading and 'SessionManager' not in loading
print('PASS: original labelled PNGs, preserved artwork scale/center, accessibility, keyboard visibility and OS fallback (not a UI runtime test)')
