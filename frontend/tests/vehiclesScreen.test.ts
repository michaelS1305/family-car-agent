import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const vehiclesSource = readFileSync(
  new URL('../src/components/VehiclesScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)

test('vehicles category opens a dedicated screen using the existing car icon', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'cars'/)
  assert.match(dashboardSource, /<VehiclesScreen/)
  assert.match(vehiclesSource, /<h1>Family Car Agent<\/h1>/)
  assert.match(vehiclesSource, /<DashboardCategoryIcon icon="car"/)
  assert.match(vehiclesSource, /<h2>רכבים<\/h2>/)
})

test('screen shows only the approved restrained development message', () => {
  assert.match(vehiclesSource, />בפיתוח<\/h3>/)
  assert.match(vehiclesSource, /הפיצ׳ר הזה כרגע עוד נמצא בפיתוח,/)
  assert.match(vehiclesSource, /ויש עוד למה לחכות\./)
  assert.doesNotMatch(vehiclesSource, /לוחית|קילומטר|טיפול|ביטוח|טסט|דלק|מיקום|הוצאות|נהג|התראה/)
  assert.doesNotMatch(vehiclesSource, /הוספת רכב|עריכת רכב|מחיקת רכב/)
})

test('screen adds no bottom navigation and back returns to the mounted dashboard', () => {
  assert.doesNotMatch(vehiclesSource, /bottom-nav|navigation|Chat tab|Dashboard tab/)
  assert.match(vehiclesSource, /aria-label="חזרה ללוח הבקרה"/)
  assert.match(vehiclesSource, /onClick=\{onBack\}/)
  assert.match(dashboardSource, /<div className="dashboard-content" inert=\{categoryOpen\}>/)
  assert.match(dashboardSource, /<VehiclesScreen open=\{categoryOpen\} onBack=\{closeCategory\}/)
  assert.match(dashboardSource, /confirmButtonRef\.current\?\.focus/)
})

test('family, reservations, history and vehicles are dedicated while settings remains generic', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'family'/)
  assert.match(dashboardSource, /activeCategory\.id === 'reservations'/)
  assert.match(dashboardSource, /activeCategory\.id === 'history'/)
  assert.match(dashboardSource, /activeCategory\.id === 'cars'/)
  assert.match(dashboardSource, /<CategoryPlaceholderScreen category=\{activeCategory\}/)
})
