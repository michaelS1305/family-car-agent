import type { CreateValidationAttempts } from '../onboarding/createValidationAttempts'

export type OnboardingFlow = 'create' | 'join'

export type OnboardingFormData = {
  familyName: string
  familyCode: string
  address: string
  userName: string
  resolvedAddress?: string
  addressResolutionToken?: string
}

export type OnboardingDraft = {
  flow: OnboardingFlow
  step: number
  form: OnboardingFormData
  createAttempts?: CreateValidationAttempts
}

export type PendingCreateSuccess = {
  version: 1
  flow: 'create'
  authUserId: string
  createdAt: string
  familyName: string
  familyCode: string
  userName: string
}

export type PendingJoinSuccess = {
  version: 1
  flow: 'join'
  authUserId: string
  createdAt: string
  familyName: string
  userName: string
}

const draftKey = 'family-car-agent:onboarding-draft'
const pendingCreateSuccessKey = 'family-car-agent:pending-create-success'
const pendingJoinSuccessKey = 'family-car-agent:pending-join-success'

type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

function getBrowserSessionStorage(): DraftStorage | null {
  return typeof window === 'undefined' ? null : window.sessionStorage
}

function isDraft(value: unknown): value is OnboardingDraft {
  if (!value || typeof value !== 'object') return false

  const draft = value as Partial<OnboardingDraft>
  const form = draft.form as Partial<OnboardingFormData> | undefined
  const attempts = draft.createAttempts

  return (
    (draft.flow === 'create' || draft.flow === 'join')
    && Number.isInteger(draft.step)
    && Number(draft.step) >= 0
    && Number(draft.step) <= (draft.flow === 'create' ? 4 : 5)
    && Boolean(form)
    && typeof form?.familyName === 'string'
    && typeof form.familyCode === 'string'
    && typeof form.address === 'string'
    && typeof form.userName === 'string'
    && (form.resolvedAddress === undefined || typeof form.resolvedAddress === 'string')
    && (
      form.addressResolutionToken === undefined
      || typeof form.addressResolutionToken === 'string'
    )
    && (
      attempts === undefined
      || (
        Number.isInteger(attempts.familyCode)
        && attempts.familyCode >= 0
        && attempts.familyCode <= 3
        && Number.isInteger(attempts.address)
        && attempts.address >= 0
        && attempts.address <= 3
      )
    )
  )
}

function isPendingCreateSuccess(value: unknown): value is PendingCreateSuccess {
  if (!value || typeof value !== 'object') return false

  const pending = value as Partial<PendingCreateSuccess>
  return (
    pending.version === 1
    && pending.flow === 'create'
    && typeof pending.authUserId === 'string'
    && pending.authUserId.length > 0
    && typeof pending.createdAt === 'string'
    && !Number.isNaN(Date.parse(pending.createdAt))
    && typeof pending.familyName === 'string'
    && pending.familyName.trim().length > 0
    && typeof pending.familyCode === 'string'
    && /^\d{6}$/.test(pending.familyCode)
    && typeof pending.userName === 'string'
    && pending.userName.trim().length > 0
  )
}

function isPendingJoinSuccess(value: unknown): value is PendingJoinSuccess {
  if (!value || typeof value !== 'object') return false

  const pending = value as Partial<PendingJoinSuccess>
  return (
    pending.version === 1
    && pending.flow === 'join'
    && typeof pending.authUserId === 'string'
    && pending.authUserId.length > 0
    && typeof pending.createdAt === 'string'
    && !Number.isNaN(Date.parse(pending.createdAt))
    && typeof pending.familyName === 'string'
    && pending.familyName.trim().length > 0
    && typeof pending.userName === 'string'
    && pending.userName.trim().length > 0
  )
}

function removeInvalidStoredValue(storage: DraftStorage | null, key: string) {
  try {
    storage?.removeItem(key)
  } catch {
    // Invalid state is still ignored when browser storage is unavailable.
  }
}

export function loadOnboardingDraft(storage = getBrowserSessionStorage()) {
  try {
    const storedDraft = storage?.getItem(draftKey)
    if (!storedDraft) return null

    const parsedDraft: unknown = JSON.parse(storedDraft)
    if (isDraft(parsedDraft)) return parsedDraft
    removeInvalidStoredValue(storage, draftKey)
    return null
  } catch {
    removeInvalidStoredValue(storage, draftKey)
    return null
  }
}

export function saveOnboardingDraft(
  draft: OnboardingDraft,
  storage = getBrowserSessionStorage(),
) {
  try {
    storage?.setItem(draftKey, JSON.stringify(draft))
  } catch {
    // The flow still works when browser storage is unavailable.
  }
}

export function clearOnboardingDraft(storage = getBrowserSessionStorage()) {
  try {
    storage?.removeItem(draftKey)
  } catch {
    // There is nothing else to clean up when storage is unavailable.
  }
}

export function loadPendingCreateSuccess(storage = getBrowserSessionStorage()) {
  try {
    const storedPending = storage?.getItem(pendingCreateSuccessKey)
    if (!storedPending) return null

    const parsedPending: unknown = JSON.parse(storedPending)
    if (isPendingCreateSuccess(parsedPending)) return parsedPending
    removeInvalidStoredValue(storage, pendingCreateSuccessKey)
    return null
  } catch {
    removeInvalidStoredValue(storage, pendingCreateSuccessKey)
    return null
  }
}

export function savePendingCreateSuccess(
  pending: PendingCreateSuccess,
  storage = getBrowserSessionStorage(),
) {
  try {
    storage?.setItem(pendingCreateSuccessKey, JSON.stringify(pending))
  } catch {
    // The mapped identity still prevents the Create form from being submitted again.
  }
}

export function clearPendingCreateSuccess(storage = getBrowserSessionStorage()) {
  try {
    storage?.removeItem(pendingCreateSuccessKey)
  } catch {
    // There is nothing else to clean up when storage is unavailable.
  }
}

export function loadPendingJoinSuccess(storage = getBrowserSessionStorage()) {
  try {
    const storedPending = storage?.getItem(pendingJoinSuccessKey)
    if (!storedPending) return null

    const parsedPending: unknown = JSON.parse(storedPending)
    if (isPendingJoinSuccess(parsedPending)) return parsedPending
    removeInvalidStoredValue(storage, pendingJoinSuccessKey)
    return null
  } catch {
    removeInvalidStoredValue(storage, pendingJoinSuccessKey)
    return null
  }
}

export function isPendingSuccessForAuthUser(
  pending: PendingCreateSuccess | PendingJoinSuccess | null,
  authUserId: string | undefined,
) {
  return Boolean(pending && authUserId && pending.authUserId === authUserId)
}

export function savePendingJoinSuccess(
  pending: PendingJoinSuccess,
  storage = getBrowserSessionStorage(),
) {
  try {
    storage?.setItem(pendingJoinSuccessKey, JSON.stringify(pending))
  } catch {
    // The mapped identity still prevents the Join form from being submitted again.
  }
}

export function clearPendingJoinSuccess(storage = getBrowserSessionStorage()) {
  try {
    storage?.removeItem(pendingJoinSuccessKey)
  } catch {
    // There is nothing else to clean up when browser storage is unavailable.
  }
}
