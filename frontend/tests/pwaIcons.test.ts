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

test('standalone iPhone display opts into the full viewport with a matching canvas', async () => {
  const html = await readFile(projectFile('index.html'), 'utf8')
  const config = await readFile(projectFile('vite.config.ts'), 'utf8')
  const globalCss = await readFile(projectFile('src/index.css'), 'utf8')
  const appCss = await readFile(projectFile('src/App.css'), 'utf8')

  assert.match(html, /name="viewport" content="[^"]*viewport-fit=cover[^"]*"/)
  assert.match(html, /name="apple-mobile-web-app-capable" content="yes"/)
  assert.match(html, /name="apple-mobile-web-app-status-bar-style" content="black-translucent"/)
  assert.match(html, /name="theme-color" content="#fffefc"/)
  assert.match(config, /background_color: '#fffefc'/)
  assert.match(config, /theme_color: '#fffefc'/)
  assert.match(globalCss, /#root \{[\s\S]*?min-height: 100dvh;[\s\S]*?background: var\(--app-canvas\);/)
  assert.match(appCss, /\.main-chat-header \{[\s\S]*?top: max\(4px, calc\(env\(safe-area-inset-top\) - 4px\)\);/)
  assert.match(appCss, /\.chat-thread \{[\s\S]*?position: absolute;[\s\S]*?inset: 0;/)
  assert.match(appCss, /\.chat-thread \{[\s\S]*?-webkit-mask-image: linear-gradient\([\s\S]*?transparent 0,/)
})
