import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CHAT_HEADER,
  CHAT_COMPOSER_LAYOUT,
  carStatusPresentation,
  draftAfterFailedSend,
  draftAfterSendStarts,
  formatMessageDayLabel,
  groupMessagesByDay,
  groupMessagesByMinute,
  isNearScrollBottom,
  retryRequestAfterFailure,
  shouldAutoScroll,
  shouldRefreshCarStatus,
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

test('chat header stays centered without a greeting or placeholder car status', () => {
  assert.equal(CHAT_HEADER.title, 'Family Car Agent')
  assert.equal(CHAT_HEADER.menuLines, 3)
  assert.equal('carStatus' in CHAT_HEADER, false)
  assert.equal('greeting' in CHAT_HEADER, false)
})

test('car status maps real, loading, and failed states to accessible Hebrew labels', () => {
  assert.deepEqual(carStatusPresentation('available'), { label: 'פנוי', tone: 'available' })
  assert.deepEqual(carStatusPresentation('occupied'), { label: 'תפוס', tone: 'occupied' })
  assert.deepEqual(carStatusPresentation('loading'), { label: 'בודק…', tone: 'loading' })
  assert.deepEqual(carStatusPresentation('unknown'), { label: 'לא ידוע', tone: 'unknown' })
})

test('foreground car status refresh is visibility-aware and deduplicated', () => {
  assert.equal(shouldRefreshCarStatus({
    isVisible: true,
    now: 5_000,
    lastRefreshAt: 1_000,
  }), true)
  assert.equal(shouldRefreshCarStatus({
    isVisible: true,
    now: 2_000,
    lastRefreshAt: 1_000,
  }), false)
  assert.equal(shouldRefreshCarStatus({
    isVisible: false,
    now: 5_000,
    lastRefreshAt: 1_000,
  }), false)
})

test('composer field and circular send action use separate visual containers', () => {
  assert.equal(CHAT_COMPOSER_LAYOUT.fieldClassName, 'chat-composer-field')
  assert.equal(CHAT_COMPOSER_LAYOUT.sendClassName, 'chat-send-button')
  assert.notEqual(
    CHAT_COMPOSER_LAYOUT.fieldClassName,
    CHAT_COMPOSER_LAYOUT.sendClassName,
  )
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

test('two messages on one local day receive one day separator', () => {
  const morning = new Date(2026, 8, 3, 9, 10, 0)
  const evening = new Date(2026, 8, 3, 18, 40, 0)
  const groups = groupMessagesByDay([
    { created_at: morning.toISOString() },
    { created_at: evening.toISOString() },
  ], new Date(2026, 8, 3, 20, 0, 0))

  assert.equal(groups.length, 1)
  assert.equal(groups[0]?.label, 'היום')
  assert.equal(groups[0]?.minuteGroups.length, 2)
})

test('a local calendar-day transition adds another separator', () => {
  const groups = groupMessagesByDay([
    { created_at: new Date(2026, 8, 2, 23, 59, 30).toISOString() },
    { created_at: new Date(2026, 8, 3, 0, 0, 5).toISOString(), pending: true },
  ], new Date(2026, 8, 3, 12, 0, 0))

  assert.equal(groups.length, 2)
  assert.equal(groups[0]?.label, 'אתמול')
  assert.equal(groups[1]?.label, 'היום')
  assert.equal(groups[1]?.minuteGroups[0]?.messages[0]?.pending, true)
})

test('older dates use a natural Hebrew date while today and yesterday are relative', () => {
  const now = new Date(2026, 8, 3, 12, 0, 0)
  assert.equal(formatMessageDayLabel(new Date(2026, 8, 3, 8), now), 'היום')
  assert.equal(formatMessageDayLabel(new Date(2026, 8, 2, 8), now), 'אתמול')
  assert.match(formatMessageDayLabel(new Date(2026, 7, 28, 8), now), /28.*2026/)
})

test('day grouping preserves same-minute grouping for history and optimistic messages', () => {
  const first = new Date(2026, 8, 3, 12, 15, 3)
  const second = new Date(2026, 8, 3, 12, 15, 48)
  const groups = groupMessagesByDay([
    { created_at: first.toISOString(), role: 'assistant' },
    { created_at: second.toISOString(), role: 'user', pending: true },
  ], new Date(2026, 8, 3, 13))

  assert.equal(groups.length, 1)
  assert.equal(groups[0]?.minuteGroups.length, 1)
  assert.equal(groups[0]?.minuteGroups[0]?.messages.length, 2)
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
