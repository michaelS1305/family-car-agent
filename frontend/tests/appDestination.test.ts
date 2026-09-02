import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveAppDestination } from '../src/auth/appDestination.ts'

test('fresh visitor sees Welcome before Auth', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'unauthenticated',
    intent: null,
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'welcome')
})

test('selected Create or Join intent opens Auth for an unauthenticated user', () => {
  for (const intent of ['create', 'join'] as const) {
    assert.equal(resolveAppDestination({
      isInitializing: false,
      identityStatus: 'unauthenticated',
      intent,
      hasCurrentUser: false,
      hasPendingCreateSuccess: false,
      hasPendingJoinSuccess: false,
    }), 'auth')
  }
})

test('unmapped account continues the selected onboarding flow', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_unmapped',
    intent: 'join',
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'onboarding')
})

test('unmapped account without a saved intent returns to Welcome', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_unmapped',
    intent: null,
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'welcome')
})

test('mapped account skips Welcome, Auth, and onboarding', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: 'join',
    hasCurrentUser: true,
    carPlaySetupStatus: 'completed',
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'main')
})

test('identity initialization never flashes Welcome', () => {
  assert.equal(resolveAppDestination({
    isInitializing: true,
    identityStatus: 'unauthenticated',
    intent: null,
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'loading')
})

test('successful Create waits for mapped identity before showing success', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_unmapped',
    intent: 'create',
    hasCurrentUser: false,
    hasPendingCreateSuccess: true,
    hasPendingJoinSuccess: false,
  }), 'create_processing')

  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: 'create',
    hasCurrentUser: true,
    carPlaySetupStatus: 'pending',
    hasPendingCreateSuccess: true,
    hasPendingJoinSuccess: false,
  }), 'create_success')
})

test('mapped identity enters the app after Create success is acknowledged', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: null,
    hasCurrentUser: true,
    carPlaySetupStatus: 'completed',
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'main')
})

test('successful Join waits for mapped identity before showing success', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_unmapped',
    intent: 'join',
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: true,
  }), 'join_processing')

  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: 'join',
    hasCurrentUser: true,
    carPlaySetupStatus: 'pending',
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: true,
  }), 'join_success')
})

test('mapped identity enters the app after Join success is acknowledged', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: null,
    hasCurrentUser: true,
    carPlaySetupStatus: 'skipped',
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'main')
})

test('final submit immediately replaces onboarding with the matching processing screen', () => {
  for (const flow of ['create', 'join'] as const) {
    assert.equal(resolveAppDestination({
      isInitializing: false,
      identityStatus: 'authenticated_unmapped',
      intent: flow,
      hasCurrentUser: false,
      hasPendingCreateSuccess: false,
      hasPendingJoinSuccess: false,
      finalProcessingFlow: flow,
    }), `${flow}_processing`)
  }
})

test('processing stays visible during the backend identity refresh', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'checking',
    intent: 'join',
    hasCurrentUser: false,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: true,
  }), 'join_processing')
})

test('real identity errors replace processing and mapped identity shows success', () => {
  const input = {
    isInitializing: false,
    intent: 'join' as const,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: true,
    finalProcessingFlow: 'join' as const,
  }

  assert.equal(resolveAppDestination({
    ...input,
    identityStatus: 'error',
    hasCurrentUser: false,
  }), 'error')
  assert.equal(resolveAppDestination({
    ...input,
    identityStatus: 'authenticated_mapped',
    hasCurrentUser: true,
    carPlaySetupStatus: 'pending',
  }), 'join_success')
})

test('mapped users are routed by the server-side CarPlay setup status', () => {
  const baseInput = {
    isInitializing: false,
    identityStatus: 'authenticated_mapped' as const,
    intent: null,
    hasCurrentUser: true,
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }

  assert.equal(resolveAppDestination({
    ...baseInput,
    carPlaySetupStatus: 'pending',
  }), 'carplay_setup')
  assert.equal(resolveAppDestination({
    ...baseInput,
    carPlaySetupStatus: 'completed',
  }), 'main')
  assert.equal(resolveAppDestination({
    ...baseInput,
    carPlaySetupStatus: 'skipped',
  }), 'main')
})

test('onboarding success markers take priority over pending CarPlay setup', () => {
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus: 'authenticated_mapped',
    intent: 'create',
    hasCurrentUser: true,
    carPlaySetupStatus: 'pending',
    hasPendingCreateSuccess: true,
    hasPendingJoinSuccess: false,
  }), 'create_success')
})

test('a stale onboarding intent cannot override completed or skipped server status', () => {
  for (const carPlaySetupStatus of ['completed', 'skipped'] as const) {
    assert.equal(resolveAppDestination({
      isInitializing: false,
      identityStatus: 'authenticated_mapped',
      intent: 'join',
      hasCurrentUser: true,
      carPlaySetupStatus,
      hasPendingCreateSuccess: false,
      hasPendingJoinSuccess: false,
    }), 'main')
  }
})
