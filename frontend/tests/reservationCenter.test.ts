import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { intervalFromForm, reservationFormValue, reservationPresentation } from '../src/reservationForm.ts'

const screenSource = readFileSync(
  new URL('../src/components/ReservationCenterScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)
const familySource = readFileSync(
  new URL('../src/components/FamilyScreen.tsx', import.meta.url),
  'utf8',
)

test('reservation and family categories remain dedicated screens', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'family'[\s\S]*?<FamilyScreen/)
  assert.match(dashboardSource, /activeCategory\.id === 'reservations'[\s\S]*?<ReservationCenterScreen/)
  assert.doesNotMatch(dashboardSource, /<CategoryPlaceholderScreen/)
  assert.match(familySource, /אנשי המשפחה/)
})

test('header reuses the dashboard calendar icon and approved title', () => {
  assert.match(screenSource, /<DashboardCategoryIcon icon="calendar"/)
  assert.match(screenSource, /<h2>מרכז הזמנות<\/h2>/)
  assert.match(screenSource, /<h1>Family Car Agent<\/h1>/)
})

test('default filters are future and all with accessible selected state', () => {
  assert.match(screenSource, /useState<ReservationTimeFilter>\('future'\)/)
  assert.match(screenSource, /useState<ReservationScopeFilter>\('all'\)/)
  assert.match(screenSource, /aria-pressed=\{timeFilter === 'future'\}/)
  assert.match(screenSource, /aria-pressed=\{scopeFilter === 'all'\}/)
})

test('actual API reservations render safe owner and interval fields', () => {
  assert.match(screenSource, /getReservations\(accessToken, timeFilter, scopeFilter/)
  assert.match(screenSource, /reservation\.owner_name/)
  assert.match(screenSource, /reservation\.start_time/)
  assert.match(screenSource, /reservation\.end_time/)
  assert.match(screenSource, /reservation\.is_mine \? 'ההזמנה שלי'/)
  assert.doesNotMatch(screenSource, /reservation\.reservation_id|reservation\.user_id|reservation\.family_id/)
})

test('edit and delete are shown only for own future reservations', () => {
  assert.match(screenSource, /const canModify = timeFilter === 'future' && reservation\.is_mine/)
  assert.match(screenSource, /\{canModify \? \(/)
  assert.match(screenSource, /עריכה/)
  assert.match(screenSource, /מחיקה/)
})

test('creation and edit share one form and mutations refresh the canonical list', () => {
  assert.equal((screenSource.match(/function ReservationForm/g) ?? []).length, 1)
  assert.match(screenSource, /editor\.mode === 'create'/)
  assert.match(screenSource, /createReservation\(accessToken, interval\)/)
  assert.match(screenSource, /updateReservation\(accessToken/)
  assert.match(screenSource, /setReloadAttempt\(\(value\) => value \+ 1\)/)
  assert.match(screenSource, /הוספת הזמנה/)
})

test('delete requires explicit confirmation and uses canonical cancellation API', () => {
  assert.match(screenSource, /setConfirmingKey\(key\)/)
  assert.match(screenSource, /כן, למחוק/)
  assert.match(screenSource, /cancelReservation\(accessToken/)
})

test('nested back and Escape return to the center before Dashboard', () => {
  assert.match(screenSource, /const screenBack = editor\.mode === 'list' \? onBack : closeEditor/)
  assert.match(screenSource, /event\.stopImmediatePropagation\(\)/)
  assert.match(screenSource, /setEditor\(\{ mode: 'list' \}\)/)
})

test('contextual empty and error states remain concise', () => {
  assert.match(screenSource, /אין לך הזמנות עתידיות/)
  assert.match(screenSource, /אין הזמנות עתידיות/)
  assert.match(screenSource, /role="alert"/)
  assert.match(screenSource, /נסו שוב/)
})

test('multi-day create and edit retain independent dates and seconds', () => {
  const interval = { start_time: '2030-09-10T18:00:12', end_time: '2030-09-12T14:00:34' }
  const form = reservationFormValue(interval)
  assert.equal(form.startDate, '2030-09-10')
  assert.equal(form.endDate, '2030-09-12')
  assert.deepEqual(intervalFromForm(form), interval)
  assert.deepEqual(intervalFromForm({ startDate: '2030-09-10', startTime: '18:00', endDate: '2030-09-12', endTime: '14:00' }),
    { start_time: '2030-09-10T18:00:00', end_time: '2030-09-12T14:00:00' })
})

test('same-day display is compact and multi-day display includes both dates', () => {
  const same = reservationPresentation({ start_time: '2030-09-10T18:00:00', end_time: '2030-09-10T19:00:00' })
  assert.equal(same.sameDay, true)
  assert.equal(same.interval, '18:00–19:00')
  const multi = reservationPresentation({ start_time: '2030-09-10T18:00:00', end_time: '2030-09-12T14:00:00' })
  assert.equal(multi.sameDay, false)
  for (const value of ['10', '12', '18:00', '14:00']) assert.ok(multi.interval.includes(value))
})

test('form groups reflow and original update locator stays untouched', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  assert.match(screenSource, /<legend>התחלה<\/legend>/)
  assert.match(screenSource, /<legend>סיום<\/legend>/)
  assert.match(screenSource, /value=\{form.startDate\}/)
  assert.match(screenSource, /value=\{form.endDate\}/)
  assert.match(screenSource, /start_time: editor.reservation.start_time/)
  assert.match(screenSource, /end_time: editor.reservation.end_time/)
  assert.doesNotMatch(css, /@container reservation-form/)
  assert.match(css, /\.reservation-editor label\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);[^}]*min-width: 0;[^}]*max-inline-size: 100%;/)
  assert.match(css, /\.reservation-time-fields\s*\{[^}]*grid-template-columns: minmax\(0, 1fr\);[^}]*gap: 10px;/)
  assert.match(css, /\.reservation-editor input\s*\{[^}]*min-width: 0;[^}]*max-width: 100%;/)
})

test('vertical date and time controls retain visible labels and accessible names', () => {
  for (const name of ['תאריך התחלה', 'שעת התחלה', 'תאריך סיום', 'שעת סיום']) {
    assert.ok(screenSource.includes(`aria-label="${name}"`))
  }
  assert.deepEqual([...screenSource.matchAll(/<span>(תאריך|משעה|עד שעה)<\/span>/g)].map((match) => match[1]),
    ['תאריך', 'משעה', 'תאריך', 'עד שעה'])
  assert.equal((screenSource.match(/type="date"/g) ?? []).length, 2)
  assert.equal((screenSource.match(/type="time"/g) ?? []).length, 2)
  assert.equal((screenSource.match(/className="reservation-time-fields"/g) ?? []).length, 2)
})

test('native date/time border boxes stretch without percentage-width sizing', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  const rule = css.match(/\.reservation-editor input:is\(\[type="date"\], \[type="time"\]\)\s*\{([^}]+)\}/)?.[1]
  assert.ok(rule)
  for (const declaration of ['box-sizing: border-box;', 'width: auto;', 'inline-size: auto;',
    'min-width: 0;', 'min-inline-size: 0;', 'max-width: 100%;', 'max-inline-size: 100%;',
    'justify-self: stretch;']) assert.ok(rule.includes(declaration))
  assert.doesNotMatch(rule, /overflow:|transform:|position:|margin:|height:|padding:/)
})
