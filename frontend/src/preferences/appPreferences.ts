export type ThemePreference = 'system' | 'light' | 'dark'
export type TextSizePreference = 'small' | 'normal' | 'large'

export type AppPreferences = {
  theme: ThemePreference
  textSize: TextSizePreference
}

export const APP_PREFERENCES_STORAGE_KEY = 'family-car-agent:preferences'
export const DEFAULT_APP_PREFERENCES: AppPreferences = {
  theme: 'system',
  textSize: 'normal',
}

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>

function isTheme(value: unknown): value is ThemePreference {
  return value === 'system' || value === 'light' || value === 'dark'
}

function isTextSize(value: unknown): value is TextSizePreference {
  return value === 'small' || value === 'normal' || value === 'large'
}

export function parseAppPreferences(value: unknown): AppPreferences {
  if (!value || typeof value !== 'object') return DEFAULT_APP_PREFERENCES
  const candidate = value as Partial<AppPreferences>
  return {
    theme: isTheme(candidate.theme) ? candidate.theme : DEFAULT_APP_PREFERENCES.theme,
    textSize: isTextSize(candidate.textSize)
      ? candidate.textSize
      : DEFAULT_APP_PREFERENCES.textSize,
  }
}

export function loadAppPreferences(storage?: PreferenceStorage | null): AppPreferences {
  try {
    const raw = storage?.getItem(APP_PREFERENCES_STORAGE_KEY)
    return raw ? parseAppPreferences(JSON.parse(raw)) : DEFAULT_APP_PREFERENCES
  } catch {
    return DEFAULT_APP_PREFERENCES
  }
}

export function saveAppPreferences(
  preferences: AppPreferences,
  storage?: PreferenceStorage | null,
) {
  try {
    storage?.setItem(APP_PREFERENCES_STORAGE_KEY, JSON.stringify(preferences))
  } catch {
    // Preferences remain active for this session if storage is unavailable.
  }
}

export function effectiveTheme(theme: ThemePreference, systemPrefersDark: boolean) {
  return theme === 'system' ? (systemPrefersDark ? 'dark' : 'light') : theme
}

export function applyPreferenceAttributes(
  root: Pick<HTMLElement, 'dataset'>,
  preferences: AppPreferences,
  systemPrefersDark: boolean,
) {
  root.dataset.theme = preferences.theme
  root.dataset.effectiveTheme = effectiveTheme(preferences.theme, systemPrefersDark)
  root.dataset.textSize = preferences.textSize
}
