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

test('settings is a dedicated Dashboard category with the shared identity and icon', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'settings'/)
  assert.match(dashboardSource, /<SettingsScreen/)
  assert.match(settingsSource, /<h1>Family Car Agent<\/h1>/)
  assert.match(settingsSource, /<DashboardCategoryIcon icon="settings"/)
  assert.match(settingsSource, /<h2>הגדרות<\/h2>/)
  assert.doesNotMatch(dashboardSource, /CategoryPlaceholderScreen/)
})

test('screen contains only the approved grouped settings', () => {
  for (const title of ['חשבון', 'תצוגה', 'הרשאות', 'התראות']) {
    assert.match(settingsSource, new RegExp(`>${title}<`))
  }
  assert.match(settingsSource, /מצב תצוגה/)
  assert.match(settingsSource, /גודל טקסט/)
  assert.match(settingsSource, /עדכונים על הרכב/)
  assert.doesNotMatch(settingsSource, /מצלמה|מיקרופון|מיקום|אנשי קשר/)
})

test('account actions reuse Family navigation and existing bounded logout cleanup', () => {
  assert.match(settingsSource, /onClick=\{onOpenFamily\}/)
  assert.match(settingsSource, /await onLogout\(\)/)
  assert.match(dashboardSource, /onOpenFamily=\{openFamily\}/)
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
  assert.equal((appCssSource.match(/\.rotary-selection-glow \{/g) ?? []).length, 1)
})
