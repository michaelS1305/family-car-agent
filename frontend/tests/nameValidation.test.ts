import assert from 'node:assert/strict'
import test from 'node:test'

import { isValidHumanName, normalizeHumanName } from '../src/onboarding/nameValidation.ts'

test('numeric and alphanumeric names are rejected', () => {
  assert.equal(isValidHumanName('111'), false)
  assert.equal(isValidHumanName('Michael1'), false)
})

test('ordinary Hebrew and English names are accepted', () => {
  assert.equal(isValidHumanName('מיכאל כהן'), true)
  assert.equal(isValidHumanName('Michael Cohen'), true)
})

test('sensible spaces, hyphens, and apostrophes remain valid', () => {
  assert.equal(isValidHumanName('בן-דוד'), true)
  assert.equal(isValidHumanName("O'Connor"), true)
  assert.equal(isValidHumanName('D’Angelo'), true)
  assert.equal(isValidHumanName("סנדרוביץ'"), true)
  assert.equal(isValidHumanName('סנדרוביץ׳'), true)
  assert.equal(isValidHumanName('סנדרוביץ’'), true)
  assert.equal(isValidHumanName('Smith‐Jones'), true)
  assert.equal(isValidHumanName('Smith‑Jones'), true)
  assert.equal(normalizeHumanName('  Michael   Cohen  '), 'Michael Cohen')
  assert.equal(normalizeHumanName('סנדרוביץ׳'), "סנדרוביץ'")
  assert.equal(normalizeHumanName('סנדרוביץ’'), "סנדרוביץ'")
  assert.equal(normalizeHumanName('Smith‑Jones'), 'Smith-Jones')
  assert.equal(normalizeHumanName('Smith—Jones'), 'Smith-Jones')
  assert.equal(normalizeHumanName('  משפחת   O’Connor  '), "משפחת O'Connor")
})

test('NFC normalization makes visually identical names canonical', () => {
  const decomposed = 'José'.normalize('NFD')

  assert.equal(normalizeHumanName(decomposed), 'José')
  assert.equal(isValidHumanName(decomposed), true)
})

test('leading, trailing, or repeated separators are rejected', () => {
  assert.equal(isValidHumanName('-כהן'), false)
  assert.equal(isValidHumanName('כהן-'), false)
  assert.equal(isValidHumanName('Michael--Cohen'), false)
  assert.equal(isValidHumanName("Michael''Cohen"), false)
  assert.equal(isValidHumanName("'"), false)
  assert.equal(isValidHumanName('׳'), false)
})
