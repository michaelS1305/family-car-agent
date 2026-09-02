import { useEffect, useRef, useState } from 'react'
import {
  ChatApiError,
  getChatHistory,
  type ChatMessage,
  type InternalUser,
} from '../api/apiClient'
import {
  createChatRequestRunner,
  pendingRequestNeedsRetry,
} from '../chat/chatSubmission'

const suggestions = [
  'מי עם הרכב?',
  'הרכב פנוי היום בערב?',
  'תזמין לי את הרכב למחר',
  'מה ההזמנה הבאה?',
]

type DisplayMessage = ChatMessage & {
  localId: string
  pending?: boolean
}

type PendingRequest = {
  requestId: string
  message: string
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
  return 'לא הצלחנו לקבל תשובה כרגע. אפשר לנסות שוב.'
}

export function MainAppScreen({
  user,
  accessToken,
  authUserId,
}: {
  user: InternalUser
  accessToken: string
  authUserId: string
}) {
  const [draftMessage, setDraftMessage] = useState('')
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [retryRequest, setRetryRequest] = useState<PendingRequest | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)
  const requestRunnerRef = useRef(createChatRequestRunner())

  useEffect(() => {
    const controller = new AbortController()
    getChatHistory(accessToken, { signal: controller.signal })
      .then((history) => {
        setMessages(history.map((message, index) => ({
          ...message,
          localId: `${message.request_id}-${message.role}-${index}`,
        })))
        const pending = loadPendingRequest(authUserId)
        if (pending) {
          if (!pendingRequestNeedsRetry(pending, history)) {
            savePendingRequest(authUserId, null)
          } else {
            setRetryRequest(pending)
            setDraftMessage(pending.message)
            setError('השליחה הקודמת לא הסתיימה בוודאות. אפשר לנסות שוב בבטחה.')
          }
        }
      })
      .catch((loadError: unknown) => {
        if (loadError instanceof DOMException && loadError.name === 'AbortError') return
        setError(readableChatError(loadError))
      })
      .finally(() => setHistoryLoading(false))
    return () => controller.abort()
  }, [accessToken, authUserId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [historyLoading, messages, sending])

  const submit = async (requestToRetry?: PendingRequest) => {
    if (sending || requestRunnerRef.current.isActive()) return
    const message = (requestToRetry?.message ?? draftMessage).trim()
    if (!message) return
    const request = requestToRetry ?? {
      requestId: crypto.randomUUID(),
      message,
    }

    await requestRunnerRef.current.run(accessToken, request, {
      onStart: () => {
        setSending(true)
        setError('')
        setRetryRequest(request)
        savePendingRequest(authUserId, request)
        setMessages((current) => {
          if (current.some((item) => item.localId === request.requestId)) return current
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
        setMessages((current) => [
          ...current.map((item) => (
            item.localId === request.requestId ? { ...item, pending: false } : item
          )),
          {
            ...result.assistant_message,
            localId: `${request.requestId}-assistant`,
          },
        ])
        setDraftMessage('')
        setRetryRequest(null)
        savePendingRequest(authUserId, null)
      },
      onError: (sendError) => {
        setError(readableChatError(sendError))
        setDraftMessage(request.message)
        const canRetrySameRequest = (
          sendError instanceof ChatApiError
          && (
            sendError.networkUncertain
            || sendError.code === 'CHAT_IN_PROGRESS'
            || sendError.code === 'CHAT_RECOVERY_REQUIRED'
            || sendError.code === 'CHAT_LEASE_LOST'
          )
        )
        if (!canRetrySameRequest) {
          setRetryRequest(null)
          savePendingRequest(authUserId, null)
        }
        setMessages((current) => current.map((item) => (
          item.localId === request.requestId ? { ...item, pending: false } : item
        )))
      },
      onFinish: () => setSending(false),
    })
  }

  return (
    <main className="main-chat-screen" dir="rtl">
      <header className="main-chat-header">
        <div>
          <strong>Family Car Agent</strong>
          <span>היי, {user.name}</span>
        </div>
        <button type="button" aria-label="הגדרות — בקרוב" disabled>•••</button>
      </header>

      <section className="chat-thread" aria-live="polite" aria-busy={historyLoading || sending}>
        {historyLoading && <div className="chat-loading">טוענים את השיחה…</div>}
        {!historyLoading && messages.length === 0 && (
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
        {messages.map((message) => (
          <article
            className={`chat-bubble chat-bubble-${message.role}${message.pending ? ' is-pending' : ''}`}
            key={message.localId}
          >
            {message.content}
          </article>
        ))}
        {sending && <div className="chat-typing" role="status">חושב…</div>}
        <div ref={endRef} />
      </section>

      {error && (
        <div className="chat-error" role="alert">
          <span>{error}</span>
          {retryRequest && (
            <button type="button" disabled={sending} onClick={() => void submit(retryRequest)}>
              ניסיון נוסף
            </button>
          )}
        </div>
      )}

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <input
          value={draftMessage}
          onChange={(event) => {
            setDraftMessage(event.target.value)
            if (retryRequest && event.target.value !== retryRequest.message) {
              setRetryRequest(null)
              savePendingRequest(authUserId, null)
            }
          }}
          placeholder="אפשר לשאול אותי על הרכב..."
          aria-label="הודעה"
          maxLength={4000}
          disabled={historyLoading}
        />
        <button
          type="submit"
          aria-label="שליחה"
          disabled={historyLoading || sending || !draftMessage.trim()}
        >
          ←
        </button>
      </form>
    </main>
  )
}
