import assert from 'node:assert/strict'
import test from 'node:test'

import {
  draftAfterFailedSend,
  draftAfterSuccessfulSend,
  isNearScrollBottom,
  retryRequestAfterFailure,
  shouldAutoScroll,
  shouldSubmitComposerKey,
} from '../src/chat/chatUi.ts'

test('a new draft survives success of an earlier request', () => {
  assert.equal(
    draftAfterSuccessfulSend('הודעה חדשה', 'הודעה קודמת'),
    'הודעה חדשה',
  )
  assert.equal(draftAfterSuccessfulSend('אותה הודעה', 'אותה הודעה'), '')
})

test('a new draft survives failure of an earlier request', () => {
  assert.equal(draftAfterFailedSend('הודעה חדשה'), 'הודעה חדשה')
})

test('retry preserves the original logical request id', () => {
  const request = { requestId: 'original-request', message: 'מי עם הרכב?' }
  assert.equal(retryRequestAfterFailure(request, true), request)
  assert.equal(retryRequestAfterFailure(request, false), undefined)
})

test('Enter sends while Shift+Enter and composition do not', () => {
  assert.equal(shouldSubmitComposerKey({
    key: 'Enter',
    shiftKey: false,
    isComposing: false,
  }), true)
  assert.equal(shouldSubmitComposerKey({
    key: 'Enter',
    shiftKey: true,
    isComposing: false,
  }), false)
  assert.equal(shouldSubmitComposerKey({
    key: 'Enter',
    shiftKey: false,
    isComposing: true,
  }), false)
})

test('near-bottom detection uses a small readable threshold', () => {
  assert.equal(isNearScrollBottom({
    scrollHeight: 1_000,
    scrollTop: 620,
    clientHeight: 300,
  }), true)
  assert.equal(isNearScrollBottom({
    scrollHeight: 1_000,
    scrollTop: 400,
    clientHeight: 300,
  }), false)
})

test('auto-scroll follows initial load and user sends but respects reading position', () => {
  assert.equal(shouldAutoScroll('initial', false), true)
  assert.equal(shouldAutoScroll('user-send', false), true)
  assert.equal(shouldAutoScroll('assistant-response', true), true)
  assert.equal(shouldAutoScroll('assistant-response', false), false)
  assert.equal(shouldAutoScroll('loading', true), false)
})
