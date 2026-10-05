import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createFamilyVehicle, getFamilyVehicle, listFamilyVehicles, ApiRequestError } from '../src/api/apiClient.ts'
import { vehicleCreationSubmission } from '../src/vehicleCreation.ts'

const source = readFileSync(new URL('../src/components/VehiclesScreen.tsx', import.meta.url), 'utf8')
const dashboard = readFileSync(new URL('../src/components/DashboardScreen.tsx', import.meta.url), 'utf8')
const chat = readFileSync(new URL('../src/components/MainAppScreen.tsx', import.meta.url), 'utf8')
const vehicle = { vehicle_ref: '11111111-1111-4111-8111-111111111111', display_name: 'Hyundai', retired_at: null, in_use: false, current_driver: null }
const key = '22222222-2222-4222-8222-222222222222'

test('list accepts zero/one/many vehicles and excludes retired records', async () => {
  for (const rows of [[], [vehicle], [vehicle, { ...vehicle, vehicle_ref: key }]]) {
    const result = await listFamilyVehicles('jwt', { fetcher: async () => new Response(JSON.stringify(rows)) })
    assert.equal(result.length, rows.length)
  }
  assert.deepEqual(await listFamilyVehicles('jwt', { fetcher: async () => new Response(JSON.stringify([{ ...vehicle, retired_at: 'date' }])) }), [])
})

test('creation sends only name, stable key and bearer identity', async () => {
  await createFamilyVehicle('jwt', { display_name: 'Hyundai', request_id: key }, { baseUrl: 'https://api.test', fetcher: async (url, init) => {
    assert.equal(url, 'https://api.test/api/vehicles')
    assert.equal(new Headers(init?.headers).get('Authorization'), 'Bearer jwt')
    assert.deepEqual(JSON.parse(String(init?.body)), { display_name: 'Hyundai', request_id: key })
    return new Response(JSON.stringify(vehicle))
  } })
})

test('detail encodes opaque reference and preserves authoritative status', async () => {
  const result = await getFamilyVehicle('jwt', vehicle.vehicle_ref, { baseUrl: 'https://api.test', fetcher: async url => {
    assert.equal(url, 'https://api.test/api/vehicles/' + vehicle.vehicle_ref)
    return new Response(JSON.stringify({ ...vehicle, in_use: true, current_driver: 'נועה' }))
  } })
  assert.equal(result.current_driver, 'נועה')
  assert.equal(result.in_use, true)
  await assert.rejects(getFamilyVehicle('jwt', key, { fetcher: async () => new Response(JSON.stringify({ ...vehicle, retired_at: 'date' })) }))
})

test('quota errors remain structured and contain useful Hebrew guidance', async () => {
  await assert.rejects(createFamilyVehicle('jwt', { display_name: 'Car', request_id: key }, { fetcher: async () =>
    new Response(JSON.stringify({ detail: { code: 'VEHICLE_ACTIVE_LIMIT' } }), { status: 409 }) }),
  (e: unknown) => e instanceof ApiRequestError && e.code === 'VEHICLE_ACTIVE_LIMIT' && e.message.includes('הרכבים'))
})

test('uncertain retry and remount preserve immutable creation identity without storing credentials', async () => {
  const values = new Map<string, string>()
  const storage = { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => { values.set(k, v) }, removeItem: (k: string) => { values.delete(k) } }
  let submission = vehicleCreationSubmission(storage, 'owner-a')
  await assert.rejects(submission.submit('Hyundai', async () => { throw new Error('lost response') }, () => key))
  submission = vehicleCreationSubmission(storage, 'owner-a')
  assert.equal(vehicleCreationSubmission(storage, 'owner-b').pending(), null)
  await submission.submit('changed name', async payload => {
    assert.deepEqual(payload, { display_name: 'Hyundai', request_id: key })
    return vehicle
  }, () => { throw new Error('must not allocate another ID') })
  assert.equal(submission.pending(), null)
  assert.equal(values.size, 0)
})

test('rapid duplicate submission sends one request', async () => {
  const submission = vehicleCreationSubmission()
  let finish!: () => void
  let calls = 0
  const first = submission.submit('Car', async () => { calls++; await new Promise<void>(resolve => { finish = resolve }); return vehicle }, () => key)
  assert.equal(await submission.submit('Car', async () => { calls++; return vehicle }), undefined)
  finish(); await first
  assert.equal(calls, 1)
})

test('Vehicles has scoped list, add, detail, retry, empty and truthful future areas', () => {
  for (const text of ['הרכב הראשון שלכם', 'הוספת רכב', 'פרטי רכב', 'היסטוריית הרכב', 'הזמנות לרכב', 'זיהוי אוטומטי', 'נסו שוב']) assert.ok(source.includes(text))
  assert.ok(source.includes('vehicles.map'))
  assert.ok(source.includes('AbortController'))
  assert.ok(source.includes('getFamilyVehicle'))
  assert.ok(source.includes('dir="rtl"'))
  assert.ok(source.includes('aria-modal="true"'))
  assert.ok(source.includes('stopImmediatePropagation'))
  assert.ok(dashboard.includes('refreshVersion={carDataRefreshVersion}'))
  assert.ok(dashboard.includes('key={authUserId}'))
  assert.doesNotMatch(source, /fuel|VIN|telemetry|navigator.geolocation/)
})

test('Chat indicator is explicitly family aggregate without changing realtime architecture', () => {
  assert.ok(chat.includes('מצב רכבי המשפחה'))
  assert.ok(chat.includes('יש רכב בשימוש'))
  assert.ok(chat.includes('אין רכב בשימוש'))
  assert.equal((chat.match(/createCarStatusRealtimeSync\(/g) ?? []).length, 1)
})
