import {
  completeJoinFamily,
  OnboardingApiError,
} from '../api/apiClient.ts'

type JoinCompleterDependencies = {
  completeRequest?: typeof completeJoinFamily
  clearDraft: () => void
  markJoined: (payload: { familyName: string; userName: string }) => void
  recheckIdentity: () => void
}

export function createJoinFamilyCompleter({
  completeRequest = completeJoinFamily,
  clearDraft,
  markJoined,
  recheckIdentity,
}: JoinCompleterDependencies) {
  return async (accessToken: string, userName: string, familyName: string) => {
    try {
      await completeRequest(accessToken, userName)
      markJoined({ familyName, userName })
      clearDraft()
      recheckIdentity()
      return { status: 'joined' as const }
    } catch (error) {
      if (
        error instanceof OnboardingApiError
        && error.code === 'AUTH_USER_ALREADY_MAPPED'
      ) {
        markJoined({ familyName, userName })
        clearDraft()
        recheckIdentity()
        return { status: 'already-mapped' as const }
      }
      throw error
    }
  }
}
