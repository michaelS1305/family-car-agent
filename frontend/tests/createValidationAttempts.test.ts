import assert from 'node:assert/strict'
import test from 'node:test'

import {
  appendRemainingAttempts,
  initialCreateValidationAttempts,
  registerCreateValidationFailure,
} from '../src/onboarding/createValidationAttempts.ts'

test('address failures count down to exhaustion', () => {
  const initial = initialCreateValidationAttempts()
  const first = registerCreateValidationFailure(initial, 'address')
  const second = registerCreateValidationFailure(first.attempts, 'address')
  const third = registerCreateValidationFailure(second.attempts, 'address')

  assert.equal(first.remainingAttempts, 2)
  assert.equal(first.exhausted, false)
  assert.equal(second.remainingAttempts, 1)
  assert.equal(second.exhausted, false)
  assert.equal(third.remainingAttempts, 0)
  assert.equal(third.exhausted, true)
})

test('address failure state contains no obsolete creator code counter', () => {
  const result = registerCreateValidationFailure(
    initialCreateValidationAttempts(),
    'address',
  )

  assert.deepEqual(result.attempts, { address: 1 })
})

test('messages preserve validation text and show the remaining attempts', () => {
  assert.equal(
    appendRemainingAttempts('הכתובת לא נמצאה.', 2),
    'הכתובת לא נמצאה. נותרו 2 ניסיונות.',
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
