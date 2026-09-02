import assert from 'node:assert/strict'
import test from 'node:test'
import { OnboardingApiError } from '../src/api/apiClient.ts'
import { createCreateFamilySubmitter } from '../src/onboarding/createFamilySubmission.ts'

const payload = {
  family_name: 'כהן',
  family_code: '482731',
  address_resolution_token: 'opaque-resolution-token',
  user_name: 'מיכאל',
}

test('successful create marks completion and rechecks /api/me without clearing early', async () => {
  const events: string[] = []
  const submit = createCreateFamilySubmitter({
    createRequest: async () => {
      events.push('create')
      return { created: true }
    },
    clearDraft: () => events.push('clear'),
    markCreated: () => events.push('mark-created'),
    recheckIdentity: () => events.push('recheck'),
  })

  const result = await submit('token', payload)

  assert.deepEqual(result, { status: 'created' })
  assert.deepEqual(events, ['create', 'mark-created', 'recheck'])
})

test('double submit issues only one backend request', async () => {
  let releaseRequest: (() => void) | undefined
  let requestCount = 0
  const pendingRequest = new Promise<void>((resolve) => {
    releaseRequest = resolve
  })
  const submit = createCreateFamilySubmitter({
    createRequest: async () => {
      requestCount += 1
      await pendingRequest
      return { created: true }
    },
    clearDraft: () => undefined,
    markCreated: () => undefined,
    recheckIdentity: () => undefined,
  })

  const first = submit('token', payload)
  const second = await submit('token', payload)
  assert.deepEqual(second, { status: 'ignored' })
  assert.equal(requestCount, 1)

  releaseRequest?.()
  await first
})

test('recoverable failure preserves the draft and does not recheck identity', async () => {
  let cleared = false
  let markedCreated = false
  let rechecked = false
  const submit = createCreateFamilySubmitter({
    createRequest: async () => {
      throw new OnboardingApiError('FAMILY_CODE_TAKEN', 'taken', 409)
    },
    clearDraft: () => { cleared = true },
    markCreated: () => { markedCreated = true },
    recheckIdentity: () => { rechecked = true },
  })

  await assert.rejects(submit('token', payload), OnboardingApiError)
  assert.equal(cleared, false)
  assert.equal(markedCreated, false)
  assert.equal(rechecked, false)
})

test('already-mapped retry is idempotent and moves to identity recheck', async () => {
  let cleared = false
  let rechecked = false
  const submit = createCreateFamilySubmitter({
    createRequest: async () => {
      throw new OnboardingApiError(
        'AUTH_USER_ALREADY_MAPPED',
        'already mapped',
        409,
      )
    },
    clearDraft: () => { cleared = true },
    markCreated: () => undefined,
    recheckIdentity: () => { rechecked = true },
  })

  const result = await submit('token', payload)

  assert.deepEqual(result, { status: 'already-mapped' })
  assert.equal(cleared, true)
  assert.equal(rechecked, true)
})

test('submitter created before OAuth uses the latest identity recheck callback', async () => {
  let session: string | null = null
  let staleRecheckCount = 0
  let currentRecheckCount = 0
  let apiMeRefreshCount = 0
  const retryIdentityRef = {
    current: () => { staleRecheckCount += 1 },
  }
  const submit = createCreateFamilySubmitter({
    createRequest: async () => ({ created: true }),
    clearDraft: () => undefined,
    markCreated: () => undefined,
    recheckIdentity: () => retryIdentityRef.current(),
  })

  session = 'oauth-session'
  retryIdentityRef.current = () => {
    assert.equal(session, 'oauth-session')
    currentRecheckCount += 1
    apiMeRefreshCount += 1
  }

  const result = await submit('access-token', payload)

  assert.deepEqual(result, { status: 'created' })
  assert.equal(staleRecheckCount, 0)
  assert.equal(currentRecheckCount, 1)
  assert.equal(apiMeRefreshCount, 1)
})
