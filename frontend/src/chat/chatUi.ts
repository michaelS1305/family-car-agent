export type ScrollMetrics = {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

export function draftAfterSuccessfulSend(currentDraft: string, sentMessage: string) {
  return currentDraft === sentMessage ? '' : currentDraft
}

export function draftAfterFailedSend(currentDraft: string) {
  return currentDraft
}

export function retryRequestAfterFailure<T>(request: T, canRetry: boolean) {
  return canRetry ? request : undefined
}

export function shouldSubmitComposerKey({
  key,
  shiftKey,
  isComposing,
}: {
  key: string
  shiftKey: boolean
  isComposing: boolean
}) {
  return key === 'Enter' && !shiftKey && !isComposing
}

export function isNearScrollBottom(
  metrics: ScrollMetrics,
  threshold = 96,
) {
  const distanceFromBottom = (
    metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight
  )
  return distanceFromBottom <= threshold
}

export function shouldAutoScroll(
  reason: 'initial' | 'user-send' | 'assistant-response' | 'loading',
  wasNearBottom: boolean,
) {
  if (reason === 'initial' || reason === 'user-send') return true
  if (reason === 'assistant-response') return wasNearBottom
  return false
}
