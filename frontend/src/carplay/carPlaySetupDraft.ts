export const carPlaySetupLastStep = 15
export const carPlaySetupActionSteps = 14

export type CarPlaySetupDraft = {
  version: 2
  authUserId: string
  currentStep: number
}

type SetupStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

const storageKey = 'family-car-agent:carplay-setup'

function browserStorage(): SetupStorage | null {
  return typeof window === 'undefined' ? null : window.sessionStorage
}

function isDraft(value: unknown): value is CarPlaySetupDraft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Partial<CarPlaySetupDraft>
  return (
    draft.version === 2
    && typeof draft.authUserId === 'string'
    && draft.authUserId.length > 0
    && Number.isInteger(draft.currentStep)
    && Number(draft.currentStep) >= 0
    && Number(draft.currentStep) <= carPlaySetupLastStep
  )
}

export function loadCarPlaySetupStep(
  authUserId: string,
  storage = browserStorage(),
) {
  try {
    const raw = storage?.getItem(storageKey)
    if (!raw) return 0
    const parsed: unknown = JSON.parse(raw)
    if (isDraft(parsed) && parsed.authUserId === authUserId) {
      return parsed.currentStep
    }
    storage?.removeItem(storageKey)
  } catch {
    try {
      storage?.removeItem(storageKey)
    } catch {
      // Progress simply starts over if browser storage is unavailable.
    }
  }
  return 0
}

export function saveCarPlaySetupStep(
  authUserId: string,
  currentStep: number,
  storage = browserStorage(),
) {
  if (!Number.isInteger(currentStep) || currentStep < 0 || currentStep > carPlaySetupLastStep) {
    return
  }
  try {
    storage?.setItem(storageKey, JSON.stringify({
      version: 2,
      authUserId,
      currentStep,
    } satisfies CarPlaySetupDraft))
  } catch {
    // The wizard remains usable without persisted progress.
  }
}

export function nextCarPlaySetupStep(currentStep: number) {
  return Math.min(carPlaySetupLastStep, Math.max(0, currentStep) + 1)
}

export function previousCarPlaySetupStep(currentStep: number) {
  return Math.max(0, Math.min(carPlaySetupLastStep, currentStep) - 1)
}

export function clearCarPlaySetupDraft(storage = browserStorage()) {
  try {
    storage?.removeItem(storageKey)
  } catch {
    // There is nothing else to clear when browser storage is unavailable.
  }
}

export async function copyConnectionCode(
  connectionCode: string,
  clipboard: Pick<Clipboard, 'writeText'> = navigator.clipboard,
) {
  await clipboard.writeText(connectionCode)
}
