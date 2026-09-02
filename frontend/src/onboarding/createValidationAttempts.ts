export type CreateValidationField = 'familyCode' | 'address'

export type CreateValidationAttempts = Record<CreateValidationField, number>

export const maxCreateValidationAttempts = 3

export function initialCreateValidationAttempts(): CreateValidationAttempts {
  return {
    familyCode: 0,
    address: 0,
  }
}

export function registerCreateValidationFailure(
  attempts: CreateValidationAttempts,
  field: CreateValidationField,
) {
  const failedAttempts = Math.min(
    attempts[field] + 1,
    maxCreateValidationAttempts,
  )
  const remainingAttempts = maxCreateValidationAttempts - failedAttempts

  return {
    attempts: {
      ...attempts,
      [field]: failedAttempts,
    },
    remainingAttempts,
    exhausted: remainingAttempts === 0,
  }
}

export function appendRemainingAttempts(
  message: string,
  remainingAttempts: number,
) {
  if (remainingAttempts === 2) return `${message} נותרו 2 ניסיונות.`
  if (remainingAttempts === 1) return `${message} נותר ניסיון אחרון.`
  return `${message} לא נותרו ניסיונות. תהליך יצירת המשפחה אופס ואפשר להתחיל מחדש.`
}
