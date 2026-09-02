import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendRemainingAttempts,
  initialCreateValidationAttempts,
  registerCreateValidationFailure,
} from '../src/onboarding/createValidationAttempts.ts'

test('family code failures count down independently to exhaustion', () => {
  const initial = initialCreateValidationAttempts()
  const first = registerCreateValidationFailure(initial, 'familyCode')
  const second = registerCreateValidationFailure(first.attempts, 'familyCode')
  const third = registerCreateValidationFailure(second.attempts, 'familyCode')

  assert.equal(first.remainingAttempts, 2)
  assert.equal(first.exhausted, false)
  assert.equal(second.remainingAttempts, 1)
  assert.equal(second.exhausted, false)
  assert.equal(third.remainingAttempts, 0)
  assert.equal(third.exhausted, true)
})

test('address failures do not consume family code attempts', () => {
  const result = registerCreateValidationFailure(
    initialCreateValidationAttempts(),
    'address',
  )

  assert.deepEqual(result.attempts, { familyCode: 0, address: 1 })
})

test('messages preserve validation text and show the remaining attempts', () => {
  assert.equal(
    appendRemainingAttempts('הקוד אינו תקין.', 2),
    'הקוד אינו תקין. נותרו 2 ניסיונות.',
  )
  assert.equal(
    appendRemainingAttempts('הכתובת לא נמצאה.', 1),
    'הכתובת לא נמצאה. נותר ניסיון אחרון.',
  )
  assert.equal(
    appendRemainingAttempts('הכתובת לא נמצאה.', 0),
    'הכתובת לא נמצאה. לא נותרו ניסיונות. תהליך יצירת המשפחה אופס ואפשר להתחיל מחדש.',
  )
})
