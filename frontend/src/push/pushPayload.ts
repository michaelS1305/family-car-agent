export type PushNotificationPayload = {
  title: 'Family Car Agent'
  body: string
  url: '/'
  tag: string
}

export function parsePushNotificationPayload(value: unknown): PushNotificationPayload | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Partial<PushNotificationPayload>
  const validBody = payload.body === 'הרכב התפנה'
    || (typeof payload.body === 'string' && /^.{1,120} לקח את הרכב$/u.test(payload.body))
  if (
    payload.title !== 'Family Car Agent'
    || !validBody
    || payload.url !== '/'
    || typeof payload.tag !== 'string'
    || !/^car-event-\d+$/.test(payload.tag)
  ) return null
  return payload as PushNotificationPayload
}
