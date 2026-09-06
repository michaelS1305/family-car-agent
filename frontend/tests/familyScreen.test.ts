import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const familySource = readFileSync(
  new URL('../src/components/FamilyScreen.tsx', import.meta.url),
  'utf8',
)
const dashboardSource = readFileSync(
  new URL('../src/components/DashboardScreen.tsx', import.meta.url),
  'utf8',
)

test('family category opens the real screen while other categories keep the placeholder', () => {
  assert.match(dashboardSource, /activeCategory\.id === 'family'/)
  assert.match(dashboardSource, /<FamilyScreen accessToken=\{accessToken\}/)
  assert.match(dashboardSource, /<CategoryPlaceholderScreen category=\{activeCategory\}/)
})

test('family screen renders real members, address, code and separate admin status', () => {
  assert.match(familySource, /family\.members\.map/)
  assert.match(familySource, /member\.name/)
  assert.match(familySource, /מנהל המשפחה/)
  assert.match(familySource, /family\.home_address/)
  assert.match(familySource, /family\.family_code/)
  assert.doesNotMatch(familySource, /הוסף.*חבר|הוספת.*חבר/)
})

test('role presentation maps exact values and keeps null explicit', () => {
  assert.match(familySource, /parent: 'הורה'/)
  assert.match(familySource, /child: 'ילד\/ילדה'/)
  assert.match(familySource, /member\.role \? <span>\{roleLabel\(member\.role\)\}/)
  assert.match(familySource, /<option value="">ללא תפקיד<\/option>/)
})

test('roles are editable only for family creator and use public member references', () => {
  assert.match(familySource, /family\.can_edit_roles \? \(/)
  assert.match(familySource, /changeRole\(\s*member\.member_ref/)
  assert.doesNotMatch(familySource, /member\.user_id|member\.family_id|auth_user_id|shortcut_token/)
})

test('copy action copies only the family code', () => {
  assert.match(familySource, /navigator\.clipboard\.writeText\(family\.family_code\)/)
  assert.doesNotMatch(familySource, /clipboard\.writeText\(family\.home_address\)/)
})

test('back uses the existing dashboard close path so rotary selection stays mounted', () => {
  assert.match(familySource, /onClick=\{onBack\}/)
  assert.match(dashboardSource, /<div className="dashboard-content" inert=\{categoryOpen\}>/)
  assert.match(dashboardSource, /onBack=\{closeCategory\}/)
})
