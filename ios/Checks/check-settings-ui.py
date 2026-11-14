"""Settings UI scaffold checks; not a device rendering test."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
screen = (root / 'Sources/FamilyCarAgent/Settings/SettingsScreen.swift').read_text(encoding='utf-8')
shell = (root / 'Sources/FamilyCarAgent/AuthenticatedAppShell.swift').read_text(encoding='utf-8')
assert 'destination == .settings' in shell
assert 'SettingsScreen(entry: entry' in shell
assert 'navigation.openFromSettings(.family)' in shell
assert 'navigation.openFromSettings(.vehicles)' in shell
assert 'isPresented: $navigation.vehicleHelpPresented' in shell
sections = ['חשבון', 'תצוגה', 'הרשאות', 'תנאי שימוש ופרטיות', 'אודות']
positions = [screen.index(f'SettingsCard(title: "{title}")') for title in sections]
assert positions == sorted(positions)
assert 'ScrollView {' in screen and '.rightToLeft' in screen
assert 'Button(action: back)' in screen
assert len(re.findall(r'\bButton\s*\(', screen)) == 3
assert '.constant(false)).labelsHidden().disabled(true)' in screen
for forbidden in ['@AppStorage', 'SessionManager', 'AuthAPI', 'openURL', 'requestAuthorization']:
    assert forbidden not in screen, forbidden
assert 'icon: "about"' in screen and 'icon: "history"' not in screen
assert '.blendMode(.multiply)' in screen
assert 'כתובת אימייל' not in screen
assert '.fixedSize(horizontal: false, vertical: true)' in screen
assert 'entry.chatIdentity == identity' in screen and '!Task.isCancelled' in screen
assert '(slot * 428 / 512) / max(rect.width, rect.height)' in screen
for title in ['מערכת', 'בהיר', 'כהה', 'זיהוי וחיבור אוטומטי', 'התנתקות', 'מחיקת חשבון']:
    assert title in screen
assets = root / 'Sources/FamilyCarAgent/Resources/AppAssets/icons/archive'
names = set(re.findall(r'icon: "([a-z_]+)"', screen)) | {'settings', 'theme'}
for name in names:
    assert (assets / f'{name}_icon.png').is_file(), name
print('PASS: Settings assets, normalized icons, account display, routes and inactive permission/actions (static)')
