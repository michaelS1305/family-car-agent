import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveAppDestination } from '../src/auth/appDestination.ts'
import {
  classifyAuthSessionUpdate,
  wasSessionReadSuperseded,
} from '../src/auth/authSessionTransition.ts'

test('INITIAL_SESSION followed by SIGNED_IN with the same token is idempotent', () => {
  assert.equal(classifyAuthSessionUpdate(undefined, 'token-t'), 'initial_session')
  assert.equal(classifyAuthSessionUpdate('token-t', 'token-t'), 'same_token')
})

test('a late getSession result cannot overwrite a newer auth event', () => {
  const revisionWhenGetSessionStarted = 0
  const revisionAfterSignedInEvent = 1

  assert.equal(
    wasSessionReadSuperseded(
      revisionWhenGetSessionStarted,
      revisionAfterSignedInEvent,
    ),
    true,
  )
})

test('a genuinely new token triggers a new identity check', () => {
  assert.equal(
    classifyAuthSessionUpdate('old-token', 'new-token'),
    'token_changed',
  )
})

test('logout is applied as session removal and repeated logout is a no-op', () => {
  assert.equal(classifyAuthSessionUpdate('token-t', null), 'session_removed')
  assert.equal(classifyAuthSessionUpdate(null, null), 'same_token')
})

test('mapped OAuth return stays mapped after a late same-token event', () => {
  let appliedToken: string | null | undefined
  let identityStatus = 'checking' as const | 'authenticated_mapped'
  let hasCurrentUser = false

  const initialEvent = classifyAuthSessionUpdate(appliedToken, 'token-t')
  if (initialEvent !== 'same_token') {
    appliedToken = 'token-t'
    identityStatus = 'checking'
  }

  // The immediate /api/me response maps the user.
  identityStatus = 'authenticated_mapped'
  hasCurrentUser = true

  // Supabase then emits the delayed SIGNED_IN event with the same token.
  const delayedSignedIn = classifyAuthSessionUpdate(appliedToken, 'token-t')
  if (delayedSignedIn !== 'same_token') {
    identityStatus = 'checking'
    hasCurrentUser = false
  }

  assert.equal(delayedSignedIn, 'same_token')
  assert.equal(resolveAppDestination({
    isInitializing: false,
    identityStatus,
    intent: null,
    hasCurrentUser,
    carPlaySetupStatus: 'completed',
    hasPendingCreateSuccess: false,
    hasPendingJoinSuccess: false,
  }), 'main')
})
