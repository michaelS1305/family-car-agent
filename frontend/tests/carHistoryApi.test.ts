import assert from 'node:assert/strict'
import test from 'node:test'

import { getCarHistory } from '../src/api/apiClient.ts'

const history = {
  active_usage: { name: 'מיכאל', started_at: '2026-09-06T08:00:00' },
  recent_usage: [{
    name: 'נועה',
    started_at: '2026-09-05T10:00:00',
    ended_at: '2026-09-05T11:00:00',
  }],
}

test('history fetch sends bearer identity only and accepts display-safe sessions', async () => {
  let url = ''
  let init: RequestInit | undefined
  const result = await getCarHistory('access-token', {
    baseUrl: 'https://api.example.com',
    fetcher: async (input, requestInit) => {
      url = String(input)
      init = requestInit
      return new Response(JSON.stringify(history), { status: 200 })
    },
  })

  assert.equal(url, 'https://api.example.com/api/car/history')
  assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer access-token')
  assert.deepEqual(result, history)
  assert.doesNotMatch(JSON.stringify(result), /user_id|family_id|auth_user_id|shortcut_token|event_id/)
})

test('history rejects raw or malformed backend event responses', async () => {
  await assert.rejects(
    getCarHistory('token', {
      fetcher: async () => new Response(JSON.stringify({
        active_usage: null,
        recent_usage: [{ status: 'connected', event_id: 4 }],
      }), { status: 200 }),
    }),
    /Car history response is invalid/,
  )
})
