export function createJoinRequestRunner(
  setLoading: (loading: boolean) => void,
) {
  let requestInFlight = false

  return async (request: () => Promise<void>) => {
    if (requestInFlight) return { status: 'ignored' as const }
    requestInFlight = true
    setLoading(true)
    try {
      await request()
      return { status: 'completed' as const }
    } finally {
      requestInFlight = false
      setLoading(false)
    }
  }
}
