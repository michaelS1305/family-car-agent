import assert from 'node:assert/strict'
import test from 'node:test'

import { getFamily, updateFamilyMemberRole } from '../src/api/apiClient.ts'

const family = {
  name: 'כהן',
  home_address: 'דימונה, המעפיל, 1209',
  family_code: '482731',
  can_edit_roles: true,
  members: [{
    member_ref: '11111111-1111-4111-8111-111111111111',
    name: 'מיכאל',
    role: null,
    is_family_admin: true,
  }],
}

test('family read sends bearer auth without client identity parameters', async () => {
  let capturedUrl = ''
  let capturedInit: RequestInit | undefined
  const result = await getFamily('access-token', {
    baseUrl: 'https://api.example.com',
    fetcher: async (url, init) => {
      capturedUrl = String(url)
      capturedInit = init
      return new Response(JSON.stringify(family), { status: 200 })
    },
  })

  assert.equal(capturedUrl, 'https://api.example.com/api/family')
  assert.equal(new Headers(capturedInit?.headers).get('Authorization'), 'Bearer access-token')
  assert.doesNotMatch(capturedUrl, /user_id|family_id|auth_user_id/)
  assert.deepEqual(result, family)
})

test('role patch sends only the cosmetic role for the public member reference', async () => {
  let capturedUrl = ''
  let capturedInit: RequestInit | undefined
  const updated = { ...family.members[0], role: 'parent' as const }
  const result = await updateFamilyMemberRole(
    'access-token',
    family.members[0].member_ref,
    'parent',
    {
      baseUrl: 'https://api.example.com',
      fetcher: async (url, init) => {
        capturedUrl = String(url)
        capturedInit = init
        return new Response(JSON.stringify(updated), { status: 200 })
      },
    },
  )

  assert.match(capturedUrl, /\/api\/family\/members\/11111111-1111-4111-8111-111111111111\/role$/)
  assert.deepEqual(JSON.parse(String(capturedInit?.body)), { role: 'parent' })
  assert.doesNotMatch(String(capturedInit?.body), /user_id|family_id|auth_user_id/)
  assert.deepEqual(result, updated)
})

test('role clear sends a JSON null role', async () => {
  let body = ''
  await updateFamilyMemberRole('token', family.members[0].member_ref, null, {
    baseUrl: 'https://api.example.com',
    fetcher: async (_url, init) => {
      body = String(init?.body)
      return new Response(JSON.stringify(family.members[0]), { status: 200 })
    },
  })
  assert.deepEqual(JSON.parse(body), { role: null })
})
