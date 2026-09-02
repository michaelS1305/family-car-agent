import assert from 'node:assert/strict'
import test from 'node:test'

import { prepareCarPlaySetup } from '../src/api/apiClient.ts'
import {
  carPlaySetupLastStep,
  clearCarPlaySetupDraft,
  copyConnectionCode,
  loadCarPlaySetupStep,
  nextCarPlaySetupStep,
  previousCarPlaySetupStep,
  saveCarPlaySetupStep,
} from '../src/carplay/carPlaySetupDraft.ts'

function memoryStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    removeItem: (key: string) => { values.delete(key) },
    values,
  }
}

test('CarPlay setup sends only the bearer identity and no request body', async () => {
  const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = []
  const setup = await prepareCarPlaySetup('access-token', {
    baseUrl: 'http://127.0.0.1:8000',
    fetcher: (async (input, init) => {
      calls.push([input, init])
      return new Response(JSON.stringify({
        connection_code: 'private-connection-code',
        connect_shortcut_url: 'https://www.icloud.com/shortcuts/connect',
        disconnect_shortcut_url: 'https://www.icloud.com/shortcuts/disconnect',
      }), { status: 200 })
    }) as typeof fetch,
  })

  assert.equal(setup.connection_code, 'private-connection-code')
  assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/carplay/setup')
  assert.equal(calls[0][1]?.method, 'POST')
  const headers = calls[0][1]?.headers as Record<string, string> | undefined
  assert.equal(headers?.Authorization, 'Bearer access-token')
  assert.equal(calls[0][1]?.body, undefined)
})

test('refresh restores only the current wizard step for the same account', () => {
  const storage = memoryStorage()
  saveCarPlaySetupStep('auth-user-a', 7, storage)

  assert.equal(loadCarPlaySetupStep('auth-user-a', storage), 7)
  const persisted = [...storage.values.values()].join('')
  assert.equal(persisted.includes('connection'), false)
  assert.equal(persisted.includes('token'), false)
})

test('progress from another account or malformed storage is discarded', () => {
  const storage = memoryStorage()
  saveCarPlaySetupStep('auth-user-a', 7, storage)
  assert.equal(loadCarPlaySetupStep('auth-user-b', storage), 0)
  assert.equal(storage.values.size, 0)

  storage.setItem('family-car-agent:carplay-setup', '{broken-json')
  assert.equal(loadCarPlaySetupStep('auth-user-a', storage), 0)
  assert.equal(storage.values.size, 0)

  storage.setItem('family-car-agent:carplay-setup', JSON.stringify({
    version: 1,
    authUserId: 'auth-user-a',
    currentStep: 8,
  }))
  assert.equal(loadCarPlaySetupStep('auth-user-a', storage), 0)
  assert.equal(storage.values.size, 0)
})

test('Back and Next move exactly one step and stay inside wizard bounds', () => {
  assert.equal(previousCarPlaySetupStep(0), 0)
  assert.equal(nextCarPlaySetupStep(carPlaySetupLastStep), carPlaySetupLastStep)

  for (let step = 0; step < carPlaySetupLastStep; step += 1) {
    const next = nextCarPlaySetupStep(step)
    assert.equal(next, step + 1)
    assert.equal(previousCarPlaySetupStep(next), step)
  }
})

test('connection code is copied through the Clipboard API', async () => {
  const copied: string[] = []
  await copyConnectionCode('private-connection-code', {
    writeText: async (value) => { copied.push(value) },
  })
  assert.deepEqual(copied, ['private-connection-code'])
})

test('finishing can clear persisted wizard progress', () => {
  const storage = memoryStorage()
  saveCarPlaySetupStep('auth-user-a', 12, storage)
  clearCarPlaySetupDraft(storage)
  assert.equal(loadCarPlaySetupStep('auth-user-a', storage), 0)
})
