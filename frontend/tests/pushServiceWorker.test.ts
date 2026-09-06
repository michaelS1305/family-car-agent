import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { parsePushNotificationPayload } from '../src/push/pushPayload.ts'

test('valid deterministic push payload is accepted', () => {
  assert.deepEqual(parsePushNotificationPayload({
    title: 'Family Car Agent',
    body: 'מיכאל לקח את הרכב',
    url: '/',
    tag: 'car-event-17',
  }), {
    title: 'Family Car Agent',
    body: 'מיכאל לקח את הרכב',
    url: '/',
    tag: 'car-event-17',
  })
  assert.ok(parsePushNotificationPayload({
    title: 'Family Car Agent', body: 'הרכב התפנה', url: '/', tag: 'car-event-18',
  }))
})

test('malformed and externally directed payloads fail safely', () => {
  assert.equal(parsePushNotificationPayload(null), null)
  assert.equal(parsePushNotificationPayload({ title: 'Other', body: 'הרכב התפנה', url: '/', tag: 'car-event-1' }), null)
  assert.equal(parsePushNotificationPayload({ title: 'Family Car Agent', body: 'arbitrary', url: '/', tag: 'car-event-1' }), null)
  assert.equal(parsePushNotificationPayload({ title: 'Family Car Agent', body: 'הרכב התפנה', url: 'https://evil.test', tag: 'car-event-1' }), null)
  assert.equal(parsePushNotificationPayload({ title: 'Family Car Agent', body: 'הרכב התפנה', url: '/', tag: 'bad' }), null)
})

test('custom worker preserves PWA lifecycle and uses the approved notification contract', async () => {
  const source = await readFile(new URL('../src/sw.ts', import.meta.url), 'utf8')
  const config = await readFile(new URL('../vite.config.ts', import.meta.url), 'utf8')
  assert.match(config, /strategies: 'injectManifest'/)
  assert.match(config, /registerType: 'autoUpdate'/)
  assert.match(source, /self\.skipWaiting\(\)/)
  assert.match(source, /clientsClaim\(\)/)
  assert.match(source, /precacheAndRoute\(self\.__WB_MANIFEST\)/)
  assert.match(source, /cleanupOutdatedCaches\(\)/)
  assert.match(source, /NavigationRoute\(createHandlerBoundToURL\('index\.html'\)\)/)
  assert.match(source, /showNotification\(payload\.title,[\s\S]*?family-car-agent-192\.png[\s\S]*?tag: payload\.tag/)
})

test('notification click focuses same-origin clients or opens only app root', async () => {
  const source = await readFile(new URL('../src/sw.ts', import.meta.url), 'utf8')
  assert.match(source, /new URL\(client\.url\)\.origin === self\.location\.origin/)
  assert.match(source, /await existingClient\.focus\(\)/)
  assert.match(source, /await self\.clients\.openWindow\('\/'\)/)
  assert.doesNotMatch(source, /openWindow\(payload|openWindow\(event\.notification\.data/)
})
