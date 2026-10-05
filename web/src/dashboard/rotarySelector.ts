export type DashboardCategory = {
  id: 'family' | 'cars' | 'settings' | 'history' | 'reservations'
  label: 'משפחה' | 'רכבים' | 'הגדרות' | 'היסטוריה' | 'מרכז הזמנות'
  icon: 'people' | 'car' | 'settings' | 'history' | 'calendar'
}

export const DASHBOARD_CATEGORIES: readonly DashboardCategory[] = [
  { id: 'family', label: 'משפחה', icon: 'people' },
  { id: 'cars', label: 'רכבים', icon: 'car' },
  { id: 'settings', label: 'הגדרות', icon: 'settings' },
  { id: 'history', label: 'היסטוריה', icon: 'history' },
  { id: 'reservations', label: 'מרכז הזמנות', icon: 'calendar' },
] as const

export const ROTARY_STEP_DEGREES = 360 / DASHBOARD_CATEGORIES.length

function positiveModulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor
}

export function normalizeAngleDelta(delta: number) {
  return positiveModulo(delta + 180, 360) - 180
}

export function categoryIndexForRotation(rotation: number) {
  return positiveModulo(Math.round(rotation / ROTARY_STEP_DEGREES), DASHBOARD_CATEGORIES.length)
}

export function snapRotaryRotation(rotation: number) {
  return Math.round(rotation / ROTARY_STEP_DEGREES) * ROTARY_STEP_DEGREES
}

export function moveRotarySelection(rotation: number, direction: -1 | 1) {
  return snapRotaryRotation(rotation) + (direction * ROTARY_STEP_DEGREES)
}

export function categoryPosition(index: number, radiusPercent = 42) {
  const angle = (-90 + (index * ROTARY_STEP_DEGREES)) * (Math.PI / 180)
  return {
    left: 50 + (Math.cos(angle) * radiusPercent),
    top: 50 + (Math.sin(angle) * radiusPercent),
  }
}

export function confirmDashboardCategory(index: number) {
  return DASHBOARD_CATEGORIES[positiveModulo(index, DASHBOARD_CATEGORIES.length)]
}
