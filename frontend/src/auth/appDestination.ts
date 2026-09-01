import type { BackendIdentityStatus } from './authContext'
import type { OnboardingFlow } from './onboardingDraft'
import type { CarPlaySetupStatus } from '../api/apiClient'

export type AppDestination =
  | 'loading'
  | 'error'
  | 'main'
  | 'carplay_setup'
  | 'create_success'
  | 'join_success'
  | 'create_processing'
  | 'join_processing'
  | 'welcome'
  | 'auth'
  | 'onboarding'

type AppDestinationInput = {
  isInitializing: boolean
  identityStatus: BackendIdentityStatus
  intent: OnboardingFlow | null
  hasCurrentUser: boolean
  carPlaySetupStatus?: CarPlaySetupStatus
  hasPendingCreateSuccess: boolean
  hasPendingJoinSuccess: boolean
  finalProcessingFlow?: OnboardingFlow | null
}

export function resolveAppDestination({
  isInitializing,
  identityStatus,
  intent,
  hasCurrentUser,
  carPlaySetupStatus,
  hasPendingCreateSuccess,
  hasPendingJoinSuccess,
  finalProcessingFlow = null,
}: AppDestinationInput): AppDestination {
  if (identityStatus === 'error') return 'error'

  if (identityStatus === 'authenticated_mapped') {
    if (!hasCurrentUser) return 'error'
    if (hasPendingCreateSuccess) return 'create_success'
    if (hasPendingJoinSuccess) return 'join_success'
    if (carPlaySetupStatus === 'pending') return 'carplay_setup'
    if (carPlaySetupStatus === 'completed' || carPlaySetupStatus === 'skipped') return 'main'
    return 'error'
  }

  if (!isInitializing && identityStatus === 'unauthenticated') {
    return intent ? 'auth' : 'welcome'
  }

  if (hasPendingCreateSuccess || finalProcessingFlow === 'create') {
    return 'create_processing'
  }
  if (hasPendingJoinSuccess || finalProcessingFlow === 'join') {
    return 'join_processing'
  }

  if (isInitializing || identityStatus === 'checking') return 'loading'
  return intent ? 'onboarding' : 'welcome'
}
