import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

function projectFile(path: string) {
  return new URL(`../${path}`, import.meta.url)
}

async function pngDimensions(path: string) {
  const contents = await readFile(projectFile(path))
  assert.equal(contents.subarray(1, 4).toString('ascii'), 'PNG')
  return {
    width: contents.readUInt32BE(16),
    height: contents.readUInt32BE(20),
  }
}

test('manifest icons use the real Family Car Agent assets at install sizes', async () => {
  const config = await readFile(projectFile('vite.config.ts'), 'utf8')

  assert.match(config, /family-car-agent-192\.png[\s\S]*sizes: '192x192'/)
  assert.match(config, /family-car-agent-512\.png[\s\S]*sizes: '512x512'/)
  assert.doesNotMatch(config, /app-icon\.svg|placeholder/i)
  assert.deepEqual(
    await pngDimensions('public/icons/family-car-agent-192.png'),
    { width: 192, height: 192 },
  )
  assert.deepEqual(
    await pngDimensions('public/icons/family-car-agent-512.png'),
    { width: 512, height: 512 },
  )
})

test('iPhone home-screen icon is an explicit 180px PNG', async () => {
  const html = await readFile(projectFile('index.html'), 'utf8')

  assert.match(
    html,
    /rel="apple-touch-icon" sizes="180x180" href="\/icons\/family-car-agent-apple-touch-180\.png"/,
  )
  assert.deepEqual(
    await pngDimensions('public/icons/family-car-agent-apple-touch-180.png'),
    { width: 180, height: 180 },
  )
})
