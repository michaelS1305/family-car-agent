export type InternalUser = {
  user_id: number
  name: string
  family_id: number | null
  carplay_setup_status: CarPlaySetupStatus
}

export type CarPlaySetupStatus = 'pending' | 'completed' | 'skipped'

export type CurrentUserResult =
  | { status: 'mapped'; user: InternalUser }
  | { status: 'unmapped' }
  | { status: 'unauthenticated' }

export type ApiRequestErrorKind = 'network' | 'server' | 'invalid-response'

export class ApiRequestError extends Error {
  readonly kind: ApiRequestErrorKind
  readonly status?: number

  constructor(kind: ApiRequestErrorKind, message: string, status?: number) {
    super(message)
    this.name = 'ApiRequestError'
    this.kind = kind
    this.status = status
  }
}

type RequestOptions = {
  baseUrl?: string
  fetcher?: typeof fetch
  signal?: AbortSignal
}

export type CreateFamilyErrorCode =
  | 'INVALID_FAMILY_NAME'
  | 'INVALID_FAMILY_CODE'
  | 'FAMILY_CODE_TAKEN'
  | 'INVALID_ADDRESS_FORMAT'
  | 'ADDRESS_NOT_FOUND'
  | 'ADDRESS_RESOLUTION_EXPIRED'
  | 'FAMILY_ALREADY_EXISTS_AT_ADDRESS'
  | 'INVALID_USER_NAME'
  | 'AUTH_USER_ALREADY_MAPPED'
  | 'AUTH_SESSION_INVALID'
  | 'JOIN_FAMILY_NAME_NOT_FOUND'
  | 'JOIN_FAMILY_ADDRESS_NOT_FOUND'
  | 'JOIN_LOCKED'
  | 'INVALID_JOIN_STEP'
  | 'UNAUTHORIZED'
  | 'SERVER_ERROR'
  | 'NETWORK_ERROR'

export class OnboardingApiError extends Error {
  readonly code: CreateFamilyErrorCode
  readonly status?: number
  readonly attemptsRemaining?: number
  readonly lockedUntil?: string

  constructor(
    code: CreateFamilyErrorCode,
    message: string,
    status?: number,
    attemptsRemaining?: number,
    lockedUntil?: string,
  ) {
    super(message)
    this.name = 'OnboardingApiError'
    this.code = code
    this.status = status
    this.attemptsRemaining = attemptsRemaining
    this.lockedUntil = lockedUntil
  }
}

export type ResolvedCreateFamilyAddress = {
  normalized_address: string
  display_address: string
  resolution_token: string
}

export type CreateFamilyPayload = {
  family_name: string
  family_code: string
  address_resolution_token: string
  user_name: string
}

export type JoinFamilyStep =
  | 'family_name'
  | 'address'
  | 'address_confirmed'
  | 'family_code'
  | 'user_name'

export type JoinFamilySession = {
  step: JoinFamilyStep
  family_name: string | null
  normalized_address: string | null
  resolved_address: string | null
  attempts_remaining: {
    family_name: number
    address: number
    family_code: number
  }
  reset: boolean
}

export type CarPlaySetup = {
  connection_code: string
  connect_shortcut_url: string
  disconnect_shortcut_url: string
}

function isCarPlaySetup(value: unknown): value is CarPlaySetup {
  if (!value || typeof value !== 'object') return false
  const setup = value as Partial<CarPlaySetup>
  return (
    typeof setup.connection_code === 'string'
    && setup.connection_code.length > 0
    && typeof setup.connect_shortcut_url === 'string'
    && setup.connect_shortcut_url.startsWith('https://www.icloud.com/shortcuts/')
    && typeof setup.disconnect_shortcut_url === 'string'
    && setup.disconnect_shortcut_url.startsWith('https://www.icloud.com/shortcuts/')
  )
}

function isInternalUser(value: unknown): value is InternalUser {
  if (!value || typeof value !== 'object') return false

  const user = value as Partial<InternalUser>
  return (
    Number.isInteger(user.user_id)
    && typeof user.name === 'string'
    && (user.family_id === null || Number.isInteger(user.family_id))
    && (
      user.carplay_setup_status === 'pending'
      || user.carplay_setup_status === 'completed'
      || user.carplay_setup_status === 'skipped'
    )
  )
}

function getCurrentUserUrl(explicitBaseUrl?: string) {
  const configuredBaseUrl = explicitBaseUrl ?? import.meta.env.VITE_API_BASE_URL
  const baseUrl = configuredBaseUrl?.trim().replace(/\/+$/, '') ?? ''
  return `${baseUrl}/api/me`
}

function getApiUrl(path: string, explicitBaseUrl?: string) {
  const configuredBaseUrl = explicitBaseUrl ?? import.meta.env.VITE_API_BASE_URL
  const baseUrl = configuredBaseUrl?.trim().replace(/\/+$/, '') ?? ''
  return `${baseUrl}${path}`
}

async function readOnboardingError(response: Response) {
  let detail: unknown
  try {
    const body: unknown = await response.json()
    detail = body && typeof body === 'object'
      ? (body as { detail?: unknown }).detail
      : undefined
  } catch {
    detail = undefined
  }

  if (detail && typeof detail === 'object') {
    const structured = detail as {
      code?: unknown
      message?: unknown
      attempts_remaining?: unknown
      locked_until?: unknown
    }
    if (typeof structured.code === 'string' && typeof structured.message === 'string') {
      return new OnboardingApiError(
        structured.code as CreateFamilyErrorCode,
        structured.message,
        response.status,
        typeof structured.attempts_remaining === 'number'
          ? structured.attempts_remaining
          : undefined,
        typeof structured.locked_until === 'string'
          ? structured.locked_until
          : undefined,
      )
    }
  }

  if (response.status === 401) {
    return new OnboardingApiError(
      'UNAUTHORIZED',
      'פג תוקף ההתחברות. יש להתחבר מחדש.',
      401,
    )
  }

  return new OnboardingApiError(
    'SERVER_ERROR',
    'לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.',
    response.status,
  )
}

async function postOnboardingJson<T>(
  path: string,
  accessToken: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const fetcher = options.fetcher ?? fetch
  let response: Response

  try {
    response = await fetcher(getApiUrl(path, options.baseUrl), {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new OnboardingApiError(
      'NETWORK_ERROR',
      'לא הצלחנו להתחבר לשרת. בדקו את החיבור ונסו שוב.',
    )
  }

  if (!response.ok) throw await readOnboardingError(response)

  try {
    return await response.json() as T
  } catch {
    throw new OnboardingApiError(
      'SERVER_ERROR',
      'התקבלה תשובה לא תקינה מהשרת.',
      response.status,
    )
  }
}

export function resolveCreateFamilyAddress(
  accessToken: string,
  homeAddress: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<ResolvedCreateFamilyAddress>(
    '/api/onboarding/create-family/address',
    accessToken,
    { home_address: homeAddress },
    options,
  )
}

export function createFamily(
  accessToken: string,
  payload: CreateFamilyPayload,
  options: RequestOptions = {},
) {
  return postOnboardingJson<{ created: true }>(
    '/api/onboarding/create-family',
    accessToken,
    payload,
    options,
  )
}

export function startJoinFamily(
  accessToken: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<JoinFamilySession>(
    '/api/onboarding/join-family/start',
    accessToken,
    {},
    options,
  )
}

export function submitJoinFamilyName(
  accessToken: string,
  familyName: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<JoinFamilySession>(
    '/api/onboarding/join-family/family-name',
    accessToken,
    { family_name: familyName },
    options,
  )
}

export function submitJoinFamilyAddress(
  accessToken: string,
  homeAddress: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<JoinFamilySession>(
    '/api/onboarding/join-family/address',
    accessToken,
    { home_address: homeAddress },
    options,
  )
}

export function confirmJoinFamilyAddress(
  accessToken: string,
  confirmed: boolean,
  options: RequestOptions = {},
) {
  return postOnboardingJson<JoinFamilySession>(
    '/api/onboarding/join-family/address-confirmation',
    accessToken,
    { confirmed },
    options,
  )
}

export function submitJoinFamilyCode(
  accessToken: string,
  familyCode: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<JoinFamilySession>(
    '/api/onboarding/join-family/code',
    accessToken,
    { family_code: familyCode },
    options,
  )
}

export function completeJoinFamily(
  accessToken: string,
  userName: string,
  options: RequestOptions = {},
) {
  return postOnboardingJson<{ created: true }>(
    '/api/onboarding/join-family/complete',
    accessToken,
    { user_name: userName },
    options,
  )
}

export async function getCurrentUser(
  accessToken: string,
  options: RequestOptions = {},
): Promise<CurrentUserResult> {
  const fetcher = options.fetcher ?? fetch
  let response: Response

  try {
    response = await fetcher(getCurrentUserUrl(options.baseUrl), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiRequestError('network', 'The backend could not be reached')
  }

  if (response.status === 401) return { status: 'unauthenticated' }
  if (response.status === 403) return { status: 'unmapped' }

  if (!response.ok) {
    throw new ApiRequestError(
      'server',
      'The backend returned an unexpected response',
      response.status,
    )
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiRequestError('invalid-response', 'The backend response is not valid JSON')
  }

  if (!isInternalUser(body)) {
    throw new ApiRequestError('invalid-response', 'The backend identity response is invalid')
  }

  return { status: 'mapped', user: body }
}

export async function prepareCarPlaySetup(
  accessToken: string,
  options: RequestOptions = {},
) {
  const fetcher = options.fetcher ?? fetch
  let response: Response
  try {
    response = await fetcher(getApiUrl('/api/carplay/setup', options.baseUrl), {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiRequestError('network', 'The backend could not be reached')
  }

  if (!response.ok) {
    throw new ApiRequestError('server', 'CarPlay setup is unavailable', response.status)
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiRequestError('invalid-response', 'The CarPlay setup response is invalid')
  }
  if (!isCarPlaySetup(body)) {
    throw new ApiRequestError('invalid-response', 'The CarPlay setup response is invalid')
  }
  return body
}

export async function updateCarPlaySetupStatus(
  accessToken: string,
  status: Exclude<CarPlaySetupStatus, 'pending'>,
  options: RequestOptions = {},
) {
  return postOnboardingJson<{ carplay_setup_status: Exclude<CarPlaySetupStatus, 'pending'> }>(
    '/api/carplay/setup/status',
    accessToken,
    { status },
    options,
  )
}
