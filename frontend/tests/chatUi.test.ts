import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CHAT_HEADER,
  draftAfterFailedSend,
  draftAfterSendStarts,
  groupMessagesByMinute,
  isNearScrollBottom,
  retryRequestAfterFailure,
  shouldAutoScroll,
  shouldSubmitComposerKey,
} from '../src/chat/chatUi.ts'

test('composer clears immediately for a new send but preserves an unrelated draft', () => {
  assert.equal(draftAfterSendStarts('אותה הודעה', 'אותה הודעה'), '')
  assert.equal(draftAfterSendStarts('  אותה הודעה  ', 'אותה הודעה'), '')
  assert.equal(draftAfterSendStarts('טיוטה חדשה', 'הודעה קודמת'), 'טיוטה חדשה')
})

test('a new draft survives failure of an earlier request', () => {
  assert.equal(draftAfterFailedSend('הודעה חדשה'), 'הודעה חדשה')
})

test('retry preserves the original logical request id', () => {
  const request = { requestId: 'original-request', message: 'מי עם הרכב?' }
  assert.equal(retryRequestAfterFailure(request, true), request)
  assert.equal(retryRequestAfterFailure(request, false), undefined)
})

test('chat header has no greeting and exposes a textual placeholder status', () => {
  assert.equal(CHAT_HEADER.title, 'Family Car Agent')
  assert.equal(CHAT_HEADER.menuLines, 3)
  assert.equal(CHAT_HEADER.carStatus.label, 'מצב לא זמין')
  assert.equal('greeting' in CHAT_HEADER, false)
})

test('messages in the same minute share one local time group', () => {
  const groups = groupMessagesByMinute([
    { role: 'user', created_at: '2026-09-03T11:31:02.000Z' },
    { role: 'assistant', created_at: '2026-09-03T11:31:25.000Z' },
    { role: 'user', created_at: '2026-09-03T11:31:54.000Z', pending: true },
  ])
  assert.equal(groups.length, 1)
  assert.equal(groups[0]?.messages.length, 3)
  assert.match(groups[0]?.label ?? '', /^\d{2}:\d{2}$/)
})

test('a minute change creates a second timestamp group', () => {
  const groups = groupMessagesByMinute([
    { created_at: '2026-09-03T11:31:54.000Z' },
    { created_at: '2026-09-03T11:32:00.000Z' },
  ])
  assert.equal(groups.length, 2)
  assert.notEqual(groups[0]?.label, groups[1]?.label)
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
