// Retain the accepted state between renders so a rapid second click cannot send
// another destructive request. A failed/uncertain response remains retryable.
export function createDeletionSubmissionGuard() {
  let running = false
  let accepted = false
  return async (operation: () => Promise<boolean>) => {
    if (running || accepted) return
    running = true
    try { accepted = await operation() } finally { running = false }
  }
}
