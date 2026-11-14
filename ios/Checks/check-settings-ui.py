"""Settings UI scaffold checks; not a device rendering test."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
screen = (root / 'Sources/FamilyCarAgent/Settings/SettingsScreen.swift').read_text(encoding='utf-8')
shell = (root / 'Sources/FamilyCarAgent/AuthenticatedAppShell.swift').read_text(encoding='utf-8')
assert 'destination == .settings' in shell
assert 'SettingsScreen(back: { navigation.back() })' in shell
sections = ['חשבון', 'תצוגה', 'הרשאות', 'תנאי שימוש ופרטיות', 'אודות']
positions = [screen.index(f'SettingsCard(title: "{title}")') for title in sections]
assert positions == sorted(positions)
assert 'ScrollView {' in screen and '.rightToLeft' in screen
assert 'Button(action: back)' in screen
assert len(re.findall(r'\bButton\s*\(', screen)) == 1
assert '.constant(false)).labelsHidden().disabled(true)' in screen
for forbidden in ['@State', '@AppStorage', 'SessionManager', 'AuthAPI', 'openURL', '.task', 'requestAuthorization']:
    assert forbidden not in screen, forbidden
for title in ['מערכת', 'בהיר', 'כהה', 'זיהוי וחיבור אוטומטי', 'התנתקות', 'מחיקת חשבון']:
    assert title in screen
assets = root / 'Sources/FamilyCarAgent/Resources/AppAssets/icons/archive'
names = set(re.findall(r'icon: "([a-z_]+)"', screen)) | {'settings', 'theme'}
for name in names:
    assert (assets / f'{name}_icon.png').is_file(), name
print('PASS: Settings section order, assets, RTL, existing route, and UI-only boundaries (static)')
