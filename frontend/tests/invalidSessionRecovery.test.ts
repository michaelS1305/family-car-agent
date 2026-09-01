import assert from 'node:assert/strict'
import test from 'node:test'

import { createInvalidSessionRecovery } from '../src/auth/invalidSessionRecovery.ts'

test('invalid auth identity clears old state and signs out only once', async () => {
  const events: string[] = []
  let releaseSignOut: (() => void) | undefined
  const signOutPending = new Promise<void>((resolve) => {
    releaseSignOut = resolve
  })
  const recover = createInvalidSessionRecovery({
    clearOnboardingDraft: () => events.push('clear-draft'),
    clearPendingCreateSuccess: () => events.push('clear-create-success'),
    clearPendingJoinSuccess: () => events.push('clear-join-success'),
    resetOnboardingForLogin: () => events.push('reset-create-intent'),
    invalidateAuthSession: async (message) => {
      assert.equal(
        message,
        'ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.',
      )
      events.push('sign-out-local')
      await signOutPending
    },
  })

  const firstRecovery = recover(
    'ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.',
  )
  const duplicateRecovery = recover(
    'ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.',
  )

  assert.equal(firstRecovery, duplicateRecovery)
  assert.deepEqual(events, [
    'clear-draft',
    'clear-create-success',
    'clear-join-success',
    'reset-create-intent',
    'sign-out-local',
  ])

  releaseSignOut?.()
  await firstRecovery
})

test('recovery can run again after a fresh login without looping', async () => {
  let signOutCount = 0
  const recover = createInvalidSessionRecovery({
    clearOnboardingDraft: () => undefined,
    clearPendingCreateSuccess: () => undefined,
    clearPendingJoinSuccess: () => undefined,
    resetOnboardingForLogin: () => undefined,
    invalidateAuthSession: async () => { signOutCount += 1 },
  })

  await recover('session expired')
  await recover('a later session expired')

  assert.equal(signOutCount, 2)
})
