import { useState } from 'react'
import { useAuth } from '../auth/authContext'
import { signInWithGoogle } from '../auth/authService'
import type { OnboardingFlow } from '../auth/onboardingDraft'

type AuthGateProps = {
  flow?: OnboardingFlow
  onBack?: () => void
}

export function AuthGate({ flow, onBack }: AuthGateProps) {
  const { isInitializing, authError, clearAuthError } = useAuth()
  const [isSigningIn, setIsSigningIn] = useState(false)
  const [signInError, setSignInError] = useState('')

  const startGoogleSignIn = async () => {
    if (isSigningIn) return

    clearAuthError()
    setSignInError('')
    setIsSigningIn(true)

    try {
      await signInWithGoogle()
    } catch {
      setSignInError('לא הצלחנו לפתוח את ההתחברות עם Google. נסו שוב.')
      setIsSigningIn(false)
    }
  }

  const displayedError = signInError || authError
  const flowLabel = flow === 'create'
    ? 'יצירת המשפחה'
    : flow === 'join'
      ? 'ההצטרפות למשפחה'
      : 'השימוש באפליקציה'

  return (
    <main className="flow-screen auth-screen">
      <header className="flow-header">
        {onBack ? (
          <button type="button" className="back-button" onClick={onBack} aria-label="חזרה">
            →
          </button>
        ) : <span className="header-spacer" aria-hidden="true" />}
        <span className="progress-label">התחברות</span>
        <span className="header-spacer" aria-hidden="true" />
      </header>

      <section className="flow-content auth-content">
        <div className="auth-card">
          <div className="auth-mark" aria-hidden="true">✓</div>
          <div className="step-copy">
            <h1>מתחברים וממשיכים</h1>
            <p>
              כדי להשלים את {flowLabel}, התחברו באמצעות החשבון האישי שלכם.
            </p>
          </div>

          {isInitializing ? (
            <div className="auth-loading" role="status">
              <span className="auth-spinner" aria-hidden="true" />
              בודקים אם כבר התחברתם…
            </div>
          ) : (
            <div className="auth-actions">
              <button
                type="button"
                className="auth-provider-button"
                disabled={isSigningIn}
                onClick={() => void startGoogleSignIn()}
                aria-label="התחברות באמצעות Google"
              >
                <img
                  className="official-signin-image"
                  src="/auth/google-sign-in-light-pill@4x.png"
                  alt=""
                  aria-hidden="true"
                />
              </button>
              {isSigningIn && (
                <p className="auth-provider-status" role="status">
                  מעבירים ל-Google…
                </p>
              )}
            </div>
          )}

          {displayedError && (
            <p className="auth-error" role="alert">{displayedError}</p>
          )}

          <p className="auth-note">
            פרטי ההתחברות נשמרים ומנוהלים על ידי Supabase Auth.
          </p>
        </div>
      </section>
    </main>
  )
}
