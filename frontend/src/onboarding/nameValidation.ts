const apostrophes = new Set(["'"])
const infixSeparators = new Set([' ', '-'])
const isLetter = (character: string) => /^\p{L}$/u.test(character)

export function normalizeHumanName(value: string) {
  return value
    .normalize('NFC')
    .trim()
    .replace(/\s+/gu, ' ')
    .replace(/[’׳]/gu, "'")
    .replace(/[‐‑‒–—−]/gu, '-')
}

export function isValidHumanName(value: string) {
  const normalized = normalizeHumanName(value)
  const characters = Array.from(normalized)
  if (
    characters.length === 0
    || !characters.some(isLetter)
    || /\p{N}/u.test(normalized)
    || !isLetter(characters[0])
  ) return false

  return characters.every((character, index) => {
    if (isLetter(character)) return true

    const previousIsLetter = index > 0 && isLetter(characters[index - 1])
    const nextIsLetter = index < characters.length - 1
      && isLetter(characters[index + 1])

    if (apostrophes.has(character)) {
      return previousIsLetter && (index === characters.length - 1 || nextIsLetter)
    }
    if (infixSeparators.has(character)) {
      return previousIsLetter && nextIsLetter
    }
    return false
  })
}

export function humanNameError(field: 'familyName' | 'userName') {
  return field === 'familyName'
    ? 'שם המשפחה יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.'
    : 'השם הפרטי יכול להכיל אותיות, רווחים, מקף או גרש, ללא ספרות.'
}
