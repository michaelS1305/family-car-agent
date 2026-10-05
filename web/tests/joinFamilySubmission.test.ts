import assert from 'node:assert/strict'
import test from 'node:test'

import { OnboardingApiError } from '../src/api/apiClient.ts'
import { createJoinFamilyCompleter } from '../src/onboarding/joinFamilySubmission.ts'

test('successful Join clears the draft and rechecks /api/me', async () => {
  const events: string[] = []
  const complete = createJoinFamilyCompleter({
    completeRequest: async () => {
      events.push('request')
      return { created: true }
    },
    markJoined: () => events.push('mark'),
    clearDraft: () => events.push('clear'),
    recheckIdentity: () => events.push('recheck'),
  })

  const result = await complete('token', 'מיכאל', 'כהן')

  assert.equal(result.status, 'joined')
  assert.deepEqual(events, ['request', 'mark', 'clear', 'recheck'])
})

test('recoverable Join failure preserves the draft', async () => {
  let cleared = false
  let rechecked = false
  const complete = createJoinFamilyCompleter({
    completeRequest: async () => {
      throw new OnboardingApiError('NETWORK_ERROR', 'network error')
    },
    markJoined: () => undefined,
    clearDraft: () => { cleared = true },
    recheckIdentity: () => { rechecked = true },
  })

  await assert.rejects(complete('token', 'מיכאל', 'כהן'), OnboardingApiError)
  assert.equal(cleared, false)
  assert.equal(rechecked, false)
})

test('already-mapped Join retry is idempotent', async () => {
  const events: string[] = []
  const complete = createJoinFamilyCompleter({
    completeRequest: async () => {
      throw new OnboardingApiError(
        'AUTH_USER_ALREADY_MAPPED',
        'already mapped',
        409,
      )
    },
    markJoined: () => events.push('mark'),
    clearDraft: () => events.push('clear'),
    recheckIdentity: () => events.push('recheck'),
  })

  const result = await complete('token', 'מיכאל', 'כהן')

  assert.equal(result.status, 'already-mapped')
  assert.deepEqual(events, ['mark', 'clear', 'recheck'])
})

test('Join completer created before OAuth uses the latest identity recheck callback', async () => {
  let session: string | null = null
  let staleRecheckCount = 0
  let currentRecheckCount = 0
  let apiMeRefreshCount = 0
  const retryIdentityRef = {
    current: () => { staleRecheckCount += 1 },
  }
  const complete = createJoinFamilyCompleter({
    completeRequest: async () => ({ joined: true }),
    clearDraft: () => undefined,
    markJoined: () => undefined,
    recheckIdentity: () => retryIdentityRef.current(),
  })

  session = 'oauth-session'
  retryIdentityRef.current = () => {
    assert.equal(session, 'oauth-session')
    currentRecheckCount += 1
    apiMeRefreshCount += 1
  }

  const result = await complete('access-token', 'מיכאל', 'כהן')

  assert.deepEqual(result, { status: 'joined' })
  assert.equal(staleRecheckCount, 0)
  assert.equal(currentRecheckCount, 1)
  assert.equal(apiMeRefreshCount, 1)
})
