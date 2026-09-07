import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { PushConfig } from '../api/apiClient'
import { LEGAL_DOCUMENTS, type LegalDocumentKind } from '../legal/legalDocuments'
import {
  activatePushNotifications, currentNotificationPermission, disableCurrentDevicePush,
  inspectCurrentDevicePushState, notificationPermissionLabel, preloadPushConfiguration,
  type CurrentDevicePushState,
} from '../push/pushNotifications'
import { useAppPreferences } from '../preferences/useAppPreferences'
import type { TextSizePreference, ThemePreference } from '../preferences/appPreferences'
import { DashboardCategoryIcon } from './DashboardCategoryIcon'
import { LegalDocumentScreen } from './LegalDocumentScreen'

const THEME_OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: 'system', label: 'מערכת' }, { value: 'light', label: 'בהיר' }, { value: 'dark', label: 'כהה' },
]
const TEXT_SIZE_OPTIONS: ReadonlyArray<{ value: TextSizePreference; label: string }> = [
  { value: 'small', label: 'קטן' }, { value: 'normal', label: 'רגיל' }, { value: 'large', label: 'גדול' },
]
type PushUiState = CurrentDevicePushState | 'loading' | 'enabling' | 'disabling' | 'error'
type SettingsPage = 'main' | 'location' | 'carplay' | 'privacy' | 'terms' | 'about' | 'contact' | 'privacy-policy' | 'terms-document'

function permissionLabel() { return notificationPermissionLabel(currentNotificationPermission()) }
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

function SettingsDetail({ title, children, onBack }: { title: string; children: ReactNode; onBack: () => void }) {
  return <div className="settings-detail"><header className="settings-detail-header"><button type="button" onClick={onBack} aria-label="חזרה להגדרות">→</button><h2>{title}</h2><span aria-hidden="true" /></header><div className="settings-detail-content">{children}</div></div>
}

export function SettingsScreen({ open, userName, userEmail, accessToken, version, onBack, onOpenFamily, onLogout }: {
  open: boolean; userName: string; userEmail: string; accessToken: string; version: string
  onBack: () => void; onOpenFamily: () => void; onLogout: () => Promise<void>
}) {
  const backButtonRef = useRef<HTMLButtonElement | null>(null)
  const { theme, textSize, setTheme, setTextSize } = useAppPreferences()
  const [page, setPage] = useState<SettingsPage>('main')
  const [pushState, setPushState] = useState<PushUiState>('loading')
  const [pushConfig, setPushConfig] = useState<PushConfig | null>(null)
  const [pushError, setPushError] = useState('')
  const [pushLoadAttempt, setPushLoadAttempt] = useState(0)
  const [loggingOut, setLoggingOut] = useState(false)
  const [permission, setPermission] = useState(permissionLabel)

  useEffect(() => { if (open) backButtonRef.current?.focus({ preventScroll: true }) }, [open])
  useEffect(() => {
    if (open) return
    const frame = window.requestAnimationFrame(() => setPage('main'))
    return () => window.cancelAnimationFrame(frame)
  }, [open])
  useEffect(() => {
    if (!open) return
    let active = true
    void Promise.resolve().then(async () => {
      if (!active) return
      setPushError(''); setPermission(permissionLabel())
      try {
        const deviceState = await inspectCurrentDevicePushState()
        if (!active) return
        setPushState(deviceState)
        if (deviceState === 'unsupported' || deviceState === 'denied') return
        const config = await preloadPushConfiguration(accessToken)
        if (!active) return
        if (!config.enabled || !config.public_vapid_key) { setPushConfig(null); setPushError('שירות ההתראות אינו זמין כרגע.'); return }
        setPushConfig(config)
      } catch { if (active) { setPushState('error'); setPushError('לא הצלחנו לבדוק את ההתראות כרגע.') } }
    })
    return () => { active = false }
  }, [accessToken, open, pushLoadAttempt])

  const enablePush = () => {
    if (!pushConfig || pushState === 'enabling') { setPushError('לא הצלחנו להכין את ההתראות. נסו שוב.'); return }
    if (pushState === 'denied') { setPushError('כדי להפעיל התראות, יש לאפשר אותן בהגדרות האייפון.'); return }
    setPushState('enabling'); setPushError('')
    void activatePushNotifications(accessToken, pushConfig).then((result) => {
      setPermission(permissionLabel())
      if (result.status === 'enabled') setPushState('subscribed')
      else if (result.status === 'denied') setPushState('denied')
      else if (result.status === 'unsupported') setPushState('unsupported')
      else { setPushState('error'); setPushError('שירות ההתראות אינו זמין כרגע.') }
    }).catch(() => { setPushState('error'); setPushError('לא הצלחנו להפעיל את ההתראות. נסו שוב.') })
  }
  const disablePush = async () => {
    if (pushState === 'disabling') return
    setPushState('disabling'); setPushError('')
    try { const result = await disableCurrentDevicePush(accessToken); if (result.serverRemoved && result.browserUnsubscribed) { setPushState('unsubscribed'); return } } catch { /* recoverable */ }
    setPushState('error'); setPushError('לא הצלחנו לכבות את ההתראות במכשיר הזה. נסו שוב.')
  }
  const togglePush = () => {
    if (pushState === 'subscribed') { void disablePush(); return }
    if (pushState === 'denied') { setPushError('כדי להפעיל התראות, יש לאפשר אותן בהגדרות האייפון.'); return }
    if (pushState !== 'unsupported') enablePush()
  }
  const logout = async () => { if (loggingOut) return; setLoggingOut(true); try { await onLogout() } finally { setLoggingOut(false) } }
  const pushBusy = pushState === 'loading' || pushState === 'enabling' || pushState === 'disabling'
  const detailBack = () => setPage('main')

  let content: ReactNode
  if (page === 'privacy-policy' || page === 'terms-document') {
    const kind: LegalDocumentKind = page === 'privacy-policy' ? 'privacy' : 'terms'
    content = <LegalDocumentScreen kind={kind} onBack={() => setPage(kind)} />
  } else if (page === 'location') {
    content = <SettingsDetail title="מיקום" onBack={detailBack}><h3>איך המיקום משמש את השירות?</h3><p>Family Car Agent אינו קורא את מיקום ה־PWA באופן רציף.</p><p>בעת ניתוק מ־CarPlay, קיצור הדרך יכול לשלוח את מיקום המכשיר הנוכחי לשרת כדי לבדוק אם הרכב נמצא בקרבת כתובת המשפחה.</p><h3>ניהול באייפון</h3><p>פתחו את ״קיצורים״, בחרו Disconnect From CarPlay ובדקו שהפעולה שמקבלת מיקום מורשית לפעול.</p><a className="settings-detail-action" href="shortcuts://open-shortcut?name=Disconnect%20From%20CarPlay">פתיחת הקיצור</a><small>אם הקישור אינו נפתח, פתחו ידנית את אפליקציית ״קיצורים״.</small></SettingsDetail>
  } else if (page === 'carplay') {
    content = <SettingsDetail title="CarPlay" onBack={detailBack}><h3>ניהול האוטומציות</h3><p>החיבור של Family Car Agent מבוסס על פעולות אוטומטיות באפליקציית Apple Shortcuts.</p><p>פתחו ״קיצורים״, עברו אל ״פעולות אוטומטיות״ ובחרו את אוטומציית CarPlay המתאימה.</p><a className="settings-detail-action" href="shortcuts://">פתיחת ״קיצורים״</a><small>iOS אינו מספק קישור ישיר אמין לאוטומציית CarPlay מסוימת.</small></SettingsDetail>
  } else if (page === 'privacy' || page === 'terms') {
    const document = LEGAL_DOCUMENTS[page]
    content = <SettingsDetail title={document.title} onBack={detailBack}><p className="settings-legal-summary">{document.summary}</p>{page === 'privacy' ? <><p>המידע משמש להפעלת החשבון, המשפחה, כתובת הבית, היסטוריית הרכב, הזמנות, הצ׳אט, Push וקיצורי CarPlay.</p><p>הכתובת נשלחת ל־Google Maps לצורך geocoding; תוכן צ׳אט ומידע הקשרי רלוונטי עשויים להיות מעובדים ב־Gemini.</p></> : <p>מצב הרכב, הזמנות, התראות ותשובות הסוכן מסייעים בתיאום בלבד ואינם אישור חוקי או בטיחותי לנהיגה.</p>}<button className="settings-detail-action" type="button" onClick={() => setPage(page === 'privacy' ? 'privacy-policy' : 'terms-document')}>{page === 'privacy' ? 'מדיניות הפרטיות המלאה' : 'תנאי השימוש המלאים'}</button><small>גרסה {document.version} · עודכן לאחרונה: {document.lastUpdated}</small></SettingsDetail>
  } else if (page === 'contact') {
    content = <SettingsDetail title="יצירת קשר" onBack={() => setPage('about')}><p>ערוץ התמיכה עדיין אינו זמין.</p></SettingsDetail>
  } else if (page === 'about') {
    content = <SettingsDetail title="אודות" onBack={detailBack}><img className="settings-about-logo" src="/images/family-car-agent-logo.png" alt="" /><h3>Family Car Agent</h3><p>דרך פשוטה לתאם ולנהל את השימוש ברכב המשפחתי.</p><dl className="settings-about-details"><div><dt>גרסה</dt><dd>{version}</dd></div><div><dt>מפעיל</dt><dd>מפעיל Family Car Agent</dd></div></dl><button className="settings-detail-action" type="button" onClick={() => setPage('contact')}>יצירת קשר</button></SettingsDetail>
  } else {
    content = <div className="settings-screen-scroll"><div className="family-screen-title settings-screen-title"><DashboardCategoryIcon icon="settings" /><h2>הגדרות</h2></div><div className="settings-sections">
      <section className="settings-group" aria-labelledby="settings-account-title"><h3 id="settings-account-title">חשבון</h3><div className="settings-card">
        <div className="settings-row settings-row-static"><span>שם</span><strong>{userName}</strong></div>
        <button type="button" className="settings-row" onClick={onOpenFamily}><span>המשפחה שלי</span><span className="settings-row-value">פתיחת ניהול המשפחה ‹</span></button>
        <div className="settings-row settings-row-static"><span>אימייל</span><strong dir="ltr">{userEmail || 'לא זמין'}</strong></div>
        <div className="settings-row settings-row-static settings-code-row"><span>קוד חיבור ל־CarPlay</span><span className="settings-row-value"><b aria-label="קוד מוסתר">••••••••</b><small>נעול — חשיפה מאובטחת תתווסף בהמשך</small></span></div>
      </div></section>
      <section className="settings-group" aria-labelledby="settings-display-title"><h3 id="settings-display-title">תצוגה</h3><div className="settings-card">
        <div className="settings-control-row"><span>מצב תצוגה</span><div className="settings-segmented" aria-label="מצב תצוגה">{THEME_OPTIONS.map((option) => <button type="button" key={option.value} aria-pressed={theme === option.value} onClick={() => setTheme(option.value)}>{option.label}</button>)}</div></div>
        <div className="settings-control-row"><span>גודל טקסט</span><div className="settings-segmented" aria-label="גודל טקסט">{TEXT_SIZE_OPTIONS.map((option) => <button type="button" key={option.value} aria-pressed={textSize === option.value} onClick={() => setTextSize(option.value)}>{option.label}</button>)}</div></div>
      </div></section>
      <section className="settings-group" aria-labelledby="settings-permissions-title"><h3 id="settings-permissions-title">הרשאות</h3><div className="settings-card">
        <button type="button" className="settings-row" onClick={() => setPage('location')}><span>מיקום</span><span className="settings-row-value">ניהול ‹</span></button>
        <button type="button" className="settings-row" onClick={() => setPage('carplay')}><span>CarPlay</span><span className="settings-row-value">ניהול ‹</span></button>
        <div className="settings-row settings-notification-row"><span><strong>שליחת התראות</strong><small>{notificationStateLabel(pushState)} · {permission}</small></span><button type="button" className="settings-switch" role="switch" aria-label="שליחת התראות במכשיר הזה" aria-checked={pushState === 'subscribed'} aria-disabled={pushState === 'unsupported'} disabled={pushBusy || pushState === 'unsupported'} onClick={togglePush}><i aria-hidden="true" /></button></div>
        {pushError ? <div className="settings-inline-error" role="status"><p>{pushError}</p>{pushState === 'error' || !pushConfig ? <button type="button" onClick={() => { setPushState('loading'); setPushLoadAttempt((value) => value + 1) }}>נסו שוב</button> : null}</div> : null}
      </div></section>
      <section className="settings-group" aria-label="מידע משפטי ואודות"><div className="settings-card"><button type="button" className="settings-row" onClick={() => setPage('privacy')}><span>פרטיות</span><span className="settings-row-value">פתיחה ‹</span></button><button type="button" className="settings-row" onClick={() => setPage('terms')}><span>תנאי שימוש</span><span className="settings-row-value">פתיחה ‹</span></button><button type="button" className="settings-row" onClick={() => setPage('about')}><span>אודות</span><span className="settings-row-value">פתיחה ‹</span></button></div></section>
      <section className="settings-group" aria-label="פעולות חשבון"><div className="settings-card"><button type="button" className="settings-row settings-row-danger" disabled={loggingOut} onClick={() => void logout()}><span>{loggingOut ? 'מתנתקים…' : 'התנתקות'}</span><span /></button></div></section>
    </div></div>
  }
  return <section className={`category-placeholder-screen settings-screen${open ? ' is-open' : ''}`} dir="rtl" role="dialog" aria-modal="true" aria-label="הגדרות" aria-hidden={!open} inert={!open}>{page === 'main' ? <header className="dashboard-header category-placeholder-header"><button ref={backButtonRef} type="button" onClick={() => { setPage('main'); onBack() }} aria-label="חזרה ללוח הבקרה"><span aria-hidden="true">×</span></button><h1>Family Car Agent</h1><span aria-hidden="true" /></header> : null}{content}</section>
}
