import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  applyPreferenceAttributes,
  loadAppPreferences,
  saveAppPreferences,
} from './appPreferences'
import { AppPreferencesContext, type AppPreferencesValue } from './appPreferencesContext'

function browserStorage() {
  return typeof window === 'undefined' ? null : window.localStorage
}

function systemDarkQuery() {
  return typeof window === 'undefined' ? null : window.matchMedia('(prefers-color-scheme: dark)')
}

export function AppPreferencesProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState(() => loadAppPreferences(browserStorage()))
  const [systemPrefersDark, setSystemPrefersDark] = useState(() => systemDarkQuery()?.matches ?? false)

  useEffect(() => {
    const query = systemDarkQuery()
    if (!query) return
    const update = (event: MediaQueryListEvent) => setSystemPrefersDark(event.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useLayoutEffect(() => {
    applyPreferenceAttributes(document.documentElement, preferences, systemPrefersDark)
    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    if (themeColor) {
      themeColor.content = document.documentElement.dataset.effectiveTheme === 'dark'
        ? '#111820'
        : '#fffefc'
    }
  }, [preferences, systemPrefersDark])

  const value = useMemo<AppPreferencesValue>(() => ({
    ...preferences,
    setTheme: (theme) => {
      setPreferences((current) => {
        const next = { ...current, theme }
        saveAppPreferences(next, browserStorage())
        return next
      })
    },
    setTextSize: (textSize) => {
      setPreferences((current) => {
        const next = { ...current, textSize }
        saveAppPreferences(next, browserStorage())
        return next
      })
    },
  }), [preferences])

  return <AppPreferencesContext.Provider value={value}>{children}</AppPreferencesContext.Provider>
}
