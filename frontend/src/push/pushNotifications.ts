import {
  getPushConfig,
  registerPushSubscription,
  removePushSubscription,
  type BrowserPushSubscription,
  type PushConfig,
} from '../api/apiClient.ts'
import { digestPushGeneration, generationStore, retirePushGeneration, beginPushActivation, enablePushGeneration, withPushDisplayLock } from './pushGeneration.ts'

export type PushCapability = 'supported' | 'unsupported'
export type CurrentDevicePushState =
  | 'subscribed'
  | 'unsubscribed'
  | 'denied'
  | 'unsupported'

export function detectPushCapability(): PushCapability {
  return (
    typeof window !== 'undefined'
    && window.isSecureContext
    && 'serviceWorker' in navigator
    && 'PushManager' in window
    && 'Notification' in window
  ) ? 'supported' : 'unsupported'
}

export function currentNotificationPermission(): NotificationPermission | 'unsupported' {
  return detectPushCapability() === 'supported' ? Notification.permission : 'unsupported'
}

export function notificationPermissionLabel(
  permission: ReturnType<typeof currentNotificationPermission>,
) {
  if (permission === 'unsupported') return 'לא נתמך'
  if (permission === 'granted') return 'מופעלות'
  if (permission === 'denied') return 'חסומות'
  return 'לא הופעלו'
}

export function preloadPushConfiguration(accessToken: string) {
  return getPushConfig(accessToken)
}

export async function inspectCurrentDevicePushState(): Promise<CurrentDevicePushState> {
  if (detectPushCapability() !== 'supported') return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  if (Notification.permission !== 'granted') return 'unsubscribed'
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return 'unsubscribed'
  const state = await generationStore.read()
  const serialized = serializeSubscription(subscription)
  const generation = await digestPushGeneration(serialized.endpoint, serialized.keys.p256dh, serialized.keys.auth)
  return state?.enabled && state.generation === generation ? 'subscribed' : 'unsubscribed'
}

export function urlBase64ToUint8Array(value: string) {
  const padding = '='.repeat((4 - (value.length % 4)) % 4)
  const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/')
  const bytes = atob(base64)
  return Uint8Array.from(bytes, (character) => character.charCodeAt(0))
}

function serializeSubscription(subscription: PushSubscription): BrowserPushSubscription {
  const json = subscription.toJSON()
  const p256dh = json.keys?.p256dh
  const auth = json.keys?.auth
  if (!p256dh || !auth) throw new Error('Push subscription keys are unavailable')
  return {
    endpoint: subscription.endpoint,
    expiration_time: subscription.expirationTime,
    keys: { p256dh, auth },
  }
}

export function activatePushNotifications(accessToken: string, config: PushConfig) {
  if (detectPushCapability() !== 'supported') {
    return Promise.resolve({ status: 'unsupported' as const })
  }
  const publicVapidKey = config.public_vapid_key
  if (!config.enabled || !publicVapidKey) {
    return Promise.resolve({ status: 'disabled' as const })
  }
  if (Notification.permission === 'denied') {
    return Promise.resolve({ status: 'denied' as const })
  }

  // Keep the permission request in the direct click/tap call stack. In
  // particular, do not await configuration or any other network request first.
  const permission = Notification.permission === 'granted'
    ? Promise.resolve<NotificationPermission>('granted')
    : Notification.requestPermission()
  const reservation = withPushDisplayLock(() => beginPushActivation())

  return Promise.all([permission, reservation]).then(async ([result, { ticket, previous: old }]) => {
    if (result !== 'granted') return { status: 'denied' as const }

    // Subject is only a local account-switch discriminator, never authorization.
    const encoded = accessToken.split('.')[1]
    const subject: unknown = JSON.parse(atob(encoded.replace(/-/g, '+').replace(/_/g, '/'))).sub
    if (typeof subject !== 'string') throw new Error('Push account unavailable')
    const owner = await digestPushGeneration(subject, '', '')
    const registration = await navigator.serviceWorker.ready
    const { serialized, generation, previousEndpoint, previousGeneration } = await navigator.locks.request('fca-push-subscription', async () => {
    if ((await generationStore.read())?.revision !== ticket.revision) throw new Error('Push activation superseded')
    let existing = await registration.pushManager.getSubscription()
    const previous = existing ? serializeSubscription(existing) : null
    const previousGeneration = previous ? await digestPushGeneration(previous.endpoint, previous.keys.p256dh, previous.keys.auth) : null
    const reusable = old?.enabled && old.owner === owner && old.generation === previousGeneration
    if (existing && !reusable) {
      if (!await existing.unsubscribe()) throw new Error('יש להסיר את המינוי הקודם לפני הפעלה מחדש.')
      existing = null
    }
    const subscription = existing ?? await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicVapidKey),
    })
    const serialized = serializeSubscription(subscription)
    const generation = await digestPushGeneration(serialized.endpoint, serialized.keys.p256dh, serialized.keys.auth)
    if (!reusable && generation === ticket.generation) throw new Error('Push subscription was not renewed')
    return { serialized, generation, previousEndpoint: reusable ? null : previous?.endpoint, previousGeneration }
    })
    if (previousEndpoint && previousGeneration) {
      try { await removePushSubscription(accessToken, previousEndpoint, {}, previousGeneration) } catch { /* Best effort; server ownership remains authoritative. */ }
    }
    if ((await generationStore.read())?.revision !== ticket.revision) throw new Error('Push activation superseded')
    await registerPushSubscription(accessToken, serialized)
    if (!await enablePushGeneration(ticket.revision, generation, owner)) throw new Error('Push activation superseded')
    return { status: 'enabled' as const }
  })
}

export async function disableCurrentDevicePush(accessToken: string, retiredGeneration?: string | null) {
  const generation = retiredGeneration === undefined
    ? (await withPushDisplayLock(() => retirePushGeneration())).generation : retiredGeneration
  if (detectPushCapability() !== 'supported') {
    return { serverRemoved: true, browserUnsubscribed: true }
  }
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return { serverRemoved: true, browserUnsubscribed: true }
  const serialized = serializeSubscription(subscription)
  if (generation !== await digestPushGeneration(serialized.endpoint, serialized.keys.p256dh, serialized.keys.auth)) {
    return { serverRemoved: false, browserUnsubscribed: false }
  }

  let serverRemoved = false
  let browserUnsubscribed = false
  try {
    await removePushSubscription(accessToken, subscription.endpoint, {}, generation ?? undefined)
    serverRemoved = true
  } catch {
    // Logout and explicit disable callers can still invalidate the browser endpoint.
  }
  try {
    browserUnsubscribed = await navigator.locks.request('fca-push-subscription', async () => {
      const current = await registration.pushManager.getSubscription()
      if (!current) return true
      const value = serializeSubscription(current)
      if (generation !== await digestPushGeneration(value.endpoint, value.keys.p256dh, value.keys.auth)) return false
      return current.unsubscribe()
    })
  } catch {
    // The caller receives both outcomes and decides how to communicate the result.
  }
  return { serverRemoved, browserUnsubscribed }
}

export async function cleanupPushBeforeLogout(accessToken: string) {
  // Local retirement must commit before any best-effort network work begins.
  let retiredGeneration: string | null = null
  if (detectPushCapability() === 'supported') {
    retiredGeneration = await withPushDisplayLock(async () => {
      const state = await retirePushGeneration()
      try {
        const registration = await navigator.serviceWorker.getRegistration()
        const notifications = await registration?.getNotifications()
        notifications?.forEach((notification) => notification.close())
      } catch { /* Durable retirement still prevents future displays. */ }
      return state.generation
    })
  }
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      disableCurrentDevicePush(accessToken, retiredGeneration),
      new Promise<{ serverRemoved: false, browserUnsubscribed: false }>((resolve) => {
        timeoutId = setTimeout(() => resolve({
          serverRemoved: false,
          browserUnsubscribed: false,
        }), 3000)
      }),
    ])
  } catch {
    return { serverRemoved: false, browserUnsubscribed: false }
  } finally {
    if (timeoutId !== undefined) clearTimeout(timeoutId)
  }
}
