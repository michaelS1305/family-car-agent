import { useEffect, useRef, useState } from 'react'
import {
  ApiRequestError,
  getCarHistory,
  type CarHistory,
} from '../api/apiClient'
import { formatHistoryDate, formatHistoryTime } from '../historyTime'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'

function historyError(error: unknown) {
  return error instanceof ApiRequestError
    ? error.message
    : 'לא הצלחנו לטעון את היסטוריית הרכב.'
}

export function HistoryScreen({
  accessToken,
  open,
  refreshVersion,
  onBack,
}: {
  accessToken: string
  open: boolean
  refreshVersion: number
  onBack: () => void
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const [history, setHistory] = useState<CarHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadAttempt, setReloadAttempt] = useState(0)

  useEffect(() => {
    if (open) backButtonRef.current?.focus({ preventScroll: true })
  }, [open])

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let active = true
    getCarHistory(accessToken, { signal: controller.signal })
      .then((result) => {
        if (!active) return
        setHistory(result)
        setError('')
      })
      .catch((requestError: unknown) => {
        if (!active || (requestError instanceof DOMException && requestError.name === 'AbortError')) return
        setError(historyError(requestError))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [accessToken, open, refreshVersion, reloadAttempt])

  const retry = () => {
    setLoading(true)
    setError('')
    setReloadAttempt((value) => value + 1)
  }

  return (
    <section
      className={`category-placeholder-screen history-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="היסטוריה"
      aria-hidden={!open}
      inert={!open}
    >
      <header className="dashboard-header category-placeholder-header">
        <button ref={backButtonRef} type="button" onClick={onBack} aria-label="חזרה ללוח הבקרה">
          <span aria-hidden="true">×</span>
        </button>
        <h1>Family Car Agent</h1>
        <span aria-hidden="true" />
      </header>

      <div className="history-screen-scroll">
        <div className="family-screen-title history-screen-title">
          <DashboardCategoryIcon icon="history" />
          <h2>היסטוריה</h2>
        </div>

        {loading ? <p className="family-screen-state" role="status">טוענים היסטוריה…</p> : null}
        {!loading && error ? (
          <div className="family-screen-error" role="alert">
            <p>{error}</p>
            <button type="button" onClick={retry}>נסו שוב</button>
          </div>
        ) : null}

        {!loading && !error && history ? (
          <div className="history-content">
            {history.active_usage ? (
              <section className="history-current is-active" aria-label="הרכב כרגע בשימוש">
                <span><i aria-hidden="true" /> הרכב כרגע בשימוש</span>
                <strong>{history.active_usage.name}</strong>
                <p>נלקח ב־{formatHistoryDate(history.active_usage.started_at)}, {formatHistoryTime(history.active_usage.started_at)}</p>
              </section>
            ) : (
              <section className="history-current is-available" aria-label="הרכב זמין כעת">
                <span><i aria-hidden="true" /> הרכב זמין כעת</span>
              </section>
            )}

            {history.recent_usage.length > 0 ? (
              <section className="history-completed" aria-labelledby="recent-usage-title">
                <h3 id="recent-usage-title">שימושים אחרונים</h3>
                <div className="history-list">
                  {history.recent_usage.map((usage) => {
                    return (
                      <article className="history-card" key={`${usage.name}|${usage.started_at}|${usage.ended_at}`}>
                        <strong>{usage.name}</strong>
                        <span>{formatHistoryDate(usage.started_at)}</span>
                        <time>{formatHistoryTime(usage.started_at)}–{formatHistoryTime(usage.ended_at)}</time>
                      </article>
                    )
                  })}
                </div>
              </section>
            ) : history.active_usage ? null : (
              <p className="history-empty">אין עדיין היסטוריית שימוש ברכב</p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  )
}
