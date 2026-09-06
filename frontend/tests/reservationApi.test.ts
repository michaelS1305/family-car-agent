import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cancelReservation,
  createReservation,
  getReservations,
  updateReservation,
} from '../src/api/apiClient.ts'

const reservation = {
  owner_name: 'מיכאל',
  start_time: '2026-09-08T10:00:00',
  end_time: '2026-09-08T11:00:00',
  is_mine: true,
}

test('default list uses future all with bearer identity only', async () => {
  let url = ''
  let init: RequestInit | undefined
  const result = await getReservations('access-token', undefined, undefined, {
    baseUrl: 'https://api.example.com',
    fetcher: async (input, requestInit) => {
      url = String(input)
      init = requestInit
      return new Response(JSON.stringify([reservation]), { status: 200 })
    },
  })

  assert.equal(url, 'https://api.example.com/api/reservations?time=future&scope=all')
  assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer access-token')
  assert.doesNotMatch(url, /family_id|user_id|auth_user_id/)
  assert.deepEqual(result, [reservation])
})

test('list forwards only validated display filters', async () => {
  let url = ''
  await getReservations('token', 'past', 'mine', {
    baseUrl: 'https://api.example.com',
    fetcher: async (input) => {
      url = String(input)
      return new Response('[]', { status: 200 })
    },
  })
  assert.match(url, /time=past&scope=mine$/)
})

test('create body contains only the reservation interval', async () => {
  let body = ''
  await createReservation('token', reservation, {
    baseUrl: 'https://api.example.com',
    fetcher: async (_input, init) => {
      body = String(init?.body)
      return new Response(JSON.stringify(reservation), { status: 201 })
    },
  })
  assert.deepEqual(JSON.parse(body), {
    start_time: reservation.start_time,
    end_time: reservation.end_time,
  })
  assert.doesNotMatch(body, /user_id|family_id|reservation_id/)
})

test('update and cancellation use original interval without internal IDs', async () => {
  const bodies: string[] = []
  const fetcher = async (_input: RequestInfo | URL, init?: RequestInit) => {
    bodies.push(String(init?.body))
    return new Response(
      bodies.length === 1 ? JSON.stringify(reservation) : JSON.stringify({ cancelled: true }),
      { status: 200 },
    )
  }
  const original = {
    start_time: reservation.start_time,
    end_time: reservation.end_time,
  }
  await updateReservation('token', original, {
    start_time: '2026-09-08T12:00:00',
    end_time: '2026-09-08T13:00:00',
  }, { baseUrl: 'https://api.example.com', fetcher })
  await cancelReservation('token', original, {
    baseUrl: 'https://api.example.com',
    fetcher,
  })

  assert.deepEqual(JSON.parse(bodies[0]), {
    original_start_time: reservation.start_time,
    original_end_time: reservation.end_time,
    start_time: '2026-09-08T12:00:00',
    end_time: '2026-09-08T13:00:00',
  })
  assert.deepEqual(JSON.parse(bodies[1]), {
    original_start_time: reservation.start_time,
    original_end_time: reservation.end_time,
  })
  assert.doesNotMatch(bodies.join(''), /reservation_id|user_id|family_id/)
})
