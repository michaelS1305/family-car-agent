import { useEffect, useRef, useState } from 'react'
import type { PushConfig } from '../api/apiClient'
import {
  activatePushNotifications,
  currentNotificationPermission,
  disableCurrentDevicePush,
  inspectCurrentDevicePushState,
  notificationPermissionLabel,
  preloadPushConfiguration,
  type CurrentDevicePushState,
} from '../push/pushNotifications'
import { useAppPreferences } from '../preferences/useAppPreferences'
import type {
  TextSizePreference,
  ThemePreference,
} from '../preferences/appPreferences'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'

const THEME_OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: 'system', label: 'מערכת' },
  { value: 'light', label: 'בהיר' },
  { value: 'dark', label: 'כהה' },
]

const TEXT_SIZE_OPTIONS: ReadonlyArray<{ value: TextSizePreference; label: string }> = [
  { value: 'small', label: 'קטן' },
  { value: 'normal', label: 'רגיל' },
  { value: 'large', label: 'גדול' },
]

type PushUiState = CurrentDevicePushState | 'loading' | 'enabling' | 'disabling' | 'error'

function permissionLabel() {
  return notificationPermissionLabel(currentNotificationPermission())
}

function notificationStateLabel(state: PushUiState) {
  if (state === 'subscribed') return 'פעיל במכשיר הזה'
  if (state === 'denied') return 'חסום בהגדרות המכשיר'
  if (state === 'unsupported') return 'לא נתמך'
  if (state === 'loading') return 'בודקים…'
  if (state === 'enabling') return 'מפעילים…'
  if (state === 'disabling') return 'מכבים…'
  if (state === 'error') return 'לא הצלחנו לבדוק'
  return 'כבוי במכשיר הזה'
}

export function SettingsScreen({
  open,
  userName,
  accessToken,
  onBack,
  onOpenFamily,
  onLogout,
}: {
  open: boolean
  userName: string
  accessToken: string
  onBack: () => void
  onOpenFamily: () => void
  onLogout: () => Promise<void>
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const { theme, textSize, setTheme, setTextSize } = useAppPreferences()
  const [pushState, setPushState] = useState<PushUiState>('loading')
  const [pushConfig, setPushConfig] = useState<PushConfig | null>(null)
  const [pushError, setPushError] = useState('')
  const [pushLoadAttempt, setPushLoadAttempt] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const [permission, setPermission] = useState(permissionLabel)

  useEffect(() => {
    if (open) backButtonRef.current?.focus({ preventScroll: true })
  }, [open])

  useEffect(() => {
    if (!open) return
    let active = true
    void Promise.resolve().then(async () => {
      if (!active) return
      setPushError('')
      setPermission(permissionLabel())
      try {
        const deviceState = await inspectCurrentDevicePushState()
        if (!active) return
        setPushState(deviceState)
        if (deviceState === 'unsupported' || deviceState === 'denied') return
        const config = await preloadPushConfiguration(accessToken)
        if (!active) return
        if (!config.enabled || !config.public_vapid_key) {
          setPushConfig(null)
          setPushError('שירות ההתראות אינו זמין כרגע.')
          return
        }
        setPushConfig(config)
      } catch {
        if (!active) return
        setPushState('error')
        setPushError('לא הצלחנו לבדוק את ההתראות כרגע.')
      }
    })
    return () => { active = false }
  }, [accessToken, open, pushLoadAttempt])

  const enablePush = () => {
    if (!pushConfig || pushState === 'enabling') {
      setPushError('לא הצלחנו להכין את ההתראות. נסו שוב.')
      return
    }
    if (pushState === 'denied') {
      setPushError('כדי להפעיל התראות, יש לאפשר אותן בהגדרות האייפון.')
      return
    }
    setPushState('enabling')
    setPushError('')
    void activatePushNotifications(accessToken, pushConfig)
      .then((result) => {
        setPermission(permissionLabel())
        if (result.status === 'enabled') setPushState('subscribed')
        else if (result.status === 'denied') setPushState('denied')
        else if (result.status === 'unsupported') setPushState('unsupported')
        else {
          setPushState('error')
          setPushError('שירות ההתראות אינו זמין כרגע.')
        }
      })
      .catch(() => {
        setPushState('error')
        setPushError('לא הצלחנו להפעיל את ההתראות. נסו שוב.')
      })
  }

  const disablePush = async () => {
    if (pushState === 'disabling') return
    setPushState('disabling')
    setPushError('')
    try {
      const result = await disableCurrentDevicePush(accessToken)
      if (result.serverRemoved && result.browserUnsubscribed) {
        setPushState('unsubscribed')
        return
      }
    } catch {
      // The same recoverable UI is used for browser and API failures.
    }
    setPushState('error')
    setPushError('לא הצלחנו לכבות את ההתראות במכשיר הזה. נסו שוב.')
  }

  const togglePush = () => {
    if (pushState === 'subscribed') {
      void disablePush()
      return
    }
    if (pushState === 'denied') {
      setPushError('כדי להפעיל התראות, יש לאפשר אותן בהגדרות האייפון.')
      return
    }
    if (pushState === 'unsupported') return
    enablePush()
  }

  const logout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      await onLogout()
    } finally {
      setLoggingOut(false)
    }
  }

  const pushBusy = pushState === 'loading' || pushState === 'enabling' || pushState === 'disabling'

  return (
    <section
      className={`category-placeholder-screen settings-screen${open ? ' is-open' : ''}`}
      dir="rtl"
      role="dialog"
      aria-modal="true"
      aria-label="הגדרות"
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

      <div className="settings-screen-scroll">
        <div className="family-screen-title settings-screen-title">
          <DashboardCategoryIcon icon="settings" />
          <h2>הגדרות</h2>
        </div>

        <div className="settings-sections">
          <section className="settings-group" aria-labelledby="settings-account-title">
            <h3 id="settings-account-title">חשבון</h3>
            <div className="settings-card">
              <div className="settings-row settings-row-static">
                <span>שם</span>
                <strong>{userName}</strong>
              </div>
              <button type="button" className="settings-row" onClick={onOpenFamily}>
                <span>המשפחה שלי</span>
                <span className="settings-row-value">פתיחת ניהול המשפחה ‹</span>
              </button>
              <button type="button" className="settings-row settings-row-danger" disabled={loggingOut} onClick={() => void logout()}>
                <span>{loggingOut ? 'מתנתקים…' : 'התנתקות'}</span>
              </button>
            </div>
          </section>

          <section className="settings-group" aria-labelledby="settings-display-title">
            <h3 id="settings-display-title">תצוגה</h3>
            <div className="settings-card">
              <div className="settings-control-row">
                <span>מצב תצוגה</span>
                <div className="settings-segmented" aria-label="מצב תצוגה">
                  {THEME_OPTIONS.map((option) => (
                    <button
                      type="button"
                      key={option.value}
                      aria-pressed={theme === option.value}
                      onClick={() => setTheme(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="settings-control-row">
                <span>גודל טקסט</span>
                <div className="settings-segmented" aria-label="גודל טקסט">
                  {TEXT_SIZE_OPTIONS.map((option) => (
                    <button
                      type="button"
                      key={option.value}
                      aria-pressed={textSize === option.value}
                      onClick={() => setTextSize(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section className="settings-group" aria-labelledby="settings-permissions-title">
            <h3 id="settings-permissions-title">הרשאות</h3>
            <div className="settings-card">
              <div className="settings-row settings-row-static">
                <span>התראות</span>
                <strong>{permission}</strong>
              </div>
              {pushState === 'denied' ? (
                <p className="settings-note">האישור חסום במכשיר. אפשר לשנות אותו בהגדרות האייפון.</p>
              ) : null}
            </div>
          </section>

          <section className="settings-group" aria-labelledby="settings-notifications-title">
            <h3 id="settings-notifications-title">התראות</h3>
            <div className="settings-card">
              <div className="settings-row settings-notification-row">
                <span>
                  <strong>עדכונים על הרכב</strong>
                  <small>{notificationStateLabel(pushState)}</small>
                </span>
                <button
                  type="button"
                  className="settings-switch"
                  role="switch"
                  aria-label="עדכונים על הרכב במכשיר הזה"
                  aria-checked={pushState === 'subscribed'}
                  aria-disabled={pushState === 'unsupported'}
                  disabled={pushBusy || pushState === 'unsupported'}
                  onClick={togglePush}
                >
                  <i aria-hidden="true" />
                </button>
              </div>
              {pushError ? (
                <div className="settings-inline-error" role="status">
                  <p>{pushError}</p>
                  {pushState === 'error' || !pushConfig ? (
                    <button type="button" onClick={() => {
                      setPushState('loading')
                      setPushLoadAttempt((value) => value + 1)
                    }}>נסו שוב</button>
                  ) : null}
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </section>
  )
}
