import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ChatApiError,
  getChatHistory,
  sendChatMessage,
} from '../src/api/apiClient.ts'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('chat send uses bearer identity and sends no internal identity fields', async () => {
  let requestInit: RequestInit | undefined
  const requestId = '0da80a79-74f1-496f-9bd0-dd4ef43d38a7'
  const result = await sendChatMessage('access-token', requestId, 'מי עם הרכב?', {
    baseUrl: 'https://backend.test',
    fetcher: async (_url, init) => {
      requestInit = init
      return jsonResponse(200, {
        request_id: requestId,
        status: 'completed',
        assistant_message: {
          role: 'assistant',
          content: 'הרכב פנוי.',
          created_at: '2026-09-02T12:00:00+00:00',
        },
      })
    },
  })

  const body = JSON.parse(String(requestInit?.body))
  assert.deepEqual(body, { request_id: requestId, message: 'מי עם הרכב?' })
  assert.equal(body.user_id, undefined)
  assert.equal(body.family_id, undefined)
  assert.equal(body.auth_user_id, undefined)
  assert.deepEqual(requestInit?.headers, {
    Accept: 'application/json',
    Authorization: 'Bearer access-token',
    'Content-Type': 'application/json',
  })
  assert.equal(result.assistant_message.content, 'הרכב פנוי.')
})

test('chat history is loaded only through the bearer session', async () => {
  let requestInit: RequestInit | undefined
  const messages = await getChatHistory('access-token', {
    baseUrl: 'https://backend.test',
    fetcher: async (_url, init) => {
      requestInit = init
      return jsonResponse(200, {
        messages: [
          { request_id: 'request-one', request_status: 'completed', role: 'user', content: 'שאלה', created_at: 'one' },
          { request_id: 'request-one', request_status: 'completed', role: 'assistant', content: 'תשובה', created_at: 'two' },
        ],
      })
    },
  })
  assert.equal(requestInit?.method, 'GET')
  assert.deepEqual(requestInit?.headers, {
    Accept: 'application/json',
    Authorization: 'Bearer access-token',
  })
  assert.deepEqual(messages.map((message) => message.role), ['user', 'assistant'])
})

test('CHAT_IN_PROGRESS keeps structured retry metadata', async () => {
  await assert.rejects(
    sendChatMessage('token', crypto.randomUUID(), 'test', {
      fetcher: async () => jsonResponse(409, {
        detail: {
          code: 'CHAT_IN_PROGRESS',
          message: 'ההודעה עדיין בעיבוד.',
          retry_after_seconds: 2,
        },
      }),
    }),
    (error: unknown) => (
      error instanceof ChatApiError
      && error.code === 'CHAT_IN_PROGRESS'
      && error.retryAfterSeconds === 2
      && !error.networkUncertain
    ),
  )
})

test('network failure is marked uncertain so retry can reuse the request id', async () => {
  await assert.rejects(
    sendChatMessage('token', crypto.randomUUID(), 'test', {
      fetcher: async () => {
        throw new TypeError('offline')
      },
    }),
    (error: unknown) => (
      error instanceof ChatApiError
      && error.code === 'NETWORK_ERROR'
      && error.networkUncertain
    ),
  )
})
