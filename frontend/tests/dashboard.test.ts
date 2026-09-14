import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  DASHBOARD_CATEGORIES,
  ROTARY_STEP_DEGREES,
  categoryIndexForRotation,
  confirmDashboardCategory,
  moveRotarySelection,
  normalizeAngleDelta,
  snapRotaryRotation,
} from '../src/dashboard/rotarySelector.ts'

const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)
const mainAppSource = readFileSync(
  new URL('../src/components/MainAppScreen.tsx', import.meta.url),
  'utf8',
)
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const appCssSource = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
const viteConfigSource = readFileSync(new URL('../vite.config.ts', import.meta.url), 'utf8')
const packageMetadata = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
) as { version: string }

test('dashboard exposes exactly the five approved categories in stable order', () => {
  assert.deepEqual(
    DASHBOARD_CATEGORIES.map(({ label }) => label),
    ['משפחה', 'רכבים', 'הגדרות', 'היסטוריה', 'מרכז הזמנות'],
  )
  assert.equal(DASHBOARD_CATEGORIES.length, 5)
  assert.equal(ROTARY_STEP_DEGREES, 72)
})

test('normalized pointer deltas do not jump at the angle wrap boundary', () => {
  assert.equal(normalizeAngleDelta(-358), 2)
  assert.equal(normalizeAngleDelta(358), -2)
  assert.equal(normalizeAngleDelta(72), 72)
})

test('rotation snaps deterministically and selects the nearest category', () => {
  assert.equal(snapRotaryRotation(38), 72)
  assert.equal(snapRotaryRotation(-38), -72)
  assert.equal(categoryIndexForRotation(72), 1)
  assert.equal(categoryIndexForRotation(-72), 4)
  assert.equal(moveRotarySelection(72, 1), 144)
  DASHBOARD_CATEGORIES.forEach((category, index) => {
    assert.equal(confirmDashboardCategory(index)?.label, category.label)
  })
})

test('hamburger opens the dashboard and its close control returns to chat', () => {
  assert.match(mainAppSource, /chat-menu-button[\s\S]*?onClick=\{\(\) => setDashboardOpen\(true\)\}/)
  assert.match(mainAppSource, /<DashboardScreen[\s\S]*?open=\{dashboardOpen\}[\s\S]*?onClose=\{closeDashboard\}/)
  assert.match(dashboardSource, /aria-label="חזרה לצ׳אט"/)
})

test('greeting and logout reuse authenticated app state and the existing auth flow', () => {
  assert.match(dashboardSource, /היי, \{userName\}/)
  assert.doesNotMatch(dashboardSource, /סובב את המתג לשירות מבוקש/)
  assert.doesNotMatch(dashboardSource, /מיכאל/)
  assert.match(dashboardSource, /מתנתקים….*התנתקות/)
  assert.match(appSource, /await cleanupPushBeforeLogout\(session\.access_token\)[\s\S]*?await invalidateAuthSession\(''\)/)
})

test('dashboard has no visible selected-status line', () => {
  assert.doesNotMatch(dashboardSource, /className="dashboard-confirmation"/)
  assert.doesNotMatch(dashboardSource, /נבחר:/)
})

test('application version is injected from package metadata', () => {
  assert.equal(typeof packageMetadata.version, 'string')
  assert.match(viteConfigSource, /__APP_VERSION__: JSON\.stringify\(packageMetadata\.version\)/)
  assert.match(dashboardSource, /<small>v\{version\}<\/small>/)
})

test('dashboard categories are direct accessible buttons without rotary confirmation', () => {
  assert.equal((dashboardSource.match(/className="dashboard-category-button"/g) ?? []).length, 1)
  assert.doesNotMatch(dashboardSource, /role="slider"|rotary-knob|<strong>OK<\/strong>/)
  assert.match(dashboardSource, /onClick=\{\(\)=>openCategory\(category\)\}/)
})

test('all five categories open dedicated screens', () => {
  for (const category of DASHBOARD_CATEGORIES) {
    assert.ok(category.label.length > 0)
  }
  assert.doesNotMatch(dashboardSource, /function CategoryPlaceholderScreen/)
  assert.match(dashboardSource, /setActiveCategory\(category\)[\s\S]*?setCategoryOpen\(true\)/)
  assert.doesNotMatch(dashboardSource, /בקרוב|coming soon|סטטיסטיקה/i)
  assert.match(dashboardSource, /activeCategory\.id===?'family'/)
  assert.match(dashboardSource, /<FamilyScreen/)
  assert.match(dashboardSource, /activeCategory\.id===?'reservations'/)
  assert.match(dashboardSource, /<ReservationCenterScreen/)
  assert.match(dashboardSource, /activeCategory\.id===?'history'/)
  assert.match(dashboardSource, /<HistoryScreen/)
  assert.match(dashboardSource, /activeCategory\.id===?'cars'/)
  assert.match(dashboardSource, /<VehiclesScreen/)
  assert.match(dashboardSource, /<SettingsScreen/)
})

test('category back preserves the mounted dashboard and restores focus', () => {
  assert.match(dashboardSource, /<div className="dashboard-content" inert=\{categoryOpen\}>/)
  assert.match(dashboardSource, /dashboard-category-button[\s\S]*?<FamilyScreen[\s\S]*?<ReservationCenterScreen[\s\S]*?<HistoryScreen[\s\S]*?<VehiclesScreen[\s\S]*?<SettingsScreen/)
  assert.match(dashboardSource, /onBack=\{closeCategory\}/)
  assert.match(dashboardSource, /setCategoryOpen\(false\)/)
  assert.match(dashboardSource, /closeButtonRef\.current\?\.focus/)
  assert.match(dashboardSource, /if\(categoryOpen\)closeCategory\(\)/)
})

test('dashboard transition and rotary motion respect reduced motion', () => {
  assert.match(appCssSource, /\.dashboard-screen \{[\s\S]*?transition:[\s\S]*?220ms/)
  assert.match(appCssSource, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(appCssSource, /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?transition: none !important;/)
})
