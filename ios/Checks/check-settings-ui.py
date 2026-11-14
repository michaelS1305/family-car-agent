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
assert 'Button(action: logout)' in screen and '.disabled(entry.busy)' in screen
assert 'logout: entry.logout)' in shell
assert 'אפשרויות התצוגה, ההרשאות ופעולות החשבון עדיין אינן פעילות' not in screen
assert '.offset(y: -15).frame(height: 108)' in screen
assert '.task(id: scenePhase)' in screen and 'scenePhase == .active' in screen
assert 'CLLocationManager().authorizationStatus == .authorizedAlways' in screen
assert 'UNUserNotificationCenter.current().notificationSettings()' in screen
assert 'notificationsEnabled = settings.authorizationStatus == .authorized' in screen
assert '.authorizedWhenInUse' not in screen and '.provisional' not in screen and '.ephemeral' not in screen
assert 'UIApplication.openSettingsURLString' in screen
assert 'openURL(url) { accepted in settingsOpenFailed = !accepted }' in screen
assert 'permissionRow("מיקום", icon: "location", enabled: locationEnabled)' in screen
assert 'permissionRow("התראות", icon: "bell", enabled: notificationsEnabled)' in screen
assert 'Color.green' in screen and 'Toggle(' not in screen
assert '.accessibilityValue(enabled ? "פעיל" : "לא פעיל")' in screen
for forbidden in ['@AppStorage', 'SessionManager', 'AuthAPI', 'requestAuthorization',
                  'requestAlwaysAuthorization', 'requestWhenInUseAuthorization', 'startUpdatingLocation',
                  'registerForRemoteNotifications', 'finishLogout', 'sessions.clear']:
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
print('PASS: Settings assets/header, account/routes, system-only permission indicators and shared logout (static; device validation required)')
