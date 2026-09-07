import { createContext } from 'react'
import type { AppPreferences, TextSizePreference, ThemePreference } from './appPreferences'

export type AppPreferencesValue = AppPreferences & {
  setTheme: (theme: ThemePreference) => void
  setTextSize: (textSize: TextSizePreference) => void
}

export const AppPreferencesContext = createContext<AppPreferencesValue | null>(null)
