import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { useAuth } from './auth/authContext'
import {
  clearOnboardingDraft,
  clearPendingCreateSuccess,
  clearPendingJoinSuccess,
  loadOnboardingDraft,
  loadPendingCreateSuccess,
  loadPendingJoinSuccess,
  isPendingSuccessForAuthUser,
  saveOnboardingDraft,
  savePendingCreateSuccess,
  savePendingJoinSuccess,
} from './auth/onboardingDraft'
import type {
  OnboardingFlow,
  OnboardingFormData,
} from './auth/onboardingDraft'
import { AuthGate } from './components/AuthGate'
import { createInvalidSessionRecovery } from './auth/invalidSessionRecovery'
import { CarPlaySetupWizard } from './components/CarPlaySetupWizard'
import { MainAppScreen } from './components/MainAppScreen'
import { clearCarPlaySetupDraft } from './carplay/carPlaySetupDraft'
import { resolveAppDestination } from './auth/appDestination'
import {
  OnboardingApiError,
  confirmJoinFamilyAddress,
  resolveCreateFamilyAddress,
  startJoinFamily,
  submitJoinFamilyAddress,
  submitJoinFamilyCode,
  submitJoinFamilyName,
  updateCarPlaySetupStatus,
  type JoinFamilySession,
} from './api/apiClient'
import { createCreateFamilySubmitter } from './onboarding/createFamilySubmission'
import {
  appendRemainingAttempts,
  initialCreateValidationAttempts,
  registerCreateValidationFailure,
  type CreateValidationField,
} from './onboarding/createValidationAttempts'
import { createJoinRequestRunner } from './onboarding/joinFamilyRequests'
import { createJoinFamilyCompleter } from './onboarding/joinFamilySubmission'
import { humanNameError, isValidHumanName } from './onboarding/nameValidation'

type Flow = 'welcome' | OnboardingFlow
type FormData = OnboardingFormData

const initialForm: FormData = {
  familyName: '',
  familyCode: '',
  address: '',
  userName: '',
  resolvedAddress: '',
  addressResolutionToken: '',
}

function isValidAddress(address: string) {
  const parts = address.split(',').map((part) => part.trim())
  return parts.length === 3 && parts.every(Boolean) && /\d/.test(parts[2])
}

function WelcomeScreen({ onChoose }: { onChoose: (flow: Exclude<Flow, 'welcome'>) => void }) {
  return (
    <main className="welcome-screen">
      <section className="brand-section" aria-labelledby="app-title">
        <img
          className="brand-logo"
          src="/images/family-car-agent-logo.png"
          alt=""
          aria-hidden="true"
        />
        <h1 id="app-title">Family Car Agent</h1>
        <div className="separator" aria-hidden="true" />
        <h2>הדרך החכמה<br />לנהל את הרכב המשפחתי</h2>
        <p>
          בדקו מי עם הרכב, נהלו הזמנות וקבלו<br className="wide-break" />
          עדכונים אוטומטיים עם CarPlay וסוכן חכם.
        </p>
      </section>

      <div className="welcome-actions" aria-label="בחירת מסלול הרשמה">
        <button type="button" onClick={() => onChoose('create')}>
          <span className="button-symbol" aria-hidden="true">＋</span>
          <span>יצירת משפחה</span>
        </button>
        <button type="button" onClick={() => onChoose('join')}>
          <span className="button-symbol people-symbol" aria-hidden="true">◯</span>
          <span>הצטרפות למשפחה</span>
        </button>
      </div>
    </main>
  )
}

function IdentityLoadingScreen() {
  return (
    <main className="identity-state-screen" aria-busy="true">
      <span className="auth-spinner" aria-hidden="true" />
      <h1>טוענים את החשבון…</h1>
      <p>בודקים בבטחה לאיזו משפחה החשבון מחובר.</p>
    </main>
  )
}

function FinalProcessingScreen({ flow }: { flow: OnboardingFlow }) {
  const messages = ['עוד רגע…', 'כמעט סיימנו', 'ממש עוד שנייה']
  const [messageIndex, setMessageIndex] = useState(0)

  useEffect(() => {
    const interval = window.setInterval(() => {
      setMessageIndex((current) => (current + 1) % messages.length)
    }, 1800)
    return () => window.clearInterval(interval)
  }, [messages.length])

  return (
    <main
      className="identity-state-screen final-processing-screen"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="final-processing-spinner" aria-hidden="true">
        <span />
      </div>
      <h1>{flow === 'create' ? 'יוצרים את המשפחה' : 'מצרפים אותך למשפחה'}</h1>
      <p key={messageIndex} className="final-processing-message" role="status">
        {messages[messageIndex]}
      </p>
      <small>אפשר להישאר במסך הזה, אנחנו משלימים הכול בבטחה.</small>
    </main>
  )
}

function IdentityErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="identity-state-screen">
      <div className="identity-error-mark" aria-hidden="true">!</div>
      <h1>לא הצלחנו לטעון את החשבון</h1>
      <p role="alert">{message}</p>
      <button type="button" className="primary-button identity-retry-button" onClick={onRetry}>
        ניסיון נוסף
      </button>
    </main>
  )
}

function JoinLockedScreen({
  message,
  lockedUntil,
  onRetry,
  onBack,
}: {
  message: string
  lockedUntil: string | null
  onRetry: () => void
  onBack: () => void
}) {
  const retryTime = lockedUntil
    ? new Intl.DateTimeFormat('he-IL', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(lockedUntil))
    : null

  return (
    <main className="identity-state-screen">
      <div className="identity-error-mark" aria-hidden="true">!</div>
      <h1>תהליך ההצטרפות נעול זמנית</h1>
      <p role="alert">{message}</p>
      {retryTime && <p>אפשר לנסות שוב לאחר השעה {retryTime}.</p>}
      <button type="button" className="primary-button" onClick={onRetry}>
        בדיקה מחדש
      </button>
      <button type="button" className="secondary-button" onClick={onBack}>
        חזרה
      </button>
    </main>
  )
}

type FlowScreenProps = {
  flow: Exclude<Flow, 'welcome'>
  step: number
  form: FormData
  error: string
  isSubmitting: boolean
  onChange: (field: keyof FormData, value: string) => void
  onBack: () => void
  onContinue: () => void
  onChangeAddress: () => void
  onFinish: () => void
}

function FlowHeader({
  step,
  onBack,
  isSubmitting,
}: {
  step: number
  onBack: () => void
  isSubmitting: boolean
}) {
  return (
    <header className="flow-header">
      <button
        type="button"
        className="back-button"
        onClick={onBack}
        aria-label="חזרה"
        disabled={isSubmitting}
      >
        →
      </button>
      <span className="progress-label">{step + 1} מתוך 5</span>
      <span className="header-spacer" aria-hidden="true" />
    </header>
  )
}

function TextStep({
  title,
  description,
  label,
  value,
  placeholder,
  inputMode,
  maxLength,
  error,
  buttonText = 'המשך',
  isSubmitting = false,
  onChange,
  onContinue,
}: {
  title: string
  description?: string
  label: string
  value: string
  placeholder: string
  inputMode?: 'text' | 'numeric'
  maxLength?: number
  error: string
  buttonText?: string
  isSubmitting?: boolean
  onChange: (value: string) => void
  onContinue: () => void
}) {
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onContinue()
  }

  return (
    <form className="step-form" onSubmit={submit} noValidate>
      <div className="step-copy">
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>

      <div className="field-group">
        <label htmlFor="step-input">{label}</label>
        <input
          id="step-input"
          type="text"
          dir="rtl"
          value={value}
          placeholder={placeholder}
          inputMode={inputMode}
          maxLength={maxLength}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'field-error' : undefined}
          autoFocus
          disabled={isSubmitting}
        />
        {error && <p className="field-error" id="field-error">{error}</p>}
      </div>

      <button type="submit" className="primary-button" disabled={isSubmitting}>
        {isSubmitting ? 'אנא המתינו…' : buttonText}
      </button>
    </form>
  )
}

function AddressConfirmation({
  address,
  displayAddress,
  error,
  isSubmitting,
  onContinue,
  onChangeAddress,
}: {
  address: string
  displayAddress?: string
  error: string
  isSubmitting: boolean
  onContinue: () => void
  onChangeAddress: () => void
}) {
  return (
    <div className="confirmation-step">
      <div className="step-copy">
        <h1>זו הכתובת הנכונה?</h1>
        <p>בדקו את הפרטים לפני שממשיכים.</p>
      </div>

      <div className="address-preview">
        <span aria-hidden="true">⌖</span>
        <strong>{displayAddress || address}</strong>
      </div>

      {error && <p className="field-error">{error}</p>}

      <div className="confirmation-actions">
        <button type="button" className="primary-button" onClick={onContinue} disabled={isSubmitting}>כן, המשך</button>
        <button type="button" className="secondary-button" onClick={onChangeAddress} disabled={isSubmitting}>שנה כתובת</button>
      </div>
    </div>
  )
}

function SuccessScreen({ flow, form, onFinish }: Pick<FlowScreenProps, 'flow' | 'form' | 'onFinish'>) {
  const [copied, setCopied] = useState(false)

  const copyCode = async () => {
    if (!form.familyCode) return
    try {
      await navigator.clipboard.writeText(form.familyCode)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <main className="success-screen">
      <div className="success-mark" aria-hidden="true">✓</div>
      <p className="success-brand">Family Car Agent</p>
      <h1>{flow === 'create' ? 'המשפחה נוצרה 🎉' : 'הצטרפת למשפחה 🎉'}</h1>
      <p className="success-copy">
        {form.userName}, הכול מוכן עבור {flow === 'create' ? 'משפחת ' : ''}{form.familyName}.
      </p>

      {flow === 'create' && (
        <div className="family-code-panel">
          <span>קוד המשפחה</span>
          <strong dir="ltr">{form.familyCode}</strong>
          <button type="button" onClick={copyCode}>{copied ? 'הקוד הועתק' : 'העתקת הקוד'}</button>
          <small>שתף את הקוד רק עם בני המשפחה שתרצה לצרף.</small>
        </div>
      )}

      <button type="button" className="primary-button success-button" onClick={onFinish}>
        המשך להגדרת CarPlay
      </button>
    </main>
  )
}

function FlowScreen(props: FlowScreenProps) {
  const {
    flow,
    step,
    form,
    error,
    isSubmitting,
    onChange,
    onBack,
    onContinue,
    onChangeAddress,
    onFinish,
  } = props

  if (step === 5) {
    return <SuccessScreen flow={flow} form={form} onFinish={onFinish} />
  }

  let content

  if (flow === 'create') {
    if (step === 0) {
      content = (
        <TextStep
          title="איך נקרא למשפחה?"
          label="שם המשפחה"
          value={form.familyName}
          placeholder="לדוגמה: כהן"
          error={error}
          isSubmitting={isSubmitting}
          onChange={(value) => onChange('familyName', value)}
          onContinue={onContinue}
        />
      )
    } else if (step === 1) {
      content = (
        <TextStep
          title="בחר קוד משפחה"
          description="קוד בן 6 ספרות שבני המשפחה האחרים ישתמשו בו כדי להצטרף."
          label="קוד משפחה"
          value={form.familyCode}
          placeholder="482731"
          inputMode="numeric"
          maxLength={6}
          error={error}
          onChange={(value) => onChange('familyCode', value)}
          onContinue={onContinue}
        />
      )
    } else if (step === 2) {
      content = (
        <TextStep
          title="מה כתובת הבית?"
          description="יש לכתוב בפורמט הבא בלבד: עיר, רחוב, מספר בית"
          label="כתובת הבית"
          value={form.address}
          placeholder="תל אביב, דיזנגוף, 120"
          error={error}
          isSubmitting={isSubmitting}
          onChange={(value) => onChange('address', value)}
          onContinue={onContinue}
        />
      )
    } else if (step === 3) {
      content = (
        <AddressConfirmation
          address={form.address}
          displayAddress={form.resolvedAddress}
          error={error}
          isSubmitting={isSubmitting}
          onContinue={onContinue}
          onChangeAddress={onChangeAddress}
        />
      )
    } else {
      content = (
        <TextStep
          title="איך קוראים לך?"
          label="השם שלך"
          value={form.userName}
          placeholder="הקלד את שמך"
          error={error}
          buttonText="יצירת המשפחה"
          isSubmitting={isSubmitting}
          onChange={(value) => onChange('userName', value)}
          onContinue={onContinue}
        />
      )
    }
  } else if (step === 0) {
    content = (
      <TextStep
        title="לאיזו משפחה מצטרפים?"
        label="שם המשפחה"
        value={form.familyName}
        placeholder="לדוגמה: כהן"
        error={error}
        isSubmitting={isSubmitting}
        onChange={(value) => onChange('familyName', value)}
        onContinue={onContinue}
      />
    )
  } else if (step === 1) {
    content = (
      <TextStep
        title="מה כתובת הבית?"
        description="יש לכתוב בפורמט הבא בלבד: עיר, רחוב, מספר בית"
        label="כתובת הבית"
        value={form.address}
        placeholder="תל אביב, דיזנגוף, 120"
        error={error}
        isSubmitting={isSubmitting}
        onChange={(value) => onChange('address', value)}
        onContinue={onContinue}
      />
    )
  } else if (step === 2) {
    content = (
      <AddressConfirmation
        address={form.address}
        displayAddress={form.resolvedAddress}
        error={error}
        isSubmitting={isSubmitting}
        onContinue={onContinue}
        onChangeAddress={onChangeAddress}
      />
    )
  } else if (step === 3) {
    content = (
      <TextStep
        title="מה קוד המשפחה?"
        description="הקוד מופיע בהודעה שקיבל בן המשפחה שיצר את המשפחה."
        label="קוד משפחה"
        value={form.familyCode}
        placeholder="000000"
        inputMode="numeric"
        maxLength={6}
        error={error}
        isSubmitting={isSubmitting}
        onChange={(value) => onChange('familyCode', value)}
        onContinue={onContinue}
      />
    )
  } else {
    content = (
      <TextStep
        title="איך קוראים לך?"
        label="השם שלך"
        value={form.userName}
        placeholder="הקלד את שמך"
        error={error}
        buttonText="הצטרפות למשפחה"
        isSubmitting={isSubmitting}
        onChange={(value) => onChange('userName', value)}
        onContinue={onContinue}
      />
    )
  }

  return (
    <main className="flow-screen">
      <FlowHeader step={step} onBack={onBack} isSubmitting={isSubmitting} />
      <section className="flow-content">{content}</section>
    </main>
  )
}

const joinStepIndexes: Record<JoinFamilySession['step'], number> = {
  family_name: 0,
  address: 1,
  address_confirmed: 2,
  family_code: 3,
  user_name: 4,
}

function App() {
  const {
    session,
    isInitializing,
    backendIdentityStatus,
    currentUser,
    backendIdentityError,
    invalidateAuthSession,
    retryBackendIdentity,
  } = useAuth()
  const [restoredDraft] = useState(() => loadOnboardingDraft())
  const [pendingCreateSuccess, setPendingCreateSuccess] = useState(
    () => loadPendingCreateSuccess(),
  )
  const [pendingJoinSuccess, setPendingJoinSuccess] = useState(
    () => loadPendingJoinSuccess(),
  )
  const [flow, setFlow] = useState<Flow>(restoredDraft?.flow ?? 'welcome')
  const [step, setStep] = useState(restoredDraft?.step ?? 0)
  const [form, setForm] = useState<FormData>(restoredDraft?.form ?? initialForm)
  const [createAttempts, setCreateAttempts] = useState(
    restoredDraft?.createAttempts ?? initialCreateValidationAttempts(),
  )
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [finalProcessingFlow, setFinalProcessingFlow] = useState<OnboardingFlow | null>(null)
  const [joinSessionReady, setJoinSessionReady] = useState(
    restoredDraft?.flow !== 'join',
  )
  const [joinLockedUntil, setJoinLockedUntil] = useState<string | null>(null)
  const retryBackendIdentityRef = useRef<() => void>(() => undefined)
  const authUserIdRef = useRef<string | undefined>(session?.user.id)

  useEffect(() => {
    retryBackendIdentityRef.current = retryBackendIdentity
  }, [retryBackendIdentity])

  useEffect(() => {
    authUserIdRef.current = session?.user.id
  }, [session?.user.id])

  const recheckLatestIdentity = useCallback(() => {
    retryBackendIdentityRef.current()
  }, [])
  const [runJoinRequest] = useState(() => createJoinRequestRunner(setIsSubmitting))
  // The factory stores this callback; it does not invoke or read the ref during render.
  // oxlint-disable-next-line react/refs
  const [createFamilySubmitter] = useState(() => createCreateFamilySubmitter({
    clearDraft: clearOnboardingDraft,
    markCreated: (payload) => {
      const pending = {
        version: 1 as const,
        flow: 'create' as const,
        authUserId: authUserIdRef.current ?? '',
        createdAt: new Date().toISOString(),
        familyName: payload.family_name,
        familyCode: payload.family_code,
        userName: payload.user_name,
      }
      savePendingCreateSuccess(pending)
      setPendingCreateSuccess(pending)
    },
    recheckIdentity: recheckLatestIdentity,
  }))
  // The factory stores this callback; it does not invoke or read the ref during render.
  // oxlint-disable-next-line react/refs
  const [joinFamilyCompleter] = useState(() => createJoinFamilyCompleter({
    clearDraft: clearOnboardingDraft,
    markJoined: (payload) => {
      const pending = {
        version: 1 as const,
        flow: 'join' as const,
        authUserId: authUserIdRef.current ?? '',
        createdAt: new Date().toISOString(),
        ...payload,
      }
      savePendingJoinSuccess(pending)
      setPendingJoinSuccess(pending)
    },
    recheckIdentity: recheckLatestIdentity,
  }))
  const [recoverInvalidAuthSession] = useState(() => createInvalidSessionRecovery({
    clearOnboardingDraft,
    clearPendingCreateSuccess,
    clearPendingJoinSuccess,
    resetOnboardingForLogin: () => {
      const resetForm = { ...initialForm }
      const resetAttempts = initialCreateValidationAttempts()
      setFlow('create')
      setStep(0)
      setForm(resetForm)
      setCreateAttempts(resetAttempts)
      setPendingCreateSuccess(null)
      setPendingJoinSuccess(null)
      setJoinSessionReady(true)
      setJoinLockedUntil(null)
      setFinalProcessingFlow(null)
      setIsSubmitting(false)
      setError('')
      saveOnboardingDraft({
        flow: 'create',
        step: 0,
        form: resetForm,
        createAttempts: resetAttempts,
      })
    },
    invalidateAuthSession,
  }))

  useEffect(() => {
    if (flow === 'welcome') return
    saveOnboardingDraft({ flow, step, form, createAttempts })
  }, [createAttempts, flow, form, step])

  useEffect(() => {
    if (backendIdentityStatus !== 'authenticated_mapped') return
    clearOnboardingDraft()
  }, [backendIdentityStatus])

  useEffect(() => {
    if (
      backendIdentityStatus === 'authenticated_mapped'
      && currentUser?.carplay_setup_status !== 'pending'
    ) {
      clearCarPlaySetupDraft()
    }
  }, [backendIdentityStatus, currentUser?.carplay_setup_status])

  const startFlow = (nextFlow: Exclude<Flow, 'welcome'>) => {
    const nextForm = { ...initialForm }
    setFlow(nextFlow)
    setStep(0)
    setForm(nextForm)
    setCreateAttempts(initialCreateValidationAttempts())
    setJoinSessionReady(nextFlow !== 'join')
    setJoinLockedUntil(null)
    setFinalProcessingFlow(null)
    setError('')
    saveOnboardingDraft({
      flow: nextFlow,
      step: 0,
      form: nextForm,
      createAttempts: initialCreateValidationAttempts(),
    })
  }

  const updateField = (field: keyof FormData, value: string) => {
    setForm((current) => ({
      ...current,
      [field]: value,
      ...(field === 'address'
        ? { resolvedAddress: '', addressResolutionToken: '' }
        : {}),
    }))
    setError('')
  }

  const currentField = () => {
    type EditableField = Exclude<
      keyof FormData,
      'resolvedAddress' | 'addressResolutionToken'
    >
    if (flow === 'create') return ['familyName', 'familyCode', 'address', 'address', 'userName'][step] as EditableField
    return ['familyName', 'address', 'address', 'familyCode', 'userName'][step] as EditableField
  }

  const applyJoinSession = useCallback((joinSession: JoinFamilySession) => {
    setStep(joinStepIndexes[joinSession.step])
    setForm((current) => {
      if (joinSession.reset) return { ...initialForm }
      return {
        ...current,
        familyName: joinSession.family_name ?? current.familyName,
        address: joinSession.normalized_address ?? current.address,
        resolvedAddress: joinSession.resolved_address ?? current.resolvedAddress,
      }
    })
    setJoinLockedUntil(null)
    setJoinSessionReady(true)
    setError('')
  }, [])

  const handleJoinFamilyError = useCallback((requestError: unknown) => {
    setJoinSessionReady(true)

    if (!(requestError instanceof OnboardingApiError)) {
      setError('לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.')
      return
    }

    if (requestError.code === 'AUTH_USER_ALREADY_MAPPED') {
      clearOnboardingDraft()
      retryBackendIdentity()
      return
    }

    if (requestError.code === 'UNAUTHORIZED') {
      setError(requestError.message)
      retryBackendIdentity()
      return
    }

    if (requestError.code === 'JOIN_LOCKED') {
      const resetForm = { ...initialForm }
      setForm(resetForm)
      setStep(0)
      setJoinLockedUntil(requestError.lockedUntil ?? null)
      setError(requestError.message)
      saveOnboardingDraft({
        flow: 'join',
        step: 0,
        form: resetForm,
        createAttempts: initialCreateValidationAttempts(),
      })
      return
    }

    if (requestError.code === 'INVALID_JOIN_STEP') {
      setError(requestError.message)
      return
    }

    setError(requestError.message)
  }, [retryBackendIdentity])

  useEffect(() => {
    if (
      flow !== 'join'
      || !session
      || joinSessionReady
      || backendIdentityStatus !== 'authenticated_unmapped'
    ) return

    void runJoinRequest(async () => {
      try {
        const joinSession = await startJoinFamily(session.access_token)
        applyJoinSession(joinSession)
      } catch (requestError) {
        handleJoinFamilyError(requestError)
      }
    })
  }, [
    applyJoinSession,
    backendIdentityStatus,
    flow,
    handleJoinFamilyError,
    joinSessionReady,
    runJoinRequest,
    session,
  ])

  const registerValidationFailure = (
    field: CreateValidationField,
    message: string,
  ) => {
    const result = registerCreateValidationFailure(createAttempts, field)

    if (result.exhausted) {
      const resetAttempts = initialCreateValidationAttempts()
      const resetForm = { ...initialForm }
      setCreateAttempts(resetAttempts)
      setForm(resetForm)
      setStep(0)
      setError(appendRemainingAttempts(message, 0))
      saveOnboardingDraft({
        flow: 'create',
        step: 0,
        form: resetForm,
        createAttempts: resetAttempts,
      })
      return
    }

    setCreateAttempts(result.attempts)
    setStep(field === 'familyCode' ? 1 : 2)
    setError(appendRemainingAttempts(message, result.remainingAttempts))
  }

  const handleCreateFamilyError = (requestError: unknown) => {
    if (!(requestError instanceof OnboardingApiError)) {
      setError('לא הצלחנו להשלים את הפעולה כרגע. נסו שוב בעוד רגע.')
      return
    }

    if (requestError.code === 'AUTH_USER_ALREADY_MAPPED') {
      clearOnboardingDraft()
      retryBackendIdentity()
      return
    }

    if (requestError.code === 'UNAUTHORIZED') {
      setError(requestError.message)
      retryBackendIdentity()
      return
    }

    if (requestError.code === 'AUTH_SESSION_INVALID') {
      void recoverInvalidAuthSession(requestError.message)
      return
    }

    if (
      requestError.code === 'INVALID_FAMILY_CODE'
      || requestError.code === 'FAMILY_CODE_TAKEN'
    ) {
      registerValidationFailure('familyCode', requestError.message)
      return
    }

    if (
      requestError.code === 'INVALID_ADDRESS_FORMAT'
      || requestError.code === 'ADDRESS_NOT_FOUND'
    ) {
      registerValidationFailure('address', requestError.message)
      return
    }

    if (requestError.code === 'ADDRESS_RESOLUTION_EXPIRED') {
      setForm((current) => ({
        ...current,
        resolvedAddress: '',
        addressResolutionToken: '',
      }))
      setStep(2)
      setError(requestError.message)
      return
    }

    const errorSteps: Partial<Record<typeof requestError.code, number>> = {
      INVALID_FAMILY_NAME: 0,
      FAMILY_ALREADY_EXISTS_AT_ADDRESS: 2,
      INVALID_USER_NAME: 4,
    }
    const targetStep = errorSteps[requestError.code]
    if (targetStep !== undefined) setStep(targetStep)
    setError(requestError.message)
  }

  const resolveCreateAddress = async (address: string) => {
    if (!session) {
      retryBackendIdentity()
      return
    }

    setIsSubmitting(true)
    try {
      const resolved = await resolveCreateFamilyAddress(
        session.access_token,
        address,
      )
      setForm((current) => ({
        ...current,
        address: resolved.normalized_address,
        resolvedAddress: resolved.display_address,
        addressResolutionToken: resolved.resolution_token,
      }))
      setError('')
      setStep(3)
    } catch (requestError) {
      handleCreateFamilyError(requestError)
    } finally {
      setIsSubmitting(false)
    }
  }

  const submitCreateFamily = async () => {
    if (!session) {
      retryBackendIdentity()
      return
    }

    setError('')
    setFinalProcessingFlow('create')
    setIsSubmitting(true)
    try {
      await createFamilySubmitter(session.access_token, {
        family_name: form.familyName,
        family_code: form.familyCode,
        address_resolution_token: form.addressResolutionToken ?? '',
        user_name: form.userName,
      })
      setError('')
    } catch (requestError) {
      setFinalProcessingFlow(null)
      handleCreateFamilyError(requestError)
    } finally {
      setIsSubmitting(false)
    }
  }

  const submitJoinName = (familyName: string) => {
    if (!session) {
      retryBackendIdentity()
      return
    }
    void runJoinRequest(async () => {
      try {
        applyJoinSession(
          await submitJoinFamilyName(session.access_token, familyName),
        )
      } catch (requestError) {
        handleJoinFamilyError(requestError)
      }
    })
  }

  const submitJoinAddress = (address: string) => {
    if (!session) {
      retryBackendIdentity()
      return
    }
    void runJoinRequest(async () => {
      try {
        applyJoinSession(
          await submitJoinFamilyAddress(session.access_token, address),
        )
      } catch (requestError) {
        handleJoinFamilyError(requestError)
      }
    })
  }

  const confirmJoinAddress = (confirmed: boolean) => {
    if (!session) {
      retryBackendIdentity()
      return
    }
    void runJoinRequest(async () => {
      try {
        applyJoinSession(
          await confirmJoinFamilyAddress(session.access_token, confirmed),
        )
      } catch (requestError) {
        handleJoinFamilyError(requestError)
      }
    })
  }

  const submitJoinCode = (familyCode: string) => {
    if (!session) {
      retryBackendIdentity()
      return
    }
    void runJoinRequest(async () => {
      try {
        applyJoinSession(
          await submitJoinFamilyCode(session.access_token, familyCode),
        )
      } catch (requestError) {
        handleJoinFamilyError(requestError)
      }
    })
  }

  const finishJoinFamily = (userName: string) => {
    if (!session) {
      retryBackendIdentity()
      return
    }
    setError('')
    setFinalProcessingFlow('join')
    void runJoinRequest(async () => {
      try {
        await joinFamilyCompleter(session.access_token, userName, form.familyName)
        setError('')
      } catch (requestError) {
        setFinalProcessingFlow(null)
        handleJoinFamilyError(requestError)
      }
    })
  }

  const continueFlow = () => {
    if (isSubmitting) return
    const field = currentField()
    const value = form[field].trim()

    if (
      (field === 'familyName' || field === 'userName')
      && !isValidHumanName(value)
    ) {
      setError(humanNameError(field))
      return
    }

    if (flow === 'join') {
      if (step === 0) submitJoinName(value)
      else if (step === 1) submitJoinAddress(value)
      else if (step === 2) confirmJoinAddress(true)
      else if (step === 3) submitJoinCode(value)
      else finishJoinFamily(value)
      return
    }

    if (!value) {
      if (flow === 'create' && field === 'familyCode') {
        registerValidationFailure(
          'familyCode',
          'קוד המשפחה חייב להכיל בדיוק 6 ספרות.',
        )
        return
      }
      if (flow === 'create' && field === 'address') {
        registerValidationFailure(
          'address',
          'כתובת לא נכתבה בפורמט הנכון. יש לכתוב: עיר, רחוב, מספר בית.',
        )
        return
      }
      setError('יש למלא את השדה כדי להמשיך.')
      return
    }

    if (field === 'familyCode' && !/^\d{6}$/.test(value)) {
      if (flow === 'create') {
        registerValidationFailure(
          'familyCode',
          'קוד המשפחה חייב להכיל בדיוק 6 ספרות.',
        )
        return
      }
      setError('קוד המשפחה חייב להכיל בדיוק 6 ספרות.')
      return
    }

    if (field === 'address' && !isValidAddress(value)) {
      if (flow === 'create') {
        registerValidationFailure(
          'address',
          'כתובת לא נכתבה בפורמט הנכון. יש לכתוב: עיר, רחוב, מספר בית.',
        )
        return
      }
      setError('כתובת לא נכתבה בפורמט הנכון. יש לכתוב: עיר, רחוב, מספר בית.')
      return
    }

    if (flow === 'create' && step === 2) {
      void resolveCreateAddress(value)
      return
    }

    if (flow === 'create' && step === 4) {
      void submitCreateFamily()
      return
    }

    setError('')
    setStep((current) => current + 1)
  }

  const goBack = () => {
    if (isSubmitting) return
    setError('')
    if (step === 0) {
      clearOnboardingDraft()
      setFlow('welcome')
      return
    }
    setStep((current) => current - 1)
  }

  const finishPrototype = () => {
    clearOnboardingDraft()
    setFlow('welcome')
    setStep(0)
    setForm({ ...initialForm })
    setCreateAttempts(initialCreateValidationAttempts())
    setJoinSessionReady(true)
    setJoinLockedUntil(null)
    setFinalProcessingFlow(null)
    setError('')
    setIsSubmitting(false)
  }

  const cancelAuthentication = () => {
    clearOnboardingDraft()
    setFlow('welcome')
    setStep(0)
    setForm({ ...initialForm })
    setCreateAttempts(initialCreateValidationAttempts())
    setJoinSessionReady(true)
    setJoinLockedUntil(null)
    setFinalProcessingFlow(null)
    setError('')
    setIsSubmitting(false)
  }

  const intent = flow === 'welcome' ? null : flow
  const createSuccessMatchesSession = isPendingSuccessForAuthUser(
    pendingCreateSuccess,
    session?.user.id,
  )
  const joinSuccessMatchesSession = isPendingSuccessForAuthUser(
    pendingJoinSuccess,
    session?.user.id,
  )
  const hasConflictingSuccessMarkers = createSuccessMatchesSession && joinSuccessMatchesSession
  const destination = resolveAppDestination({
    isInitializing,
    identityStatus: backendIdentityStatus,
    intent,
    hasCurrentUser: Boolean(currentUser),
    carPlaySetupStatus: currentUser?.carplay_setup_status,
    hasPendingCreateSuccess: createSuccessMatchesSession && !hasConflictingSuccessMarkers,
    hasPendingJoinSuccess: joinSuccessMatchesSession && !hasConflictingSuccessMarkers,
    finalProcessingFlow,
  })

  if (destination === 'create_processing') {
    return <FinalProcessingScreen flow="create" />
  }

  if (destination === 'join_processing') {
    return <FinalProcessingScreen flow="join" />
  }

  if (destination === 'loading') {
    return <IdentityLoadingScreen />
  }

  if (destination === 'error') {
    return (
      <IdentityErrorScreen
        message={backendIdentityError}
        onRetry={retryBackendIdentity}
      />
    )
  }

  if (destination === 'create_success' && pendingCreateSuccess) {
    return (
      <SuccessScreen
        flow="create"
        form={{
          familyName: pendingCreateSuccess.familyName,
          familyCode: pendingCreateSuccess.familyCode,
          userName: pendingCreateSuccess.userName,
          address: '',
          resolvedAddress: '',
        }}
        onFinish={() => {
          clearPendingCreateSuccess()
          setPendingCreateSuccess(null)
          setFinalProcessingFlow(null)
        }}
      />
    )
  }

  if (destination === 'join_success' && pendingJoinSuccess) {
    return (
      <SuccessScreen
        flow="join"
        form={{
          familyName: pendingJoinSuccess.familyName,
          familyCode: '',
          userName: pendingJoinSuccess.userName,
          address: '',
          resolvedAddress: '',
        }}
        onFinish={() => {
          clearPendingJoinSuccess()
          setPendingJoinSuccess(null)
          setFinalProcessingFlow(null)
        }}
      />
    )
  }

  if (destination === 'carplay_setup' && currentUser && session) {
    return (
      <CarPlaySetupWizard
        accessToken={session.access_token}
        authUserId={session.user.id}
        onBack={() => undefined}
        onStatusChange={async (status) => {
          await updateCarPlaySetupStatus(session.access_token, status)
          retryBackendIdentity()
        }}
      />
    )
  }

  if (destination === 'main' && currentUser) {
    return <MainAppScreen user={currentUser} />
  }

  if (destination === 'welcome') {
    return <WelcomeScreen onChoose={startFlow} />
  }

  if (destination === 'auth' && intent) {
    return (
      <AuthGate
        flow={intent}
        onBack={cancelAuthentication}
      />
    )
  }

  if (flow === 'join' && !joinSessionReady) {
    return <IdentityLoadingScreen />
  }

  if (flow === 'join' && joinLockedUntil) {
    return (
      <JoinLockedScreen
        message={error}
        lockedUntil={joinLockedUntil}
        onRetry={() => setJoinSessionReady(false)}
        onBack={() => {
          clearOnboardingDraft()
          setFlow('welcome')
          setJoinLockedUntil(null)
          setError('')
        }}
      />
    )
  }

  if (flow === 'welcome') {
    return <WelcomeScreen onChoose={startFlow} />
  }

  return (
    <FlowScreen
      flow={flow}
      step={step}
      form={form}
      error={error}
      isSubmitting={isSubmitting}
      onChange={updateField}
      onBack={goBack}
      onContinue={continueFlow}
      onChangeAddress={() => {
        if (flow === 'join') {
          confirmJoinAddress(false)
          return
        }
        setError('')
        setForm((current) => ({
          ...current,
          resolvedAddress: '',
          addressResolutionToken: '',
        }))
        setStep(flow === 'create' ? 2 : 1)
      }}
      onFinish={finishPrototype}
    />
  )
}

export default App
