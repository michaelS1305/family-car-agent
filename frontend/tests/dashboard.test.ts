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
  assert.match(dashboardSource, /סובב את המתג לשירות מבוקש/)
  assert.doesNotMatch(dashboardSource, /מיכאל/)
  assert.match(dashboardSource, /loggingOut \? 'מתנתקים…' : 'התנתקות'/)
  assert.match(appSource, /onLogout=\{\(\) => invalidateAuthSession\(''\)\}/)
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

test('rotary has one accessible slider and one real OK confirmation button', () => {
  assert.equal((dashboardSource.match(/role="slider"/g) ?? []).length, 1)
  assert.match(dashboardSource, /aria-valuetext=\{selectedCategory\.label\}/)
  assert.match(dashboardSource, /className="rotary-knob"[\s\S]*?onClick=\{\(\) => onConfirm/)
  assert.match(dashboardSource, /aria-label=\{`פתיחת \$\{selectedCategory\.label\}`\}/)
  assert.match(dashboardSource, /<strong>OK<\/strong>/)
})

test('one reusable placeholder opens every configured category without duplicated content', () => {
  for (const category of DASHBOARD_CATEGORIES) {
    assert.ok(category.label.length > 0)
  }
  assert.match(dashboardSource, /function CategoryPlaceholderScreen/)
  assert.match(dashboardSource, /<h1>Family Car Agent<\/h1>/)
  assert.match(dashboardSource, /<h2>\{category\.label\}<\/h2>/)
  assert.match(dashboardSource, /setActiveCategory\(category\)[\s\S]*?requestAnimationFrame[\s\S]*?setCategoryOpen\(true\)/)
  assert.doesNotMatch(dashboardSource, /בקרוב|coming soon|סטטיסטיקה/i)
})

test('category back preserves the mounted rotary and restores focus to OK', () => {
  assert.match(dashboardSource, /<div className="dashboard-content" inert=\{categoryOpen\}>/)
  assert.match(dashboardSource, /<RotarySelector[\s\S]*?<CategoryPlaceholderScreen/)
  assert.match(dashboardSource, /aria-label="חזרה ללוח הבקרה"/)
  assert.match(dashboardSource, /setCategoryOpen\(false\)/)
  assert.match(dashboardSource, /confirmButtonRef\.current\?\.focus/)
  assert.match(dashboardSource, /if \(categoryOpen\) closeCategory\(\)/)
})

test('dashboard transition and rotary motion respect reduced motion', () => {
  assert.match(appCssSource, /\.dashboard-screen \{[\s\S]*?transition:[\s\S]*?220ms/)
  assert.match(appCssSource, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(appCssSource, /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?transition: none !important;/)
})
