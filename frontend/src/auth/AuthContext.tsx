import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { ApiRequestError, getCurrentUser, type InternalUser } from '../api/apiClient'
import {
  consumeOAuthCallbackFailure,
  getCurrentSession,
  refreshCurrentSession,
  signOutLocal,
  subscribeToAuthState,
} from './authService'
import { SupabaseConfigurationError } from '../lib/supabase'
import {
  AuthContext,
  type AuthContextValue,
  type BackendIdentityStatus,
} from './authContext'
import {
  classifyAuthSessionUpdate,
  wasSessionReadSuperseded,
} from './authSessionTransition'

function readableAuthError(error: unknown) {
  if (error instanceof SupabaseConfigurationError) {
    return 'ההתחברות עדיין לא הוגדרה בסביבה הזו.'
  }
  return 'לא הצלחנו לבדוק את מצב ההתחברות. בדקו את החיבור ונסו שוב.'
}

function readableBackendIdentityError(error: unknown) {
  if (error instanceof ApiRequestError && error.kind === 'network') {
    return 'לא הצלחנו להתחבר לשרת. בדקו את החיבור ונסו שוב.'
  }
  return 'לא הצלחנו לבדוק את פרטי המשתמש כרגע. נסו שוב בעוד רגע.'
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)
  const [authError, setAuthError] = useState('')
  const [backendIdentityStatus, setBackendIdentityStatus] = useState<BackendIdentityStatus>('checking')
  const [currentUser, setCurrentUser] = useState<InternalUser | null>(null)
  const [backendIdentityError, setBackendIdentityError] = useState('')
  const [identityCheckAttempt, setIdentityCheckAttempt] = useState(0)
  const unauthorizedRefreshAttempted = useRef(false)
  const appliedAccessTokenRef = useRef<string | null | undefined>(undefined)

  const applySession = useCallback((nextSession: Session | null) => {
    const nextAccessToken = nextSession?.access_token ?? null
    const update = classifyAuthSessionUpdate(
      appliedAccessTokenRef.current,
      nextAccessToken,
    )

    if (update === 'same_token') return

    appliedAccessTokenRef.current = nextAccessToken
    setSession(nextSession)
    setCurrentUser(null)
    setBackendIdentityError('')
    setBackendIdentityStatus(nextSession ? 'checking' : 'unauthenticated')
    if (!nextSession) unauthorizedRefreshAttempted.current = false
    setAuthError('')
    setIsInitializing(false)
  }, [])

  useEffect(() => {
    let active = true
    let oauthCallbackFailed = false
    let unsubscribe: () => void = () => undefined
    let authEventRevision = 0

    const initializeAuth = async () => {
      oauthCallbackFailed = consumeOAuthCallbackFailure()
      unsubscribe = subscribeToAuthState((nextSession) => {
        if (!active) return
        authEventRevision += 1
        applySession(nextSession)
      })

      const revisionWhenSessionReadStarted = authEventRevision
      let currentSession: Session | null
      try {
        currentSession = await getCurrentSession()
      } catch (error) {
        if (wasSessionReadSuperseded(
          revisionWhenSessionReadStarted,
          authEventRevision,
        )) return
        throw error
      }
      if (!active) return

      if (!wasSessionReadSuperseded(
        revisionWhenSessionReadStarted,
        authEventRevision,
      )) {
        applySession(currentSession)
      }

      if (oauthCallbackFailed && appliedAccessTokenRef.current === null) {
        setAuthError('ההתחברות בוטלה או לא הושלמה. אפשר לנסות שוב.')
      }
    }

    void initializeAuth().catch((error: unknown) => {
      if (!active) return
      appliedAccessTokenRef.current = null
      setSession(null)
      setCurrentUser(null)
      setBackendIdentityStatus('unauthenticated')
      setAuthError(
        oauthCallbackFailed
          ? 'ההתחברות בוטלה או לא הושלמה. אפשר לנסות שוב.'
          : readableAuthError(error),
      )
      setIsInitializing(false)
    })

    return () => {
      active = false
      unsubscribe()
    }
  }, [applySession])

  useEffect(() => {
    if (isInitializing) return

    const accessToken = session?.access_token
    if (!accessToken) return

    let active = true
    const controller = new AbortController()

    const clearInvalidSession = async () => {
      try {
        await signOutLocal()
      } catch {
        // The UI still treats a backend-rejected session as unauthenticated.
      }
      if (!active) return
      appliedAccessTokenRef.current = null
      setSession(null)
      setCurrentUser(null)
      setBackendIdentityError('')
      setBackendIdentityStatus('unauthenticated')
    }

    const checkBackendIdentity = async () => {
      setBackendIdentityStatus('checking')
      setBackendIdentityError('')

      try {
        const result = await getCurrentUser(accessToken, { signal: controller.signal })
        if (!active) return

        if (result.status === 'mapped') {
          unauthorizedRefreshAttempted.current = false
          setCurrentUser(result.user)
          setBackendIdentityStatus('authenticated_mapped')
          return
        }

        setCurrentUser(null)
        if (result.status === 'unmapped') {
          unauthorizedRefreshAttempted.current = false
          setBackendIdentityStatus('authenticated_unmapped')
          return
        }

        if (!unauthorizedRefreshAttempted.current) {
          unauthorizedRefreshAttempted.current = true
          try {
            const refreshedSession = await refreshCurrentSession()
            if (!active) return
            if (refreshedSession?.access_token && refreshedSession.access_token !== accessToken) {
              applySession(refreshedSession)
              return
            }
          } catch {
            // A rejected token that Supabase cannot refresh is cleared locally below.
          }
        }

        await clearInvalidSession()
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === 'AbortError')) return
        setCurrentUser(null)
        setBackendIdentityError(readableBackendIdentityError(error))
        setBackendIdentityStatus('error')
      }
    }

    void checkBackendIdentity()

    return () => {
      active = false
      controller.abort()
    }
  }, [applySession, identityCheckAttempt, isInitializing, session?.access_token])

  const retryBackendIdentity = useCallback(() => {
    if (!session) return
    setBackendIdentityStatus('checking')
    setIdentityCheckAttempt((attempt) => attempt + 1)
  }, [session])

  const invalidateAuthSession = useCallback(async (message: string) => {
    try {
      await signOutLocal()
    } catch {
      // A backend-rejected identity must still be cleared from the UI locally.
    }
    unauthorizedRefreshAttempted.current = false
    appliedAccessTokenRef.current = null
    setSession(null)
    setCurrentUser(null)
    setBackendIdentityError('')
    setBackendIdentityStatus('unauthenticated')
    setAuthError(message)
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    session,
    isInitializing,
    authError,
    backendIdentityStatus,
    currentUser,
    backendIdentityError,
    clearAuthError: () => setAuthError(''),
    invalidateAuthSession,
    retryBackendIdentity,
  }), [
    authError,
    backendIdentityError,
    backendIdentityStatus,
    currentUser,
    isInitializing,
    invalidateAuthSession,
    retryBackendIdentity,
    session,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
