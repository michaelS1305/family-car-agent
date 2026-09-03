export type ScrollMetrics = {
  scrollHeight: number
  scrollTop: number
  clientHeight: number
}

export const CHAT_HEADER = {
  title: 'Family Car Agent',
  menuLabel: 'פתיחת תפריט — בקרוב',
  menuLines: 3,
} as const

export const CHAT_COMPOSER_LAYOUT = {
  fieldClassName: 'chat-composer-field',
  sendClassName: 'chat-send-button',
} as const

export type CarStatusUiState = 'loading' | 'available' | 'occupied' | 'unknown'

export function carStatusPresentation(status: CarStatusUiState) {
  const presentations = {
    loading: { label: 'בודק…', tone: 'loading' },
    available: { label: 'פנוי', tone: 'available' },
    occupied: { label: 'תפוס', tone: 'occupied' },
    unknown: { label: 'לא ידוע', tone: 'unknown' },
  } as const
  return presentations[status]
}

export function shouldRefreshCarStatus({
  isVisible,
  now,
  lastRefreshAt,
  minimumInterval = 1_500,
}: {
  isVisible: boolean
  now: number
  lastRefreshAt: number
  minimumInterval?: number
}) {
  return isVisible && now - lastRefreshAt >= minimumInterval
}

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

export type MessageDayGroup<T> = {
  key: string
  label: string
  minuteGroups: MessageTimeGroup<T>[]
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

function localDateKey(date: Date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-')
}

export function formatMessageDayLabel(date: Date, now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const daysAgo = Math.round((today.getTime() - target.getTime()) / 86_400_000)
  if (daysAgo === 0) return 'היום'
  if (daysAgo === 1) return 'אתמול'
  return new Intl.DateTimeFormat('he-IL', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date)
}

export function groupMessagesByDay<T extends { created_at: string }>(
  messages: T[],
  now = new Date(),
): MessageDayGroup<T>[] {
  return messages.reduce<MessageDayGroup<T>[]>((days, message, index) => {
    const date = new Date(message.created_at)
    const validTimestamp = Number.isFinite(date.getTime())
    const key = validTimestamp ? localDateKey(date) : `invalid-${index}`
    const previous = days.at(-1)
    if (previous?.key === key) {
      previous.minuteGroups = groupMessagesByMinute([
        ...previous.minuteGroups.flatMap((group) => group.messages),
        message,
      ])
      return days
    }
    days.push({
      key,
      label: validTimestamp ? formatMessageDayLabel(date, now) : '',
      minuteGroups: groupMessagesByMinute([message]),
    })
    return days
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
