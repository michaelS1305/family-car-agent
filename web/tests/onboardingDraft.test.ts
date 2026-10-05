import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearOnboardingDraft,
  clearPendingCreateSuccess,
  clearPendingJoinSuccess,
  loadOnboardingDraft,
  loadPendingCreateSuccess,
  loadPendingJoinSuccess,
  isPendingSuccessForAuthUser,
  saveOnboardingDraft,
  savePendingCreateSuccess,
  savePendingJoinSuccess,
} from '../src/auth/onboardingDraft.ts'

function createMemoryStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    removeItem: (key: string) => { values.delete(key) },
  }
}

const successMetadata = {
  version: 1 as const,
  authUserId: 'auth-user-a',
  createdAt: '2026-09-01T10:00:00.000Z',
}

test('Join draft preserves and restores its family code', () => {
  const storage = createMemoryStorage()
  saveOnboardingDraft({
    flow: 'join',
    step: 3,
    form: {
      familyName: 'כהן',
      familyCode: 'k7m2q9',
      address: 'תל אביב, דיזנגוף, 120',
      userName: '',
      resolvedAddress: '',
      addressResolutionToken: 'opaque-resolution-token',
    },
  }, storage)

  assert.deepEqual(loadOnboardingDraft(storage), {
    flow: 'join',
    step: 3,
    form: {
      familyName: 'כהן',
      familyCode: 'k7m2q9',
      address: 'תל אביב, דיזנגוף, 120',
      userName: '',
      resolvedAddress: '',
      addressResolutionToken: 'opaque-resolution-token',
    },
  })
})

test('draft is removed only when onboarding is explicitly cleared', () => {
  const storage = createMemoryStorage()
  saveOnboardingDraft({
    flow: 'create',
    step: 0,
    form: { familyName: '', address: '', userName: '' },
  }, storage)

  clearOnboardingDraft(storage)
  assert.equal(loadOnboardingDraft(storage), null)
})

test('Create draft saves and restores without a familyCode field', () => {
  const storage = createMemoryStorage()
  const draft = {
    flow: 'create' as const,
    step: 2,
    form: {
      familyName: 'כהן',
      address: 'תל אביב, דיזנגוף, 120',
      resolvedAddress: 'דיזנגוף 120, תל אביב, ישראל',
      addressResolutionToken: 'opaque-resolution-token',
      userName: '',
    },
    createAttempts: { address: 0 },
  }

  saveOnboardingDraft(draft, storage)

  const stored = JSON.parse(String(
    storage.getItem('family-car-agent:onboarding-draft'),
  )) as { form: Record<string, unknown> }
  assert.equal(Object.hasOwn(stored.form, 'familyCode'), false)
  assert.deepEqual(loadOnboardingDraft(storage), draft)
})

test('legacy Create draft familyCode is discarded during restore', () => {
  const storage = createMemoryStorage()
  storage.setItem('family-car-agent:onboarding-draft', JSON.stringify({
    flow: 'create',
    step: 1,
    form: {
      familyName: 'כהן',
      familyCode: '482731',
      address: 'תל אביב, דיזנגוף, 120',
      userName: '',
    },
  }))

  const restored = loadOnboardingDraft(storage)
  assert.equal(restored?.flow, 'create')
  assert.equal(Object.hasOwn(restored?.form ?? {}, 'familyCode'), false)
})

test('successful Create marker survives refresh until the user continues', () => {
  const storage = createMemoryStorage()
  const pending = {
    ...successMetadata,
    flow: 'create' as const,
    familyName: 'כהן',
    userName: 'מיכאל',
  }

  savePendingCreateSuccess(pending, storage)
  assert.deepEqual(loadPendingCreateSuccess(storage), pending)

  clearPendingCreateSuccess(storage)
  assert.equal(loadPendingCreateSuccess(storage), null)
})

test('Create drafts reject the removed fifth step', () => {
  const storage = createMemoryStorage()
  saveOnboardingDraft({
    flow: 'create',
    step: 4,
    form: {
      familyName: 'כהן',
      address: 'תל אביב, דיזנגוף, 120',
      userName: 'מיכאל',
    },
  }, storage)

  assert.equal(loadOnboardingDraft(storage), null)
})

test('successful Join marker survives refresh until the user continues', () => {
  const storage = createMemoryStorage()
  const pending = { familyName: 'כהן', userName: 'מיכאל' }
  const validPending = { ...successMetadata, flow: 'join' as const, ...pending }

  savePendingJoinSuccess(validPending, storage)
  assert.deepEqual(loadPendingJoinSuccess(storage), validPending)

  clearPendingJoinSuccess(storage)
  assert.equal(loadPendingJoinSuccess(storage), null)
})

test('malformed JSON and invalid legacy drafts are removed safely', () => {
  const storage = createMemoryStorage()
  storage.setItem('family-car-agent:onboarding-draft', '{not-json')
  assert.equal(loadOnboardingDraft(storage), null)
  assert.equal(storage.getItem('family-car-agent:onboarding-draft'), null)

  storage.setItem('family-car-agent:onboarding-draft', JSON.stringify({
    flow: 'create',
    step: 99,
    form: { familyName: '', address: '', userName: '' },
  }))
  assert.equal(loadOnboardingDraft(storage), null)
  assert.equal(storage.getItem('family-car-agent:onboarding-draft'), null)

  storage.setItem('family-car-agent:onboarding-draft', JSON.stringify({
    flow: 'join',
    step: 6,
    form: { familyName: 'כהן', familyCode: '', address: '', userName: '' },
  }))
  assert.equal(loadOnboardingDraft(storage), null)
  assert.equal(storage.getItem('family-car-agent:onboarding-draft'), null)

  storage.setItem('family-car-agent:pending-join-success', '{not-json')
  assert.equal(loadPendingJoinSuccess(storage), null)
  assert.equal(storage.getItem('family-car-agent:pending-join-success'), null)
})

test('success markers require complete versioned data for their own flow', () => {
  const storage = createMemoryStorage()
  const key = 'family-car-agent:pending-create-success'

  for (const invalid of [
    { familyName: 'כהן', familyCode: '123456', userName: 'מיכאל' },
    { ...successMetadata, flow: 'join', familyName: 'כהן', familyCode: '123456', userName: 'מיכאל' },
    { ...successMetadata, flow: 'create', familyName: 'כהן', userName: '' },
  ]) {
    storage.setItem(key, JSON.stringify(invalid))
    assert.equal(loadPendingCreateSuccess(storage), null)
    assert.equal(storage.getItem(key), null)
  }
})

test('success marker is valid only for the active Supabase identity', () => {
  const pending = {
    ...successMetadata,
    flow: 'create' as const,
    familyName: 'כהן',
    userName: 'מיכאל',
  }

  assert.equal(isPendingSuccessForAuthUser(pending, undefined), false)
  assert.equal(isPendingSuccessForAuthUser(pending, 'auth-user-b'), false)
  assert.equal(isPendingSuccessForAuthUser(pending, 'auth-user-a'), true)
})
