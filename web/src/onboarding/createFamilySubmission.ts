import {
  createFamily,
  OnboardingApiError,
  type CreateFamilyPayload,
} from '../api/apiClient.ts'

type SubmitterDependencies = {
  createRequest?: typeof createFamily
  clearDraft: () => void
  markCreated: (payload: CreateFamilyPayload) => void
  recheckIdentity: () => void
}

export function createCreateFamilySubmitter({
  createRequest = createFamily,
  clearDraft,
  markCreated,
  recheckIdentity,
}: SubmitterDependencies) {
  let submitting = false

  return async (accessToken: string, payload: CreateFamilyPayload) => {
    if (submitting) return { status: 'ignored' as const }
    submitting = true

    try {
      await createRequest(accessToken, payload)
      markCreated(payload)
      recheckIdentity()
      return { status: 'created' as const }
    } catch (error) {
      if (
        error instanceof OnboardingApiError
        && error.code === 'AUTH_USER_ALREADY_MAPPED'
      ) {
        clearDraft()
        recheckIdentity()
        return { status: 'already-mapped' as const }
      }
      throw error
    } finally {
      submitting = false
    }
  }
}
