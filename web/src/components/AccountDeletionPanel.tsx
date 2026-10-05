import { useEffect, useRef, useState } from 'react'
import { confirmAccountDeletion, getDeletionPreview, getDeletionStatus, type DeletionPreview, type DeletionStatus } from '../api/apiClient'
import { clearDeletionLocalState } from '../auth/deletionCleanup'
import { createDeletionSubmissionGuard } from '../auth/deletionSubmission'

export function AccountDeletionPanel({ accessToken, onBack, onLogout }: {
  accessToken: string; onBack: () => void; onLogout: () => Promise<void>
}) {
  const [preview, setPreview] = useState<DeletionPreview | null>(null)
  const [phase, setPhase] = useState<DeletionStatus['status']>('not_requested')
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [error, setError] = useState('')
  const submitOnce = useRef(createDeletionSubmissionGuard())
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [exiting, setExiting] = useState(false)
  const pending = phase === 'draining' || phase === 'auth_pending'

  useEffect(() => {
    let active = true
    void getDeletionStatus(accessToken).then(async (state) => {
      if (!active) return
      setPhase(state.status)
      if (state.status === 'not_requested') {
        const result = await getDeletionPreview(accessToken)
        if (active) setPreview(result)
      }
    }).catch(() => { if (active) setError('לא הצלחנו לבדוק את מצב החשבון. נסו שוב.') })
    return () => { active = false }
  }, [accessToken, loadAttempt])

  useEffect(() => {
    if (!pending) return
    let active = true
    const timer = window.setInterval(() => {
      void getDeletionStatus(accessToken).then((state) => {
        if (active) { setPhase(state.status); setError('') }
      }).catch(() => { if (active) setError('המחיקה ממשיכה בשרת. לא הצלחנו לעדכן את המצב כרגע.') })
    }, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [accessToken, pending])

  const clearLocal = () => {
    try { clearDeletionLocalState([window.localStorage, window.sessionStorage]) } catch { /* restricted storage */ }
  }
  const confirm = async () => {
    if (pending || phase === 'completed' || !preview) return
    await submitOnce.current(async () => {
      setBusy(true); setError('')
      try {
        const result = await confirmAccountDeletion(accessToken)
        setPhase(result.status); setUncertain(false); clearLocal()
        return true
      } catch {
        setUncertain(true)
        setError('לא ניתן לאשר את מצב הבקשה כרגע. ייתכן שהמחיקה החלה; לחצו שוב לבדיקת המצב ולהמשך הבקשה.')
        return false
      } finally { setBusy(false) }
    })
  }
  const exit = async () => {
    if (exiting) return
    setExiting(true); clearLocal()
    try { await onLogout() } catch { setError('לא הצלחנו לנקות את ההתחברות המקומית. נסו שוב.') }
    finally { setExiting(false) }
  }

  return <div className="settings-detail" dir="rtl">
    <header className="settings-detail-header"><button type="button" disabled={pending || busy || uncertain || phase === 'completed'} onClick={onBack} aria-label="חזרה להגדרות">→</button><h2>מחיקת חשבון</h2><span /></header>
    <div className="settings-detail-content">
      <p>החשבון וכל המידע האישי שלכם ב־FCA יימחקו לצמיתות. לא ניתן לבטל את המחיקה.</p>
      <p>אם אתם מנהלי המשפחה ונשארו חברים נוספים, ניהול המשפחה יועבר אוטומטית לחבר אחר. אם אתם החברים האחרונים, גם המשפחה והמידע המשפחתי יימחקו.</p>
      {preview?.consequence === 'management_transferred' ? <p>במצב הנוכחי, ניהול המשפחה יועבר לחבר משפחה אחר.</p> : null}
      {preview?.consequence === 'family_deleted' ? <p>אתם החברים האחרונים: גם המשפחה והמידע שלה ב־FCA יימחקו.</p> : null}
      {pending ? <p role="status">מחיקת החשבון בתהליך. החשבון חסום לפעילות; ההשלמה תימשך גם לאחר סגירת האפליקציה.</p> : null}
      {phase === 'completed' ? <p role="status">החשבון נמחק.</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {!preview && phase === 'not_requested' && error ? <button type="button" className="settings-detail-action" onClick={() => { setError(''); setLoadAttempt((value) => value + 1) }}>בדיקה מחדש</button> : null}
      {phase === 'not_requested' ? <button type="button" className="settings-detail-action settings-row-danger" disabled={busy || !preview} onClick={() => void confirm()}>{busy ? 'שולחים בקשה…' : 'אני מאשר/ת מחיקה לצמיתות'}</button> : null}
      {pending || uncertain || phase === 'completed' ? <button type="button" className="settings-detail-action" disabled={exiting} onClick={() => void exit()}>סגירה והתנתקות</button> : null}
    </div>
  </div>
}
