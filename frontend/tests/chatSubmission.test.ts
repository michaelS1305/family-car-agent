import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createChatRequestRunner,
  pendingRequestNeedsRetry,
} from '../src/chat/chatSubmission.ts'

const response = {
  request_id: 'request-1',
  status: 'completed' as const,
  assistant_message: {
    role: 'assistant' as const,
    content: 'תשובה',
    created_at: '2026-09-02T12:00:00+00:00',
  },
}

test('submission reports pending then success', async () => {
  const events: string[] = []
  const runner = createChatRequestRunner(async () => response)

  const started = await runner.run('token', {
    requestId: 'request-1',
    message: 'שאלה',
  }, {
    onStart: () => events.push('pending'),
    onSuccess: () => events.push('success'),
    onError: () => events.push('error'),
    onFinish: () => events.push('finished'),
  })

  assert.equal(started, true)
  assert.deepEqual(events, ['pending', 'success', 'finished'])
  assert.equal(runner.isActive(), false)
})

test('submission preserves the same logical request on error', async () => {
  let receivedRequest: { requestId: string; message: string } | undefined
  const runner = createChatRequestRunner(async () => {
    throw new TypeError('offline')
  })

  await runner.run('token', {
    requestId: 'stable-request-id',
    message: 'הטיוטה שלי',
  }, {
    onStart: () => undefined,
    onSuccess: () => undefined,
    onError: (_error, request) => { receivedRequest = request },
    onFinish: () => undefined,
  })

  assert.deepEqual(receivedRequest, {
    requestId: 'stable-request-id',
    message: 'הטיוטה שלי',
  })
})

test('double submit is blocked while the first request is active', async () => {
  let release: (() => void) | undefined
  let calls = 0
  const runner = createChatRequestRunner(async () => {
    calls += 1
    await new Promise<void>((resolve) => { release = resolve })
    return response
  })
  const callbacks = {
    onStart: () => undefined,
    onSuccess: () => undefined,
    onError: () => undefined,
    onFinish: () => undefined,
  }

  const first = runner.run('token', { requestId: 'one', message: 'one' }, callbacks)
  const second = await runner.run('token', { requestId: 'two', message: 'two' }, callbacks)
  assert.equal(second, false)
  assert.equal(calls, 1)
  release?.()
  await first
})

test('completed history prevents retry after a client disconnect', () => {
  const request = { requestId: 'request-1', message: 'מי עם הרכב?' }
  assert.equal(pendingRequestNeedsRetry(request, [{
    request_id: 'request-1',
    request_status: 'completed',
    role: 'assistant',
    content: 'הרכב פנוי.',
    created_at: '2026-09-02T12:00:00+00:00',
  }]), false)
  assert.equal(pendingRequestNeedsRetry(request, []), true)
})
