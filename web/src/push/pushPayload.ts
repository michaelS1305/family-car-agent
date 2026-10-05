export type PushNotificationPayload = {
  title: 'Family Car Agent'
  body: string
  url: '/'
  tag: string
  generation?: string
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
    || (payload.generation !== undefined && (typeof payload.generation !== 'string' || !/^[a-f0-9]{64}$/.test(payload.generation)))
  ) return null
  return payload as PushNotificationPayload
}
