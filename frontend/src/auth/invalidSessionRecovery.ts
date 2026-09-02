type InvalidSessionRecoveryDependencies = {
  clearOnboardingDraft: () => void
  clearPendingCreateSuccess: () => void
  clearPendingJoinSuccess: () => void
  resetOnboardingForLogin: () => void
  invalidateAuthSession: (message: string) => Promise<void>
}

export function createInvalidSessionRecovery({
  clearOnboardingDraft,
  clearPendingCreateSuccess,
  clearPendingJoinSuccess,
  resetOnboardingForLogin,
  invalidateAuthSession,
}: InvalidSessionRecoveryDependencies) {
  let activeRecovery: Promise<void> | null = null

  return (message: string) => {
    if (activeRecovery) return activeRecovery

    clearOnboardingDraft()
    clearPendingCreateSuccess()
    clearPendingJoinSuccess()
    resetOnboardingForLogin()

    activeRecovery = invalidateAuthSession(message).finally(() => {
      activeRecovery = null
    })
    return activeRecovery
  }
}
