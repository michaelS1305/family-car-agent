import { useContext } from 'react'
import { AppPreferencesContext } from './appPreferencesContext'

export function useAppPreferences() {
  const value = useContext(AppPreferencesContext)
  if (!value) throw new Error('useAppPreferences must be used inside AppPreferencesProvider')
  return value
}
