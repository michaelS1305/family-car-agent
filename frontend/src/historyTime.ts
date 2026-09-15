const HISTORY_DATE = new Intl.DateTimeFormat('he-IL', {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Jerusalem',
})

const HISTORY_TIME = new Intl.DateTimeFormat('he-IL', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'Asia/Jerusalem',
})

export function formatHistoryDate(value: string) {
  return HISTORY_DATE.format(new Date(value))
}

export function formatHistoryTime(value: string) {
  return HISTORY_TIME.format(new Date(value))
}
