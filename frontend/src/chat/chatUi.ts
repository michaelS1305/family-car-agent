export type ScrollMetrics = {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

export const CHAT_HEADER = {
  title: 'Family Car Agent',
  menuLabel: 'פתיחת תפריט — בקרוב',
  menuLines: 3,
  // Placeholder until an existing API contract exposes live car availability.
  carStatus: { label: 'מצב לא זמין', tone: 'unknown' },
} as const

export function draftAfterSendStarts(currentDraft: string, sentMessage: string) {
  return currentDraft.trim() === sentMessage ? '' : currentDraft
}

export function draftAfterFailedSend(currentDraft: string) {
  return currentDraft
}

export function retryRequestAfterFailure<T>(request: T, canRetry: boolean) {
  return canRetry ? request : undefined
}

export type MessageTimeGroup<T> = {
  key: string
  label: string
  dateTime?: string
  messages: T[]
}

const messageTimeFormatter = new Intl.DateTimeFormat('he-IL', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

export function groupMessagesByMinute<T extends { created_at: string }>(
  messages: T[],
): MessageTimeGroup<T>[] {
  return messages.reduce<MessageTimeGroup<T>[]>((groups, message, index) => {
    const date = new Date(message.created_at)
    const timestamp = date.getTime()
    const validTimestamp = Number.isFinite(timestamp)
    const minuteKey = validTimestamp
      ? `minute-${Math.floor(timestamp / 60_000)}`
      : `invalid-${index}`
    const previous = groups.at(-1)
    if (previous?.key === minuteKey) {
      previous.messages.push(message)
      return groups
    }
    groups.push({
      key: minuteKey,
      label: validTimestamp ? messageTimeFormatter.format(date) : '',
      dateTime: validTimestamp ? date.toISOString() : undefined,
      messages: [message],
    })
    return groups
  }, [])
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
