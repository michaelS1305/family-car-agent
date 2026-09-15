import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const auth = readFileSync(new URL('../src/components/AuthGate.tsx', import.meta.url), 'utf8')
const legal = readFileSync(new URL('../src/legal/legalDocuments.ts', import.meta.url), 'utf8')

test('privacy and terms are accessible before authentication without generic consent', () => {
  assert.match(auth, /onOpenPrivacy/)
  assert.match(auth, /onOpenTerms/)
  assert.match(app, /<LegalDocumentScreen kind=\{publicLegalDocument\}/)
  assert.doesNotMatch(auth, /type="checkbox"|מסכים להכול/)
})

test('address collection gives the contextual Google Maps and geofence notice', () => {
  assert.ok((app.match(/יש להזין את הכתובת כפי שהיא מופיעה ב-Google Maps/g) ?? []).length >= 2)
  assert.match(app, /אימות המשפחה/)
  assert.match(app, /ניתוק אופציונלית/)
  assert.ok((app.match(/maxLength=\{200\}/g) ?? []).length >= 2)
})

test('driver eligibility is explicit at both irreversible create and join boundaries without DOB', () => {
  assert.ok((app.match(/<DriverEligibilityDeclaration/g) ?? []).length >= 2)
  assert.match(app, /step === \(flow === 'create' \? 3 : 4\) && !eligibilityAccepted/)
  assert.match(app, /16 שנים ו־9 חודשים/)
  assert.match(app, /אינה בודקת תוקף רישיון/)
  assert.doesNotMatch(app, /dateOfBirth|birth_date|תאריך לידה/)
})

test('Create has four steps and no creator-controlled family code UI', () => {
  assert.match(app, /totalSteps=\{flow === 'create' \? 4 : 5\}/)
  assert.doesNotMatch(app, /title="בחר קוד משפחה"/)
  assert.doesNotMatch(app, /payload\.family_code/)
  assert.match(app, /placeholder="k7m2q9"/)
  assert.match(app, /\^\[a-z0-9\]\{6\}\$/)
})

test('central legal documents expose metadata and avoid unsupported privacy promises', () => {
  assert.match(legal, /version:/)
  assert.match(legal, /lastUpdated:/)
  assert.match(legal, /מפעיל Family Car Agent/)
  assert.match(legal, /Google Maps/)
  assert.match(legal, /Gemini/)
  assert.doesNotMatch(legal, /אין לנו אחריות|אף פעם לא נשמר|לא משמש.*שיפור/)
})
