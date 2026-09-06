import {
  getPushConfig,
  registerPushSubscription,
  removePushSubscription,
  type BrowserPushSubscription,
} from '../api/apiClient.ts'

export type PushCapability = 'supported' | 'unsupported'

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

export async function activatePushNotifications(accessToken: string) {
  if (detectPushCapability() !== 'supported') return { status: 'unsupported' as const }
  const config = await getPushConfig(accessToken)
  if (!config.enabled || !config.public_vapid_key) return { status: 'disabled' as const }

  const permission = Notification.permission === 'granted'
    ? 'granted'
    : await Notification.requestPermission()
  if (permission !== 'granted') return { status: 'denied' as const }

  const registration = await navigator.serviceWorker.ready
  const existing = await registration.pushManager.getSubscription()
  const subscription = existing ?? await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(config.public_vapid_key),
  })
  await registerPushSubscription(accessToken, serializeSubscription(subscription))
  return { status: 'enabled' as const }
}

export async function disableCurrentDevicePush(accessToken: string) {
  if (detectPushCapability() !== 'supported') {
    return { serverRemoved: true, browserUnsubscribed: true }
  }
  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return { serverRemoved: true, browserUnsubscribed: true }

  let serverRemoved = false
  let browserUnsubscribed = false
  try {
    await removePushSubscription(accessToken, subscription.endpoint)
    serverRemoved = true
  } catch {
    // Logout and explicit disable callers can still invalidate the browser endpoint.
  }
  try {
    browserUnsubscribed = await subscription.unsubscribe()
  } catch {
    // The caller receives both outcomes and decides how to communicate the result.
  }
  return { serverRemoved, browserUnsubscribed }
}

export async function cleanupPushBeforeLogout(accessToken: string) {
  let timeoutId: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      disableCurrentDevicePush(accessToken),
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
