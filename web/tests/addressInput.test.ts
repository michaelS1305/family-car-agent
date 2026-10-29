import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isValidAddress } from '../src/onboarding/addressInput.ts'
test('full natural input and legacy comma format reach server validation', () => {
  for (const address of ['דימונה, המעפיל, 1209', 'המעפיל 1209 דימונה', 'דימונה המעפיל 1209', 'המעפיל 1209, דימונה', 'שדרות בן גוריון 12 תל אביב']) assert.equal(isValidAddress(address), true)
  for (const address of ['', '   ', 'א'.repeat(201)]) assert.equal(isValidAddress(address), false)
})
