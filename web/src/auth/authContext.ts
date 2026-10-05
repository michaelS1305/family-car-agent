import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'
import type { InternalUser } from '../api/apiClient'

export type BackendIdentityStatus =
  | 'checking'
  | 'unauthenticated'
  | 'authenticated_unmapped'
  | 'authenticated_mapped'
  | 'error'

export type AuthContextValue = {
  session: Session | null
  isInitializing: boolean
  authError: string
  backendIdentityStatus: BackendIdentityStatus
  currentUser: InternalUser | null
  backendIdentityError: string
  clearAuthError: () => void
  invalidateAuthSession: (message: string) => Promise<void>
  retryBackendIdentity: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
