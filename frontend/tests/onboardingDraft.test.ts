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

test('OAuth redirect preserves the selected intent and onboarding form', () => {
  const storage = createMemoryStorage()
  saveOnboardingDraft({
    flow: 'join',
    step: 1,
    form: {
      familyName: 'כהן',
      familyCode: '',
      address: 'תל אביב, דיזנגוף, 120',
      userName: '',
      resolvedAddress: '',
      addressResolutionToken: 'opaque-resolution-token',
    },
  }, storage)

  assert.deepEqual(loadOnboardingDraft(storage), {
    flow: 'join',
    step: 1,
    form: {
      familyName: 'כהן',
      familyCode: '',
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
    form: { familyName: '', familyCode: '', address: '', userName: '' },
  }, storage)

  clearOnboardingDraft(storage)
  assert.equal(loadOnboardingDraft(storage), null)
})

test('successful Create marker survives refresh until the user continues', () => {
  const storage = createMemoryStorage()
  const pending = {
    ...successMetadata,
    flow: 'create' as const,
    familyName: 'כהן',
    familyCode: '482731',
    userName: 'מיכאל',
  }

  savePendingCreateSuccess(pending, storage)
  assert.deepEqual(loadPendingCreateSuccess(storage), pending)

  clearPendingCreateSuccess(storage)
  assert.equal(loadPendingCreateSuccess(storage), null)
})

test('Create success cannot be restored from an unverified step-five draft', () => {
  const storage = createMemoryStorage()
  saveOnboardingDraft({
    flow: 'create',
    step: 5,
    form: {
      familyName: 'כהן',
      familyCode: '482731',
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
    form: { familyName: '', familyCode: '', address: '', userName: '' },
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
    { ...successMetadata, flow: 'create', familyName: 'כהן', userName: 'מיכאל' },
    { ...successMetadata, flow: 'create', familyName: 'כהן', familyCode: '123456', userName: '' },
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
    familyCode: '123456',
    userName: 'מיכאל',
  }

  assert.equal(isPendingSuccessForAuthUser(pending, undefined), false)
  assert.equal(isPendingSuccessForAuthUser(pending, 'auth-user-b'), false)
  assert.equal(isPendingSuccessForAuthUser(pending, 'auth-user-a'), true)
})
