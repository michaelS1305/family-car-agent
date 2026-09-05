import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import {
  ChatApiError,
  getCarStatus,
  getChatHistory,
  type ChatMessage,
  type InternalUser,
} from '../api/apiClient'
import {
  createChatRequestRunner,
  pendingRequestNeedsRetry,
} from '../chat/chatSubmission'
import {
  CHAT_HEADER,
  CHAT_COMPOSER_LAYOUT,
  CHAT_PENDING_UI,
  carStatusPresentation,
  draftAfterFailedSend,
  draftAfterSendStarts,
  groupMessagesByDay,
  isNearScrollBottom,
  retryRequestAfterFailure,
  shouldAutoScroll,
  shouldRefreshCarStatus,
  shouldSubmitComposerKey,
  type CarStatusUiState,
} from '../chat/chatUi'
import { createCarStatusRealtimeSync } from '../carStatus/carStatusRealtime'
import { getSupabaseClient } from '../lib/supabase'
import { DashboardScreen } from './DashboardScreen'
import { APP_VERSION } from '../appVersion'

const suggestions = [
  'מי עם הרכב?',
  'הרכב פנוי היום בערב?',
  'תזמין לי את הרכב למחר',
  'מה ההזמנה הבאה?',
]

type PendingRequest = { requestId: string; message: string }

type DisplayMessage = ChatMessage & {
  localId: string
  pending?: boolean
  failed?: boolean
  retryRequest?: PendingRequest
}

function pendingStorageKey(authUserId: string) {
  return `family-car-agent:chat-pending:v1:${authUserId}`
}

function loadPendingRequest(authUserId: string): PendingRequest | null {
  try {
    const raw = sessionStorage.getItem(pendingStorageKey(authUserId))
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<PendingRequest>
    if (typeof value.requestId !== 'string' || typeof value.message !== 'string') {
      sessionStorage.removeItem(pendingStorageKey(authUserId))
      return null
    }
    return { requestId: value.requestId, message: value.message }
  } catch {
    sessionStorage.removeItem(pendingStorageKey(authUserId))
    return null
  }
}

function savePendingRequest(authUserId: string, request: PendingRequest | null) {
  const key = pendingStorageKey(authUserId)
  if (!request) {
    sessionStorage.removeItem(key)
    return
  }
  sessionStorage.setItem(key, JSON.stringify(request))
}

function readableChatError(error: unknown) {
  if (error instanceof ChatApiError) return error.message
  return 'לא הצלחנו לטעון את השיחה כרגע.'
}

function isRetryableWithSameRequest(error: unknown) {
  return error instanceof ChatApiError && (
    error.networkUncertain
    || error.code === 'CHAT_IN_PROGRESS'
    || error.code === 'CHAT_RECOVERY_REQUIRED'
    || error.code === 'CHAT_LEASE_LOST'
  )
}

export function MainAppScreen({ user, accessToken, authUserId, onLogout }: {
  user: InternalUser
  accessToken: string
  authUserId: string
  onLogout: () => Promise<void>
}) {
  const [draftMessage, setDraftMessage] = useState('')
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyReloadAttempt, setHistoryReloadAttempt] = useState(0)
  const [historyError, setHistoryError] = useState('')
  const [sending, setSending] = useState(false)
  const [carStatus, setCarStatus] = useState<CarStatusUiState>('loading')
  const [liveAssistantText, setLiveAssistantText] = useState('')
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const threadRef = useRef<HTMLElement | null>(null)
  const menuButtonRef = useRef<HTMLButtonElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const requestRunnerRef = useRef(createChatRequestRunner())
  const initialHistoryPositionedRef = useRef(false)
  const nearBottomRef = useRef(true)
  const scrollIntentRef = useRef<'auto' | 'smooth' | null>(null)
  const composingRef = useRef(false)
  const closeDashboard = useCallback(() => {
    setDashboardOpen(false)
    window.requestAnimationFrame(() => menuButtonRef.current?.focus({ preventScroll: true }))
  }, [])

  useEffect(() => {
    document.documentElement.classList.add('chat-shell-active')
    document.body.classList.add('chat-shell-active')
    return () => {
      document.documentElement.classList.remove('chat-shell-active')
      document.body.classList.remove('chat-shell-active')
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    initialHistoryPositionedRef.current = false

    getChatHistory(accessToken, { signal: controller.signal })
      .then((history) => {
        if (!active) return
        const displayHistory: DisplayMessage[] = history.map((message, index) => ({
          ...message,
          localId: `${message.request_id}-${message.role}-${index}`,
          failed: message.role === 'user' && message.request_status === 'failed',
        }))
        const pending = loadPendingRequest(authUserId)
        if (pending && pendingRequestNeedsRetry(pending, history)) {
          displayHistory.push({
            role: 'user',
            content: pending.message,
            created_at: new Date().toISOString(),
            localId: pending.requestId,
            failed: true,
            retryRequest: pending,
          })
        } else if (pending) {
          savePendingRequest(authUserId, null)
        }
        setMessages(displayHistory)
      })
      .catch((loadError: unknown) => {
        if (!active || (loadError instanceof DOMException && loadError.name === 'AbortError')) return
        setHistoryError(readableChatError(loadError))
      })
      .finally(() => {
        if (active) setHistoryLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [accessToken, authUserId, historyReloadAttempt])

  useEffect(() => {
    let active = true
    let requestSequence = 0
    let lastRefreshAt = Number.NEGATIVE_INFINITY
    let refreshInFlight: Promise<void> | null = null

    const refreshStatus = async (force = false) => {
      const now = Date.now()
      if (!force && !shouldRefreshCarStatus({
        isVisible: document.visibilityState !== 'hidden',
        now,
        lastRefreshAt,
      })) return

      if (refreshInFlight) return refreshInFlight

      lastRefreshAt = now
      const requestId = ++requestSequence
      refreshInFlight = (async () => {
        try {
          const result = await getCarStatus(accessToken)
          if (active && requestId === requestSequence) setCarStatus(result.status)
        } catch {
          if (active && requestId === requestSequence) setCarStatus('unknown')
        } finally {
          refreshInFlight = null
        }
      })()
      return refreshInFlight
    }

    const familyId = user.family_id
    const realtimeSync = familyId === null
      ? null
      : createCarStatusRealtimeSync({
          client: getSupabaseClient(),
          familyId,
          isVisible: () => document.visibilityState !== 'hidden',
          refreshStatus: () => refreshStatus(true),
        })

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        realtimeSync?.handleForeground()
        if (!realtimeSync) void refreshStatus()
      } else {
        realtimeSync?.handleBackground()
      }
    }
    const handleFocus = () => {
      realtimeSync?.handleForeground()
      if (!realtimeSync) void refreshStatus()
    }

    void refreshStatus(true)
    realtimeSync?.start()
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleFocus)
    return () => {
      active = false
      realtimeSync?.stop()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleFocus)
    }
  }, [accessToken, user.family_id])

  useLayoutEffect(() => {
    if (historyLoading) return
    const thread = threadRef.current
    if (!thread) return
    if (!initialHistoryPositionedRef.current) {
      if (shouldAutoScroll('initial', nearBottomRef.current)) thread.scrollTop = thread.scrollHeight
      initialHistoryPositionedRef.current = true
      nearBottomRef.current = true
      return
    }
    const behavior = scrollIntentRef.current
    if (!behavior) return
    thread.scrollTo({ top: thread.scrollHeight, behavior })
    scrollIntentRef.current = null
  }, [historyLoading, messages, sending])

  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const styles = window.getComputedStyle(textarea)
    const lineHeight = Number.parseFloat(styles.lineHeight) || 24
    const padding = Number.parseFloat(styles.paddingTop) + Number.parseFloat(styles.paddingBottom)
    const maxHeight = (lineHeight * 5) + padding
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [draftMessage])

  const submit = async (requestToRetry?: PendingRequest) => {
    if (sending || requestRunnerRef.current.isActive()) return
    const message = (requestToRetry?.message ?? draftMessage).trim()
    if (!message) return
    const request = requestToRetry ?? { requestId: crypto.randomUUID(), message }

    await requestRunnerRef.current.run(accessToken, request, {
      onStart: () => {
        setSending(true)
        setDraftMessage((current) => draftAfterSendStarts(current, request.message))
        savePendingRequest(authUserId, request)
        scrollIntentRef.current = 'smooth'
        setMessages((current) => {
          if (current.some((item) => item.localId === request.requestId)) {
            return current.map((item) => item.localId === request.requestId
              ? { ...item, pending: true, failed: false, retryRequest: undefined }
              : item)
          }
          return [...current, {
            role: 'user',
            content: message,
            created_at: new Date().toISOString(),
            localId: request.requestId,
            pending: true,
          }]
        })
      },
      onSuccess: (result) => {
        const thread = threadRef.current
        const wasNearBottom = thread ? isNearScrollBottom(thread) : nearBottomRef.current
        if (shouldAutoScroll('assistant-response', wasNearBottom)) scrollIntentRef.current = 'smooth'
        setMessages((current) => [
          ...current.map((item) => item.localId === request.requestId
            ? { ...item, pending: false, failed: false, retryRequest: undefined }
            : item),
          { ...result.assistant_message, localId: `${request.requestId}-assistant` },
        ])
        setLiveAssistantText(result.assistant_message.content)
        savePendingRequest(authUserId, null)
      },
      onError: (sendError) => {
        setDraftMessage((current) => draftAfterFailedSend(current))
        const canRetrySameRequest = isRetryableWithSameRequest(sendError)
        if (!canRetrySameRequest) {
          savePendingRequest(authUserId, null)
        }
        setMessages((current) => current.map((item) => item.localId === request.requestId
          ? {
              ...item,
              pending: false,
              failed: true,
              retryRequest: retryRequestAfterFailure(request, canRetrySameRequest),
            }
          : item))
      },
      onFinish: () => setSending(false),
    })
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const shouldSubmit = shouldSubmitComposerKey({
      key: event.key,
      shiftKey: event.shiftKey,
      isComposing: composingRef.current || event.nativeEvent.isComposing,
    })
    if (!shouldSubmit) return
    event.preventDefault()
    if (!historyLoading && !sending && draftMessage.trim()) void submit()
  }

  const messageDays = groupMessagesByDay(messages)
  const displayedCarStatus = carStatusPresentation(carStatus)

  return (
    <main className="main-chat-screen" dir="rtl">
      <header className="main-chat-header" aria-hidden={dashboardOpen} inert={dashboardOpen}>
        <button ref={menuButtonRef} className="chat-menu-button" type="button" aria-label={CHAT_HEADER.menuLabel} onClick={() => setDashboardOpen(true)}>
          <span className="chat-menu-icon" aria-hidden="true">
            {Array.from({ length: CHAT_HEADER.menuLines }, (_, index) => <i key={index} />)}
          </span>
        </button>
        <strong className="main-chat-title">{CHAT_HEADER.title}</strong>
        <div className={`car-status-pill is-${displayedCarStatus.tone}`} aria-label={`מצב הרכב: ${displayedCarStatus.label}`}>
          <i aria-hidden="true" />
          <span>{displayedCarStatus.label}</span>
        </div>
      </header>

      <section
        className="chat-thread"
        ref={threadRef}
        aria-busy={historyLoading || sending}
        aria-label="השיחה"
        aria-hidden={dashboardOpen}
        inert={dashboardOpen}
        onScroll={(event) => { nearBottomRef.current = isNearScrollBottom(event.currentTarget) }}
      >
        {historyLoading && <div className="chat-loading" role="status">טוענים את השיחה…</div>}
        {!historyLoading && historyError && (
          <div className="chat-history-error" role="alert">
            <span>{historyError}</span>
            <button type="button" onClick={() => {
              setHistoryLoading(true)
              setHistoryError('')
              setHistoryReloadAttempt((value) => value + 1)
            }}>
              טען שוב
            </button>
          </div>
        )}
        {!historyLoading && !historyError && messages.length === 0 && (
          <div className="chat-empty-state">
            <p>העוזר המשפחתי לרכב</p>
            <h1>איך אפשר לעזור?</h1>
            <div className="chat-suggestions" aria-label="הצעות לשאלות">
              {suggestions.map((suggestion) => (
                <button type="button" key={suggestion} onClick={() => setDraftMessage(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messageDays.map((day) => (
          <section className="chat-day-group" key={day.key}>
            {day.label && (
              <div className="chat-day-separator" aria-hidden="true">
                <span>{day.label}</span>
              </div>
            )}
            {day.minuteGroups.map((group) => (
              <div className="chat-time-group" key={group.key}>
                {group.messages.map((message) => (
                  <article className={`chat-message chat-message-${message.role}`} key={message.localId}>
                    <div
                      className={`chat-bubble chat-bubble-${message.role}${message.pending ? ' is-pending' : ''}${message.failed ? ' is-failed' : ''}`}
                      dir="auto"
                    >
                      {message.content}
                    </div>
                    {message.failed && (
                      <div className="chat-message-failure" role="status">
                        <span>לא נשלח</span>
                        {message.retryRequest && (
                          <button type="button" disabled={sending} onClick={() => void submit(message.retryRequest)}>
                            נסה שוב
                          </button>
                        )}
                      </div>
                    )}
                  </article>
                ))}
                {group.label && <time className="chat-time-label" dateTime={group.dateTime}>{group.label}</time>}
              </div>
            ))}
          </section>
        ))}
        {sending && (
          <div className="chat-typing" role="status" aria-label={CHAT_PENDING_UI.typingLabel}>
            <span className="chat-typing-dots" aria-hidden="true">
              {Array.from({ length: CHAT_PENDING_UI.typingDotCount }, (_, index) => (
                <i key={index} />
              ))}
            </span>
          </div>
        )}
      </section>

      <p className="visually-hidden" aria-live="polite" aria-atomic="true" aria-hidden={dashboardOpen}>{liveAssistantText}</p>

      <form className="chat-composer" aria-hidden={dashboardOpen} inert={dashboardOpen} onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}>
        <div className={CHAT_COMPOSER_LAYOUT.fieldClassName}>
          <textarea
            ref={textareaRef}
            rows={1}
            value={draftMessage}
            onChange={(event) => {
              setDraftMessage(event.target.value)
            }}
            onKeyDown={handleComposerKeyDown}
            onCompositionStart={() => { composingRef.current = true }}
            onCompositionEnd={() => { composingRef.current = false }}
            placeholder="אפשר לשאול אותי על הרכב..."
            aria-label="הודעה"
            maxLength={4000}
            disabled={historyLoading}
          />
        </div>
        <button
          className={CHAT_COMPOSER_LAYOUT.sendClassName}
          type="submit"
          aria-label={sending ? 'ההודעה נשלחת' : 'שליחה'}
          disabled={historyLoading || sending || !draftMessage.trim()}
        >
          <span aria-hidden="true">←</span>
        </button>
      </form>

      <DashboardScreen
        open={dashboardOpen}
        userName={user.name}
        version={APP_VERSION}
        onClose={closeDashboard}
        onLogout={onLogout}
      />
    </main>
  )
}
