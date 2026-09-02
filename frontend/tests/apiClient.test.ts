import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ApiRequestError,
  createFamily,
  getCurrentUser,
  OnboardingApiError,
  resolveCreateFamilyAddress,
  completeJoinFamily,
  startJoinFamily,
  submitJoinFamilyName,
  updateCarPlaySetupStatus,
} from '../src/api/apiClient.ts'

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('200 returns the backend identity and sends only the bearer token', async () => {
  let receivedUrl = ''
  let receivedRequest: RequestInit | undefined
  const fetcher: typeof fetch = async (url, request) => {
    receivedUrl = String(url)
    receivedRequest = request
    return jsonResponse(200, {
      user_id: 17,
      name: 'מיכאל',
      family_id: 42,
      carplay_setup_status: 'pending',
    })
  }

  const result = await getCurrentUser('test-access-token', {
    baseUrl: 'http://backend.test/',
    fetcher,
  })

  assert.deepEqual(result, {
    status: 'mapped',
    user: {
      user_id: 17,
      name: 'מיכאל',
      family_id: 42,
      carplay_setup_status: 'pending',
    },
  })
  assert.equal(receivedUrl, 'http://backend.test/api/me')
  assert.equal(receivedRequest?.method, 'GET')
  assert.deepEqual(receivedRequest?.headers, {
    Accept: 'application/json',
    Authorization: 'Bearer test-access-token',
  })
  assert.equal(receivedRequest?.body, undefined)
})

test('CarPlay status update sends only the requested status and bearer identity', async () => {
  let receivedUrl = ''
  let receivedRequest: RequestInit | undefined
  const result = await updateCarPlaySetupStatus('access-token', 'skipped', {
    baseUrl: 'http://backend.test/',
    fetcher: async (url, request) => {
      receivedUrl = String(url)
      receivedRequest = request
      return jsonResponse(200, { carplay_setup_status: 'skipped' })
    },
  })

  assert.deepEqual(result, { carplay_setup_status: 'skipped' })
  assert.equal(receivedUrl, 'http://backend.test/api/carplay/setup/status')
  assert.equal(receivedRequest?.method, 'POST')
  assert.deepEqual(JSON.parse(String(receivedRequest?.body)), { status: 'skipped' })
  assert.deepEqual(receivedRequest?.headers, {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    Authorization: 'Bearer access-token',
  })
})

test('403 means the authenticated user has no internal mapping', async () => {
  const result = await getCurrentUser('token', {
    baseUrl: 'http://backend.test',
    fetcher: async () => new Response(null, { status: 403 }),
  })

  assert.deepEqual(result, { status: 'unmapped' })
})

test('401 means the Supabase session must be refreshed or cleared', async () => {
  const result = await getCurrentUser('token', {
    baseUrl: 'http://backend.test',
    fetcher: async () => new Response(null, { status: 401 }),
  })

  assert.deepEqual(result, { status: 'unauthenticated' })
})

test('network failure becomes a typed error', async () => {
  await assert.rejects(
    getCurrentUser('token', {
      baseUrl: 'http://backend.test',
      fetcher: async () => {
        throw new TypeError('offline')
      },
    }),
    (error: unknown) => error instanceof ApiRequestError && error.kind === 'network',
  )
})

test('unexpected server response becomes an error', async () => {
  await assert.rejects(
    getCurrentUser('token', {
      baseUrl: 'http://backend.test',
      fetcher: async () => new Response(null, { status: 500 }),
    }),
    (error: unknown) => (
      error instanceof ApiRequestError
      && error.kind === 'server'
      && error.status === 500
    ),
  )
})

test('missing auth user returns a structured invalid-session error', async () => {
  await assert.rejects(
    createFamily('stale-token', {
      family_name: 'כהן',
      family_code: '482731',
      address_resolution_token: 'opaque-resolution-token',
      user_name: 'מיכאל',
    }, {
      baseUrl: 'http://backend.test',
      fetcher: async () => jsonResponse(401, {
        detail: {
          code: 'AUTH_SESSION_INVALID',
          message: 'ההתחברות שלך כבר לא תקפה. התחבר מחדש כדי להמשיך.',
        },
      }),
    }),
    (error: unknown) => (
      error instanceof OnboardingApiError
      && error.code === 'AUTH_SESSION_INVALID'
      && error.status === 401
    ),
  )
})

test('address resolution sends only address and bearer identity', async () => {
  let receivedRequest: RequestInit | undefined
  const result = await resolveCreateFamilyAddress(
    'access-token',
    'תל אביב, דיזנגוף, 120',
    {
      baseUrl: 'http://backend.test',
      fetcher: async (_url, request) => {
        receivedRequest = request
        return jsonResponse(200, {
          normalized_address: 'תל אביב, דיזנגוף, 120',
          display_address: '120 Dizengoff Street, Tel Aviv',
          resolution_token: 'opaque-resolution-token',
        })
      },
    },
  )

  assert.ok(receivedRequest)
  assert.equal(receivedRequest.method, 'POST')
  assert.deepEqual(JSON.parse(String(receivedRequest.body)), {
    home_address: 'תל אביב, דיזנגוף, 120',
  })
  const requestHeaders = receivedRequest.headers as Record<string, string>
  assert.equal(
    requestHeaders.Authorization,
    'Bearer access-token',
  )
  assert.equal(result.display_address, '120 Dizengoff Street, Tel Aviv')
  assert.equal(result.resolution_token, 'opaque-resolution-token')
})

test('successful create sends no client identity fields', async () => {
  let receivedBody: unknown
  const result = await createFamily(
    'access-token',
    {
      family_name: 'כהן',
      family_code: '482731',
      address_resolution_token: 'opaque-resolution-token',
      user_name: 'מיכאל',
    },
    {
      baseUrl: 'http://backend.test',
      fetcher: async (_url, request) => {
        receivedBody = JSON.parse(String(request?.body))
        return jsonResponse(201, { created: true })
      },
    },
  )

  assert.deepEqual(result, { created: true })
  assert.deepEqual(receivedBody, {
    family_name: 'כהן',
    family_code: '482731',
    address_resolution_token: 'opaque-resolution-token',
    user_name: 'מיכאל',
  })
  assert.equal('auth_user_id' in (receivedBody as object), false)
  assert.equal('user_id' in (receivedBody as object), false)
  assert.equal('family_id' in (receivedBody as object), false)
})

test('structured validation and duplicate errors are preserved', async () => {
  await assert.rejects(
    createFamily(
      'token',
      {
        family_name: 'כהן',
        family_code: '482731',
        address_resolution_token: 'opaque-resolution-token',
        user_name: 'מיכאל',
      },
      {
        baseUrl: 'http://backend.test',
        fetcher: async () => jsonResponse(409, {
          detail: {
            code: 'FAMILY_CODE_TAKEN',
            message: 'קוד המשפחה הזה כבר תפוס. בחרו קוד אחר.',
          },
        }),
      },
    ),
    (error: unknown) => (
      error instanceof OnboardingApiError
      && error.code === 'FAMILY_CODE_TAKEN'
      && error.status === 409
    ),
  )
})

test('create maps 401 and network failure without parsing text', async () => {
  const payload = {
    family_name: 'כהן',
    family_code: '482731',
    address_resolution_token: 'opaque-resolution-token',
    user_name: 'מיכאל',
  }

  await assert.rejects(
    createFamily('token', payload, {
      baseUrl: 'http://backend.test',
      fetcher: async () => new Response(null, { status: 401 }),
    }),
    (error: unknown) => error instanceof OnboardingApiError && error.code === 'UNAUTHORIZED',
  )

  await assert.rejects(
    createFamily('token', payload, {
      baseUrl: 'http://backend.test',
      fetcher: async () => { throw new TypeError('offline') },
    }),
    (error: unknown) => error instanceof OnboardingApiError && error.code === 'NETWORK_ERROR',
  )
})

test('Join start sends only the bearer identity and returns server state', async () => {
  let receivedBody: unknown
  const result = await startJoinFamily('join-token', {
    baseUrl: 'http://backend.test',
    fetcher: async (_url, request) => {
      receivedBody = JSON.parse(String(request?.body))
      return jsonResponse(200, {
        step: 'family_name',
        family_name: null,
        normalized_address: null,
        resolved_address: null,
        attempts_remaining: { family_name: 3, address: 3, family_code: 3 },
        reset: false,
      })
    },
  })

  assert.deepEqual(receivedBody, {})
  assert.equal(result.step, 'family_name')
  assert.equal('family_id' in result, false)
  assert.equal('auth_user_id' in result, false)
})

test('Join validation error preserves server attempts metadata', async () => {
  await assert.rejects(
    submitJoinFamilyName('join-token', 'לא קיימת', {
      baseUrl: 'http://backend.test',
      fetcher: async () => jsonResponse(404, {
        detail: {
          code: 'JOIN_FAMILY_NAME_NOT_FOUND',
          message: 'לא מצאנו משפחה בשם הזה. נותרו 2 ניסיונות.',
          attempts_remaining: 2,
        },
      }),
    }),
    (error: unknown) => (
      error instanceof OnboardingApiError
      && error.code === 'JOIN_FAMILY_NAME_NOT_FOUND'
      && error.attemptsRemaining === 2
    ),
  )
})

test('Join lock error includes the authoritative unlock time', async () => {
  await assert.rejects(
    submitJoinFamilyName('join-token', 'לא קיימת', {
      baseUrl: 'http://backend.test',
      fetcher: async () => jsonResponse(429, {
        detail: {
          code: 'JOIN_LOCKED',
          message: 'תהליך ההצטרפות נעול.',
          attempts_remaining: 0,
          locked_until: '2026-08-30T12:15:00+00:00',
        },
      }),
    }),
    (error: unknown) => (
      error instanceof OnboardingApiError
      && error.code === 'JOIN_LOCKED'
      && error.lockedUntil === '2026-08-30T12:15:00+00:00'
    ),
  )
})

test('Join completion sends a name but no client identity fields', async () => {
  let receivedBody: Record<string, unknown> = {}
  const result = await completeJoinFamily('join-token', 'מיכאל', {
    baseUrl: 'http://backend.test',
    fetcher: async (_url, request) => {
      receivedBody = JSON.parse(String(request?.body)) as Record<string, unknown>
      return jsonResponse(201, { created: true })
    },
  })

  assert.deepEqual(receivedBody, { user_name: 'מיכאל' })
  assert.equal('family_id' in receivedBody, false)
  assert.equal('user_id' in receivedBody, false)
  assert.equal('auth_user_id' in receivedBody, false)
  assert.deepEqual(result, { created: true })
})
