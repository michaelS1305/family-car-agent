import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  cancelReservation,
  createReservation,
  getReservations,
  updateReservation,
  type Reservation,
  type ReservationScopeFilter,
  type ReservationTimeFilter,
} from '../api/apiClient'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'
import { intervalFromForm, reservationFormValue, reservationPresentation, type ReservationFormValue } from '../reservationForm'

type EditorState =
  | { mode: 'list' }
  | { mode: 'create' }
  | { mode: 'edit'; reservation: Reservation }


function readableError(error: unknown) {
  return error instanceof ApiRequestError
    ? error.message
    : 'לא הצלחנו להשלים את הפעולה. נסו שוב.'
}

function ReservationForm({
  editor,
  saving,
  onCancel,
  onSave,
}: {
  editor: Exclude<EditorState, { mode: 'list' }>
  saving: boolean
  onCancel: () => void
  onSave: (value: ReservationFormValue) => Promise<void>
}) {
  const [form, setForm] = useState(() => reservationFormValue(
    editor.mode === 'edit' ? editor.reservation : undefined,
  ))
  const [error, setError] = useState('')
  const dateInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    dateInputRef.current?.focus({ preventScroll: true })
  }, [])

  const submit = async () => {
    if (!form.startDate || !form.endDate || !form.startTime || !form.endTime || saving) return
    setError('')
    try {
      await onSave(form)
    } catch (requestError) {
      setError(readableError(requestError))
    }
  }

  return (
    <section className="reservation-editor" aria-labelledby="reservation-editor-title">
      <h3 id="reservation-editor-title">
        {editor.mode === 'create' ? 'הוספת הזמנה' : 'עריכת הזמנה'}
      </h3>
      <form onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}>
        <fieldset className="reservation-datetime-group">
          <legend>התחלה</legend>
          <div className="reservation-time-fields">
            <label>
              <input
                aria-label="תאריך התחלה"
                ref={dateInputRef}
                type="date"
                required
                value={form.startDate}
                onChange={(event) => setForm((current) => ({ ...current, startDate: event.target.value }))}
              />
            </label>
            <label>
              <input
                aria-label="שעת התחלה"
                type="time"
                step="1"
                required
                value={form.startTime}
                onChange={(event) => setForm((current) => ({ ...current, startTime: event.target.value }))}
              />
            </label>
          </div>
        </fieldset>
        <fieldset className="reservation-datetime-group">
          <legend>סיום</legend>
          <div className="reservation-time-fields">
            <label>
              <input aria-label="תאריך סיום" type="date" required value={form.endDate}
                onChange={(event) => setForm((current) => ({ ...current, endDate: event.target.value }))} />
            </label>
            <label>
              <input
                aria-label="שעת סיום"
                type="time"
                step="1"
                required
                value={form.endTime}
                onChange={(event) => setForm((current) => ({ ...current, endTime: event.target.value }))}
              />
            </label>
          </div>
        </fieldset>
        {error ? <p className="reservation-form-error" role="alert">{error}</p> : null}
        <div className="reservation-form-actions">
          <button type="button" className="secondary" disabled={saving} onClick={onCancel}>ביטול</button>
          <button type="submit" disabled={saving || !form.startDate || !form.endDate || !form.startTime || !form.endTime}>
            {saving ? 'שומרים…' : 'שמירה'}
          </button>
        </div>
      </form>
    </section>
  )
}

export function ReservationCenterScreen({ accessToken, open, onBack }: {
  accessToken: string
  open: boolean
  onBack: () => void
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const addButtonRef = useRef<HTMLButtonElement | null>(null)
  const [timeFilter, setTimeFilter] = useState<ReservationTimeFilter>('future')
  const [scopeFilter, setScopeFilter] = useState<ReservationScopeFilter>('all')
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadAttempt, setReloadAttempt] = useState(0)
  const [editor, setEditor] = useState<EditorState>({ mode: 'list' })
  const [saving, setSaving] = useState(false)
  const [cancellingKey, setCancellingKey] = useState<string | null>(null)
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null)

  const closeEditor = () => {
    setEditor({ mode: 'list' })
    window.requestAnimationFrame(() => addButtonRef.current?.focus({ preventScroll: true }))
  }

  useEffect(() => {
    if (!open) return
    backButtonRef.current?.focus({ preventScroll: true })
  }, [open])

  useEffect(() => {
    if (!open || editor.mode !== 'list') return
    const controller = new AbortController()
    getReservations(accessToken, timeFilter, scopeFilter, { signal: controller.signal })
      .then(setReservations)
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError(readableError(requestError))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [accessToken, editor.mode, open, reloadAttempt, scopeFilter, timeFilter])

  useEffect(() => {
    if (!open || editor.mode === 'list') return
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopImmediatePropagation()
      closeEditor()
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [editor.mode, open])

  const emptyText = useMemo(() => {
    if (timeFilter === 'future') {
      return scopeFilter === 'mine' ? 'אין לך הזמנות עתידיות' : 'אין הזמנות עתידיות'
    }
    return scopeFilter === 'mine' ? 'אין לך הזמנות מהעבר' : 'אין הזמנות מהעבר'
  }, [scopeFilter, timeFilter])

  const saveEditor = async (form: ReservationFormValue) => {
    if (saving || editor.mode === 'list') return
    setSaving(true)
    try {
      const interval = intervalFromForm(form)
      if (editor.mode === 'create') {
        await createReservation(accessToken, interval)
        setTimeFilter('future')
        setScopeFilter('mine')
      } else {
        await updateReservation(accessToken, {
          start_time: editor.reservation.start_time,
          end_time: editor.reservation.end_time,
        }, interval)
      }
      setLoading(true)
      setError('')
      setEditor({ mode: 'list' })
      setReloadAttempt((value) => value + 1)
    } finally {
      setSaving(false)
    }
  }

  const cancelOne = async (reservation: Reservation) => {
    const key = `${reservation.start_time}|${reservation.end_time}`
    if (cancellingKey) return
    setCancellingKey(key)
    setError('')
    try {
      await cancelReservation(accessToken, {
        start_time: reservation.start_time,
        end_time: reservation.end_time,
      })
      setConfirmingKey(null)
      setReloadAttempt((value) => value + 1)
    } catch (requestError) {
      setError(readableError(requestError))
    } finally {
      setCancellingKey(null)
    }
  }

  const screenBack = editor.mode === 'list' ? onBack : closeEditor

  const selectTimeFilter = (value: ReservationTimeFilter) => {
    setLoading(true)
    setError('')
    setTimeFilter(value)
  }

  const selectScopeFilter = (value: ReservationScopeFilter) => {
    setLoading(true)
    setError('')
    setScopeFilter(value)
  }

  const reloadReservations = () => {
    setLoading(true)
    setError('')
    setReloadAttempt((value) => value + 1)
  }

  return (
    <section
      className={`category-placeholder-screen reservation-center-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="מרכז הזמנות"
      aria-hidden={!open}
      inert={!open}
    >
      <header className="dashboard-header category-placeholder-header">
        <button ref={backButtonRef} type="button" onClick={screenBack} aria-label={editor.mode === 'list' ? 'חזרה ללוח הבקרה' : 'חזרה למרכז ההזמנות'}>
          <span aria-hidden="true">×</span>
        </button>
        <h1>Family Car Agent</h1>
        <span aria-hidden="true" />
      </header>

      <div className="reservation-center-scroll">
        <div className="family-screen-title reservation-center-title">
          <DashboardCategoryIcon icon="calendar" />
          <h2>מרכז הזמנות</h2>
        </div>

        {editor.mode !== 'list' ? (
          <ReservationForm editor={editor} saving={saving} onCancel={closeEditor} onSave={saveEditor} />
        ) : (
          <>
            <div className="reservation-filters" aria-label="סינון הזמנות">
              <div role="group" aria-label="זמן ההזמנה">
                <button type="button" aria-pressed={timeFilter === 'future'} onClick={() => selectTimeFilter('future')}>עתידיות</button>
                <button type="button" aria-pressed={timeFilter === 'past'} onClick={() => selectTimeFilter('past')}>מהעבר</button>
              </div>
              <div role="group" aria-label="בעלות על ההזמנה">
                <button type="button" aria-pressed={scopeFilter === 'all'} onClick={() => selectScopeFilter('all')}>כולם</button>
                <button type="button" aria-pressed={scopeFilter === 'mine'} onClick={() => selectScopeFilter('mine')}>שלי</button>
              </div>
            </div>

            {error ? (
              <div className="family-screen-error reservation-list-error" role="alert">
                <p>{error}</p>
                <button type="button" onClick={reloadReservations}>נסו שוב</button>
              </div>
            ) : null}
            {loading ? <p className="family-screen-state" role="status">טוענים הזמנות…</p> : null}
            {!loading && !error && reservations.length === 0 ? <p className="reservation-empty">{emptyText}</p> : null}

            {!loading && reservations.length > 0 ? (
              <section className="reservation-list" aria-label="הזמנות">
                {reservations.map((reservation) => {
                  const key = `${reservation.start_time}|${reservation.end_time}`
                  const canModify = timeFilter === 'future' && reservation.is_mine
                  const presentation = reservationPresentation(reservation)
                  return (
                    <article className="reservation-card" key={key}>
                      <div>
                        <strong>{presentation.title}</strong>
                        <span dir={presentation.sameDay ? 'ltr' : 'rtl'}>{presentation.interval}</span>
                      </div>
                      <p>{reservation.is_mine ? 'ההזמנה שלי' : reservation.owner_name}</p>
                      {canModify ? (
                        <div className="reservation-card-actions">
                          <button type="button" aria-label={`עריכת ההזמנה של ${reservation.owner_name}`} onClick={() => setEditor({ mode: 'edit', reservation })}>עריכה</button>
                          {confirmingKey === key ? (
                            <span className="reservation-delete-confirm" role="group" aria-label="אישור מחיקת הזמנה">
                              <button type="button" disabled={cancellingKey === key} onClick={() => void cancelOne(reservation)}>כן, למחוק</button>
                              <button type="button" onClick={() => setConfirmingKey(null)}>לא</button>
                            </span>
                          ) : (
                            <button type="button" aria-label={`מחיקת ההזמנה של ${reservation.owner_name}`} onClick={() => setConfirmingKey(key)}>מחיקה</button>
                          )}
                        </div>
                      ) : null}
                    </article>
                  )
                })}
              </section>
            ) : null}

            <button ref={addButtonRef} type="button" className="reservation-add-button" onClick={() => setEditor({ mode: 'create' })}>
              הוספת הזמנה
            </button>
          </>
        )}
      </div>
    </section>
  )
}
