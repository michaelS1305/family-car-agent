import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const historySource = readFileSync(
  new URL('../src/components/HistoryScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)
const mainAppSource = readFileSync(
  new URL('../src/components/MainAppScreen.tsx', import.meta.url),
  'utf8',
)

test('history category is real and reuses the dashboard history icon and heading', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'history'/)
  assert.match(dashboardSource, /<HistoryScreen/)
  assert.match(historySource, /<DashboardCategoryIcon icon="history"/)
  assert.match(historySource, /<h2>היסטוריה<\/h2>/)
})

test('active usage is rendered first without a fabricated end time', () => {
  const activePosition = historySource.indexOf('history.active_usage ?')
  const completedPosition = historySource.indexOf('history.recent_usage.length > 0')
  assert.ok(activePosition > -1 && activePosition < completedPosition)
  assert.match(historySource, /הרכב כרגע בשימוש/)
  assert.match(historySource, /history\.active_usage\.name/)
  assert.match(historySource, /history\.active_usage\.started_at/)
  assert.doesNotMatch(
    historySource.slice(activePosition, completedPosition),
    /ended_at|שעת סיום/,
  )
})

test('available, completed, empty, loading and retry states are truthful', () => {
  assert.match(historySource, /הרכב זמין כעת/)
  assert.match(historySource, /שימושים אחרונים/)
  assert.match(historySource, /usage\.name/)
  assert.match(historySource, /usage\.started_at/)
  assert.match(historySource, /usage\.ended_at/)
  assert.match(historySource, /אין עדיין היסטוריית שימוש ברכב/)
  assert.match(historySource, /טוענים היסטוריה…/)
  assert.match(historySource, /נסו שוב/)
  assert.doesNotMatch(historySource, /עריכה|מחיקה|הוספת/)
})

test('one realtime subscription fans out canonical invalidation to status and history', () => {
  assert.equal((mainAppSource.match(/createCarStatusRealtimeSync\(/g) ?? []).length, 1)
  assert.match(mainAppSource, /refreshFamilyCarData[\s\S]*?setCarDataRefreshVersion/)
  assert.match(mainAppSource, /refreshStatus: refreshFamilyCarData/)
  assert.match(mainAppSource, /carDataRefreshVersion=\{carDataRefreshVersion\}/)
  assert.match(dashboardSource, /refreshVersion=\{carDataRefreshVersion\}/)
  assert.match(historySource, /refreshVersion[\s\S]*?getCarHistory/)
})

test('back returns to the mounted dashboard while all category routes remain dedicated', () => {
  assert.match(historySource, /aria-label="חזרה ללוח הבקרה"/)
  assert.match(dashboardSource, /onBack=\{closeCategory\}/)
  assert.match(dashboardSource, /activeCategory\.id === 'family'/)
  assert.match(dashboardSource, /activeCategory\.id === 'reservations'/)
  assert.match(dashboardSource, /activeCategory\.id === 'history'/)
  assert.match(dashboardSource, /activeCategory\.id === 'cars'/)
  assert.match(dashboardSource, /activeCategory\.id === 'settings'/)
  assert.doesNotMatch(dashboardSource, /CategoryPlaceholderScreen/)
})
