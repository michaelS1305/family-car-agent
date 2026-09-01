import type { Session } from '@supabase/supabase-js'
import { getSupabaseClient } from '../lib/supabase'

const oauthErrorParameters = ['error', 'error_code', 'error_description']
let cachedOAuthCallbackFailure: boolean | undefined

function getOAuthRedirectUrl() {
  return new URL(import.meta.env.BASE_URL, window.location.origin).toString()
}

async function signInWithGoogleProvider() {
  const { error } = await getSupabaseClient().auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: getOAuthRedirectUrl(),
    },
  })

  if (error) throw error
}

export function signInWithGoogle() {
  return signInWithGoogleProvider()
}

export async function signOutLocal() {
  const { error } = await getSupabaseClient().auth.signOut({ scope: 'local' })
  if (error) throw error
}

export async function getCurrentSession() {
  const { data, error } = await getSupabaseClient().auth.getSession()
  if (error) throw error
  return data.session
}

export async function refreshCurrentSession() {
  const { data, error } = await getSupabaseClient().auth.refreshSession()
  if (error) throw error
  return data.session
}

export function subscribeToAuthState(onSession: (session: Session | null) => void) {
  const { data } = getSupabaseClient().auth.onAuthStateChange((_event, session) => {
    onSession(session)
  })

  return () => data.subscription.unsubscribe()
}

export function consumeOAuthCallbackFailure() {
  if (cachedOAuthCallbackFailure !== undefined) {
    return cachedOAuthCallbackFailure
  }

  const url = new URL(window.location.href)
  const hashParameters = new URLSearchParams(url.hash.replace(/^#/, ''))
  const hasFailure = oauthErrorParameters.some(
    (parameter) => url.searchParams.has(parameter) || hashParameters.has(parameter),
  )

  cachedOAuthCallbackFailure = hasFailure
  if (!hasFailure) return false

  oauthErrorParameters.forEach((parameter) => {
    url.searchParams.delete(parameter)
    hashParameters.delete(parameter)
  })
  url.hash = hashParameters.toString()
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)

  return cachedOAuthCallbackFailure
}
