import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { notificationPermissionLabel } from '../src/push/pushNotifications.ts'

const settingsSource = readFileSync(
  new URL('../src/components/SettingsScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)
const appCssSource = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const legalSource = readFileSync(new URL('../src/legal/legalDocuments.ts', import.meta.url), 'utf8')

test('settings is a dedicated Dashboard category with the shared identity and icon', () => {
  assert.match(dashboardSource, /<SettingsScreen/)
  assert.match(dashboardSource, /<SettingsScreen/)
  assert.match(settingsSource, /<h1>Family Car Agent<\/h1>/)
  assert.match(settingsSource, /<DashboardCategoryIcon icon="settings"/)
  assert.match(settingsSource, /<h2>הגדרות<\/h2>/)
  assert.doesNotMatch(dashboardSource, /CategoryPlaceholderScreen/)
})

test('screen contains the approved phase-one groups and exact account order', () => {
  for (const title of ['חשבון', 'תצוגה', 'הרשאות']) {
    assert.match(settingsSource, new RegExp(`>${title}<`))
  }
  const account = ['>שם<', '>המשפחה שלי<', '>אימייל<', '>קוד חיבור ל־CarPlay<']
  let previous = -1
  for (const marker of account) {
    const index = settingsSource.indexOf(marker)
    assert.ok(index > previous)
    previous = index
  }
  assert.match(settingsSource, /מצב תצוגה/)
  assert.match(settingsSource, /גודל טקסט/)
  assert.match(settingsSource, /שליחת התראות/)
  assert.match(settingsSource, /מיקום/)
  assert.match(settingsSource, /CarPlay/)
})

test('account values use a two-column grid and email comes read-only from Supabase session', () => {
  assert.match(appCssSource, /\.settings-row,[\s\S]*?grid-template-columns:/)
  assert.doesNotMatch(appCssSource, /button\.settings-row:not\(\.settings-row-danger\)::after/)
  assert.match(settingsSource, /userEmail: string/)
  assert.match(appSource, /userEmail=\{session\.user\.email \?\? ''\}/)
  assert.doesNotMatch(settingsSource, /type="email"|onChange=.*userEmail/)
})

test('personal CarPlay code is masked by default and uses the existing authenticated setup source', () => {
  assert.match(settingsSource, /prepareCarPlaySetup\(accessToken, \{ signal: controller\.signal \}\)/)
  assert.match(settingsSource, /\[connectionCodeVisible, setConnectionCodeVisible\] = useState\(false\)/)
  assert.match(settingsSource, /connectionCodeVisible \? connectionCode : '••••••••••••'/)
  assert.match(settingsSource, /connectionCodeVisible \? 'הסתרת הקוד' : 'הצגת הקוד'/)
  assert.match(settingsSource, /setConnectionCodeVisible\(\(visible\) => !visible\)/)
})

test('personal CarPlay code can be copied exactly while it remains masked', () => {
  assert.match(settingsSource, /await copyConnectionCode\(connectionCode\)/)
  assert.match(settingsSource, /onClick=\{\(\) => void copyCode\(\)\}/)
  const copyHandler = settingsSource.slice(
    settingsSource.indexOf('const copyCode = async'),
    settingsSource.indexOf('const pushBusy'),
  )
  assert.doesNotMatch(copyHandler, /connectionCodeVisible/)
  assert.doesNotMatch(settingsSource, /localStorage|sessionStorage|shortcut_token|family_id|user_id/)
  assert.match(settingsSource, /aria-pressed=\{connectionCodeVisible\}/)
  assert.match(appCssSource, /\.settings-code-actions button[\s\S]*?min-height: 44px/)
})

test('account actions reuse Family navigation and existing bounded logout cleanup', () => {
  assert.match(settingsSource, /onClick=\{onOpenFamily\}/)
  assert.match(settingsSource, /await onLogout\(\)/)
  assert.match(dashboardSource, /onOpenFamily=\{\(\)=>openCategory\(DASHBOARD_CATEGORIES\[0\]\)\}/)
  assert.match(dashboardSource, /onLogout=\{handleLogout\}/)
})

test('permission labels represent browser state truthfully', () => {
  assert.equal(notificationPermissionLabel('granted'), 'מופעלות')
  assert.equal(notificationPermissionLabel('denied'), 'חסומות')
  assert.equal(notificationPermissionLabel('default'), 'לא הופעלו')
  assert.equal(notificationPermissionLabel('unsupported'), 'לא נתמך')
})

test('push is enabled only by switch gesture and disabled for this device', () => {
  assert.match(settingsSource, /onClick=\{togglePush\}/)
  assert.match(settingsSource, /void activatePushNotifications\(accessToken, pushConfig\)/)
  assert.match(settingsSource, /disableCurrentDevicePush\(accessToken\)/)
  assert.match(settingsSource, /pushState === 'denied'[\s\S]*?הגדרות האייפון/)
  assert.match(settingsSource, /inspectCurrentDevicePushState/)
  assert.match(settingsSource, /preloadPushConfiguration/)
})

test('navigation, focus, RTL and accessible settings controls remain consistent', () => {
  assert.match(settingsSource, /dir="rtl"/)
  assert.match(settingsSource, /backButtonRef\.current\?\.focus/)
  assert.match(settingsSource, /onClick=\{onBack\}/)
  assert.match(settingsSource, /role="switch"/)
  assert.match(settingsSource, /aria-checked=\{pushState === 'subscribed'\}/)
  assert.match(appCssSource, /\.settings-row[\s\S]*?min-height: 54px/)
  assert.match(appCssSource, /\.settings-screen button:focus-visible/)
})

test('dark mode covers the existing application surfaces without changing rotary selection mechanics', () => {
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.main-chat-screen/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.dashboard-screen/)
  assert.match(appCssSource, /\.family-member[\s\S]*?\.reservation-card[\s\S]*?\.history-current[\s\S]*?\.vehicles-development-card[\s\S]*?\.settings-card/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-selection-glow/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-knob::before/)
  assert.match(appCssSource, /html\[data-effective-theme='dark'\] \.rotary-knob/)
})

test('permission help, legal readers and truthful about details are present once', () => {
  assert.match(settingsSource, /shortcuts:\/\/open-shortcut\?name=Disconnect%20From%20CarPlay/)
  assert.match(settingsSource, /shortcuts:\/\//)
  assert.equal((settingsSource.match(/>פרטיות</g) ?? []).length, 1)
  assert.equal((settingsSource.match(/>תנאי שימוש</g) ?? []).length, 1)
  assert.equal((settingsSource.match(/>אודות</g) ?? []).length, 1)
  assert.match(settingsSource, /ערוץ התמיכה עדיין אינו זמין/)
  assert.match(settingsSource, /version/)
  assert.match(legalSource, /Google Maps/)
  assert.match(legalSource, /Gemini/)
  assert.doesNotMatch(legalSource, /zero retention|אפס שמירה|לא משמש.*אימון/)
})
