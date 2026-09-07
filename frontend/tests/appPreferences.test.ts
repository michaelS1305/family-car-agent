import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  APP_PREFERENCES_STORAGE_KEY,
  applyPreferenceAttributes,
  effectiveTheme,
  loadAppPreferences,
  parseAppPreferences,
  saveAppPreferences,
} from '../src/preferences/appPreferences.ts'

function memoryStorage(initial?: string) {
  const values = new Map<string, string>()
  if (initial !== undefined) values.set(APP_PREFERENCES_STORAGE_KEY, initial)
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    value: () => values.get(APP_PREFERENCES_STORAGE_KEY),
  }
}

test('preferences default to system theme and normal text', () => {
  assert.deepEqual(loadAppPreferences(memoryStorage()), { theme: 'system', textSize: 'normal' })
  assert.equal(effectiveTheme('system', false), 'light')
  assert.equal(effectiveTheme('system', true), 'dark')
})

test('explicit light and dark override the system preference', () => {
  assert.equal(effectiveTheme('light', true), 'light')
  assert.equal(effectiveTheme('dark', false), 'dark')
})

test('theme and all three text sizes persist and apply at root level', () => {
  for (const textSize of ['small', 'normal', 'large'] as const) {
    const storage = memoryStorage()
    saveAppPreferences({ theme: 'dark', textSize }, storage)
    assert.deepEqual(loadAppPreferences(storage), { theme: 'dark', textSize })
    const root = { dataset: {} as DOMStringMap }
    applyPreferenceAttributes(root, { theme: 'dark', textSize }, false)
    assert.deepEqual(root.dataset, {
      theme: 'dark',
      effectiveTheme: 'dark',
      textSize,
    })
  }
})

test('malformed and stale preference values fall back safely', () => {
  assert.deepEqual(loadAppPreferences(memoryStorage('{broken')), { theme: 'system', textSize: 'normal' })
  assert.deepEqual(parseAppPreferences({ theme: 'sepia', textSize: 'huge' }), {
    theme: 'system',
    textSize: 'normal',
  })
})

test('provider follows system changes only through the system preference and startup avoids theme flash', () => {
  const provider = readFileSync(new URL('../src/preferences/AppPreferencesContext.tsx', import.meta.url), 'utf8')
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
  assert.match(provider, /matchMedia\('\(prefers-color-scheme: dark\)'\)/)
  assert.match(provider, /addEventListener\('change', update\)/)
  assert.match(provider, /effectiveTheme === 'dark'/)
  assert.match(html, /family-car-agent:preferences/)
  assert.match(html, /dataset\.effectiveTheme/)
  assert.match(css, /html\[data-text-size='small'\]/)
  assert.match(css, /html\[data-text-size='large'\]/)
  assert.match(css, /html\[data-effective-theme='dark'\]/)
})
