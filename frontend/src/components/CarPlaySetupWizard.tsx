import { useEffect, useState } from 'react'
import { prepareCarPlaySetup, type CarPlaySetup } from '../api/apiClient'
import {
  carPlaySetupActionSteps,
  carPlaySetupLastStep,
  clearCarPlaySetupDraft,
  copyConnectionCode,
  loadCarPlaySetupStep,
  nextCarPlaySetupStep,
  previousCarPlaySetupStep,
  saveCarPlaySetupStep,
} from '../carplay/carPlaySetupDraft'
import connectShortcutImage from '../assets/carplay/01-connect-shortcut.jpeg'
import connectCodeImage from '../assets/carplay/02-connect-code.jpeg'
import disconnectShortcutImage from '../assets/carplay/03-disconnect-shortcut.jpeg'
import disconnectCodeImage from '../assets/carplay/04-disconnect-code.jpeg'
import allShortcutsImage from '../assets/carplay/05-all-shortcuts.jpeg'
import chooseCarPlayImage from '../assets/carplay/06-choose-carplay.jpeg'
import connectAutomationImage from '../assets/carplay/07-connect-automation.jpeg'
import chooseConnectImage from '../assets/carplay/08-choose-connect.jpeg'
import disconnectAutomationImage from '../assets/carplay/09-disconnect-automation.jpeg'
import chooseDisconnectImage from '../assets/carplay/10-choose-disconnect.jpeg'

type Props = {
  accessToken: string
  authUserId: string
  onBack: () => void
  onStatusChange: (status: 'completed' | 'skipped') => Promise<void>
}

type StepContent = {
  title: string
  action: string
  secondary?: string
  image?: string
  imageAlt?: string
  instructions?: string[]
  callout?: string
  shortcut?: 'connect' | 'disconnect'
  code?: 'full' | 'compact'
}

const steps: StepContent[] = [
  {
    title: 'חיבור CarPlay',
    action: 'בוא נחבר את האייפון לרכב.',
    secondary: 'זה לוקח בערך 2 דקות 🙂\nלא צריך להיות ברכב כדי לבצע את ההגדרה.\nהכול מוסבר שלב־שלב, ואחרי שמסיימים לא צריך להתעסק בזה שוב.',
  },
  {
    title: 'קוד החיבור שלך',
    action: 'העתק את הקוד. נשתמש בו בשני הקיצורים שנגדיר בעוד רגע.',
    secondary: 'אל תדאג, נציג לך אותו שוב כשצריך.',
    code: 'full',
  },
  {
    title: 'התקנת קיצור החיבור',
    action: 'פתח את Connect To CarPlay ולחץ על ״הגדרת קיצור״.',
    image: connectShortcutImage,
    imageAlt: 'מסך Connect To CarPlay עם הכפתור הגדרת קיצור',
    shortcut: 'connect',
    code: 'compact',
  },
  {
    title: 'הגדרת קיצור החיבור',
    action: 'הדבק את הקוד בשדה ״מלל״.',
    secondary: 'לאחר מכן לחץ על ״הוספת קיצור״.',
    image: connectCodeImage,
    imageAlt: 'מסך קביעת תצורה לקיצור עם השדה מלל',
    code: 'compact',
  },
  {
    title: 'התקנת קיצור הניתוק',
    action: 'פתח את Disconnect From CarPlay ולחץ על ״הגדרת קיצור״.',
    image: disconnectShortcutImage,
    imageAlt: 'מסך Disconnect From CarPlay עם הכפתור הגדרת קיצור',
    shortcut: 'disconnect',
    code: 'compact',
  },
  {
    title: 'הגדרת קיצור הניתוק',
    action: 'הדבק שוב את אותו קוד בשדה ״מלל״.',
    secondary: 'לאחר מכן לחץ על ״הוספת קיצור״.',
    image: disconnectCodeImage,
    imageAlt: 'מסך קביעת תצורה לקיצור הניתוק עם השדה מלל',
    code: 'compact',
  },
  {
    title: 'פתח את אפליקציית קיצורים',
    action: 'פתח באייפון את אפליקציית ״קיצורים״.',
    secondary: 'אם אינך מוצא אותה, חפש ״קיצורים״ בחיפוש של האייפון.',
    image: allShortcutsImage,
    imageAlt: 'מסך כל הקיצורים באייפון',
  },
  {
    title: 'פעולות אוטומטיות',
    action: 'לחץ למטה על ״פעולות אוטומטיות״.',
    secondary: 'במסך שייפתח לחץ על + למעלה.',
    image: allShortcutsImage,
    imageAlt: 'מסך כל הקיצורים עם פעולות אוטומטיות בתחתית',
    callout: 'אל תלחץ על אחד משני הקיצורים. עכשיו אנחנו מגדירים מתי הם ירוצו אוטומטית.',
  },
  {
    title: 'בחר CarPlay',
    action: 'ברשימת האפשרויות בחר ״CarPlay״.',
    image: chooseCarPlayImage,
    imageAlt: 'רשימת הפעולות האוטומטיות ובה האפשרות CarPlay',
  },
  {
    title: 'הגדרת החיבור לרכב',
    action: 'בחר ״מחובר״ ו״הפעלה מיידית״.',
    image: connectAutomationImage,
    imageAlt: 'מסך CarPlay כאשר מחובר מסומן והפעלה מיידית נבחרה',
    instructions: ['ודא ש״מנותק״ אינו מסומן.', 'ודא ש״הפעלה לאחר אישור״ אינה מסומנת.', 'לחץ על ״הבא״.'],
    callout: 'חשוב: יש לבחור ״הפעלה מיידית״ כדי שהחיבור יעבוד אוטומטית.',
  },
  {
    title: 'בחר את קיצור החיבור',
    action: 'בשורה ״הקיצורים שלי״ בחר Connect To CarPlay.',
    image: chooseConnectImage,
    imageAlt: 'מסך הקיצורים שלי עבור חיבור CarPlay',
    callout: 'אל תבחר ״יצירת קיצור חדש״.',
  },
  {
    title: 'אוטומציה נוספת',
    action: 'חזור למסך ״פעולות אוטומטיות״ ולחץ שוב על +.',
    image: allShortcutsImage,
    imageAlt: 'מסך הקיצורים עם פעולות אוטומטיות',
  },
  {
    title: 'בחר שוב CarPlay',
    action: 'ברשימת האפשרויות בחר שוב ״CarPlay״.',
    image: chooseCarPlayImage,
    imageAlt: 'רשימת הפעולות האוטומטיות ובה האפשרות CarPlay',
  },
  {
    title: 'הגדרת הניתוק מהרכב',
    action: 'בחר ״מנותק״ ו״הפעלה מיידית״.',
    image: disconnectAutomationImage,
    imageAlt: 'מסך CarPlay כאשר מנותק מסומן והפעלה מיידית נבחרה',
    instructions: ['ודא ש״מחובר״ אינו מסומן.', 'ודא ש״הפעלה לאחר אישור״ אינה מסומנת.', 'לחץ על ״הבא״.'],
    callout: 'גם כאן חשוב לבחור ״הפעלה מיידית״.',
  },
  {
    title: 'בחר את קיצור הניתוק',
    action: 'בשורה ״הקיצורים שלי״ בחר Disconnect From CarPlay.',
    image: chooseDisconnectImage,
    imageAlt: 'מסך הקיצורים שלי עבור ניתוק CarPlay',
  },
  {
    title: 'הכול מוכן 🎉',
    action: 'החיבור ל-CarPlay הוגדר.',
    instructions: ['בפעם הראשונה שבה CarPlay יתחבר או יתנתק, ייתכן שהאייפון יבקש אישור להרצת הקיצור. בחר באפשרות שמאפשרת להריץ אותו תמיד או באופן אוטומטי, כדי שמכאן והלאה לא תצטרך לעשות דבר.'],
    callout: 'זה קורה רק בפעם הראשונה.',
  },
]

function CodeCard({ setup, compact, copied, onCopy }: {
  setup: CarPlaySetup
  compact: boolean
  copied: boolean
  onCopy: () => void
}) {
  return (
    <div className={`connection-code-panel${compact ? ' compact' : ''}`}>
      <span>קוד החיבור שלך</span>
      <strong dir="ltr">{setup.connection_code}</strong>
      <button type="button" className="secondary-button" onClick={onCopy}>
        {copied ? 'הועתק ✓' : 'העתק קוד'}
      </button>
    </div>
  )
}

export function CarPlaySetupWizard({ accessToken, authUserId, onBack, onStatusChange }: Props) {
  const [step, setStep] = useState(() => loadCarPlaySetupStep(authUserId))
  const [setup, setSetup] = useState<CarPlaySetup | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [isSavingStatus, setIsSavingStatus] = useState(false)
  const current = steps[step]

  useEffect(() => {
    const controller = new AbortController()
    void prepareCarPlaySetup(accessToken, { signal: controller.signal })
      .then(setSetup)
      .catch((requestError: unknown) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError('לא הצלחנו לטעון את קוד החיבור. בדוק את החיבור ונסה שוב.')
      })
    return () => controller.abort()
  }, [accessToken])

  useEffect(() => {
    saveCarPlaySetupStep(authUserId, step)
  }, [authUserId, step])

  const saveStatus = async (status: 'completed' | 'skipped') => {
    if (isSavingStatus) return
    setIsSavingStatus(true)
    setError('')
    try {
      await onStatusChange(status)
      clearCarPlaySetupDraft()
    } catch {
      setError('לא הצלחנו לשמור את הבחירה. ההתקדמות שלך נשמרה ואפשר לנסות שוב.')
      setIsSavingStatus(false)
    }
  }

  const moveNext = () => {
    setCopied(false)
    if (step === carPlaySetupLastStep) {
      void saveStatus('completed')
      return
    }
    setStep(nextCarPlaySetupStep)
  }

  const moveBack = () => {
    setCopied(false)
    if (step === 0) {
      onBack()
      return
    }
    setStep(previousCarPlaySetupStep)
  }

  const copyCode = async () => {
    if (!setup) return
    try {
      await copyConnectionCode(setup.connection_code)
      setCopied(true)
      setError('')
    } catch {
      setError('לא הצלחנו להעתיק. לחץ לחיצה ארוכה על הקוד ובחר ״העתק״.')
    }
  }

  if (!setup) {
    return (
      <main className="identity-state-screen carplay-setup-loading" dir="rtl">
        <div className="final-processing-spinner" aria-hidden="true"><span /></div>
        <h1>מכינים את החיבור</h1>
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button type="button" className="secondary-button" onClick={onBack}>חזרה לאפליקציה</button>
          </>
        ) : <p>עוד רגע והכול יהיה מוכן.</p>}
      </main>
    )
  }

  const isFinished = step === carPlaySetupLastStep
  const progressStep = Math.min(Math.max(step, 0), carPlaySetupActionSteps)
  const shortcutUrl = current.shortcut === 'connect'
    ? setup.connect_shortcut_url
    : setup.disconnect_shortcut_url

  return (
    <main className={`carplay-wizard${isFinished ? ' finished' : ''}`} dir="rtl">
      {!isFinished && (
        <header className="carplay-wizard-navigation">
          <button type="button" onClick={moveBack} className={step === 0 ? 'is-hidden' : undefined}>אחורה</button>
          <div className="carplay-progress-wrap">
            <span>{step === 0 ? 'מתחילים' : `שלב ${progressStep} מתוך ${carPlaySetupActionSteps}`}</span>
            <div className="carplay-progress-bar" role="progressbar" aria-valuemin={0} aria-valuemax={carPlaySetupActionSteps} aria-valuenow={progressStep}>
              <i style={{ width: `${(progressStep / carPlaySetupActionSteps) * 100}%` }} />
            </div>
          </div>
          <button
            type="button"
            onClick={step === 0 ? () => void saveStatus('skipped') : moveNext}
            disabled={step === 0 && isSavingStatus}
          >
            {step === 0
              ? (isSavingStatus ? 'שומר...' : 'כבר הגדרתי')
              : 'המשך'}
          </button>
        </header>
      )}

      <section className="carplay-wizard-card">
        <h1>{current.title}</h1>
        <p className="carplay-primary-instruction">{current.action}</p>
        {current.secondary && <p className="carplay-secondary-copy">{current.secondary}</p>}

        {current.shortcut && (
          <a className="primary-button carplay-shortcut-link" href={shortcutUrl}>
            {current.shortcut === 'connect' ? 'פתח את קיצור החיבור' : 'פתח את קיצור הניתוק'}
          </a>
        )}

        {current.code && <CodeCard setup={setup} compact={current.code === 'compact'} copied={copied} onCopy={() => void copyCode()} />}

        {current.image && <img className="carplay-guide-image" src={current.image} alt={current.imageAlt} />}

        {current.instructions && (
          <ul className={isFinished ? 'carplay-final-note' : 'carplay-instructions'}>
            {current.instructions.map((instruction) => <li key={instruction}>{instruction}</li>)}
          </ul>
        )}
        {current.callout && <p className="carplay-callout">{current.callout}</p>}
        {error && <p className="carplay-copy-error" role="alert">{error}</p>}

        {step === 0 && (
          <button
            type="button"
            className="primary-button carplay-start-button"
            onClick={moveNext}
            disabled={isSavingStatus}
          >
            מתחילים
          </button>
        )}

        {isFinished && (
          <button type="button" className="primary-button carplay-finish-button" onClick={moveNext} disabled={isSavingStatus}>
            {isSavingStatus ? 'שומר...' : 'המשך לאפליקציה'}
          </button>
        )}
      </section>
    </main>
  )
}
