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
assert 'CLLocationManager' not in screen and 'locationEnabled' not in screen
assert 'import CoreLocation' not in screen
assert 'UNUserNotificationCenter.current().notificationSettings()' in screen
assert 'notificationsEnabled = settings.authorizationStatus == .authorized' in screen
assert '.authorizedWhenInUse' not in screen and '.provisional' not in screen and '.ephemeral' not in screen
assert 'UIApplication.openSettingsURLString' in screen
assert 'openURL(url) { accepted in settingsOpenFailed = !accepted }' in screen
assert 'permissionRow("מיקום", icon: "location", enabled: locationPermission.ready)' in screen
assert 'enabled: Bool?' in screen and 'permission: enabled' in screen
assert 'if let permission {' in screen
assert 'permissionRow("התראות", icon: "bell", enabled: notificationsEnabled)' in screen
assert 'Color.green' in screen and 'Toggle(' not in screen
assert '.accessibilityValue(enabled.map { $0 ? "פעיל" : "לא פעיל" } ?? "")' in screen
for forbidden in ['SessionManager', 'AuthAPI', 'requestAuthorization',
                  'requestAlwaysAuthorization', 'requestWhenInUseAuthorization', 'startUpdatingLocation',
                  'registerForRemoteNotifications', 'finishLogout', 'sessions.clear']:
    assert forbidden not in screen, forbidden
assert 'icon: "about"' in screen and 'icon: "history"' not in screen
assert '.modifier(FCAWordmarkBlend())' in screen
assert 'כתובת אימייל' not in screen
assert '.fixedSize(horizontal: false, vertical: true)' in screen
assert 'entry.chatIdentity == identity' in screen and '!Task.isCancelled' in screen
assert '(slot * 428 / 512) / max(rect.width, rect.height)' in screen
appearance = (root / 'Sources/FamilyCarAgent/Appearance/AppAppearance.swift').read_text(encoding='utf-8')
for title in ['מערכת', 'בהיר', 'כהה']:
    assert title in appearance
assert '@AppStorage(AppAppearance.storageKey)' in screen
assert 'Button { appearancePreference = mode.rawValue }' in screen
assert 'appearance == mode ? .isSelected : []' in screen
assert 'בחירה אינה זמינה' not in screen
for title in ['זיהוי וחיבור אוטומטי', 'התנתקות', 'מחיקת חשבון']:
    assert title in screen
assets = root / 'Sources/FamilyCarAgent/Resources/AppAssets/icons/archive'
names = set(re.findall(r'icon: "([a-z_]+)"', screen)) | {'settings', 'theme'}
for name in names:
    assert (assets / f'{name}_icon.png').is_file(), name
print('PASS: Settings assets/header, account/routes, system-only permission indicators and shared logout (static; device validation required)')

# Confirmation delegates to the authenticated lifecycle, never directly to a provider.
assert 'SettingsDeletionNotice(entry: entry) { showDeleteAccount = false }' in screen
assert 'Button("ביטול", action: dismiss)' in screen
assert 'await entry.loadDeletionPreview()' in screen
assert 'await entry.submitDeletion()' in screen
assert '.disabled(entry.deletionBusy || entry.deletionPreview == nil)' in screen
assert 'מחיקת חשבון עדיין אינה זמינה' not in screen
assert '.onChange(of: entry.chatIdentity) { _, _ in showDeleteAccount = false }' in screen
notice = screen.split('private struct SettingsDeletionNotice: View {', 1)[1]
for forbidden in ('URLSession', 'logout', 'gateway', 'session'):
    assert forbidden not in notice, forbidden
for expected in ('FCAColors.color(.dialog)', '.rightToLeft', '.isModal', '.accessibilityFocused($focused)', '.allowsHitTesting(!showDeleteAccount)', '.accessibilityHidden(showDeleteAccount)'):
    assert expected in screen, expected
print('PASS: explicit deletion confirmation, preview gating, identity dismissal and semantic modal')

entry = (root / 'Sources/FamilyCarAgent/Auth/EntryModel.swift').read_text(encoding='utf-8')
submit = entry.split('func submitDeletion()', 1)[1].split('func checkDeletionStatus()', 1)[0]
assert submit.index('prepareLogout()') < submit.index('markDeletionPending()') < submit.index('try await request(')
assert 'sessions.session?.owner == owner, sessions.generation == generation' in submit
api = (root / 'Sources/FamilyCarAgent/Auth/AuthAPI.swift').read_text(encoding='utf-8')
assert '"/api/account/deletion", "/api/account/deletion/preview"' in api
assert 'method: fields == nil ? "GET" : "POST"' in api
assert 'forHTTPHeaderField: "Authorization"' in api
print('PASS: existing Push preparation precedes durable fence and POST; existing authenticated transport reused')

assert "Text(locationPermission.detail)" not in screen
assert "locationPermission.refresh()" in screen
