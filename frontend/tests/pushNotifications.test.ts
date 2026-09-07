import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  activatePushNotifications,
  cleanupPushBeforeLogout,
  currentNotificationPermission,
  detectPushCapability,
  disableCurrentDevicePush,
  inspectCurrentDevicePushState,
  preloadPushConfiguration,
  urlBase64ToUint8Array,
} from '../src/push/pushNotifications.ts'

type GlobalName = 'window' | 'navigator' | 'Notification' | 'fetch'

const enabledPushConfig = { enabled: true, public_vapid_key: 'AQID' }

function installGlobal(name: GlobalName, value: unknown) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, name)
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value })
  return () => {
    if (descriptor) Object.defineProperty(globalThis, name, descriptor)
    else delete (globalThis as Record<string, unknown>)[name]
  }
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function pushEnvironment(options: {
  permission?: NotificationPermission
  subscription?: Record<string, unknown> | null
  permissionResult?: NotificationPermission
  order?: string[]
} = {}) {
  const calls = { permission: 0, ready: 0, subscribe: 0, unsubscribe: 0, fetches: [] as string[] }
  const subscription = options.subscription === undefined ? {
    endpoint: 'https://push.example/device',
    expirationTime: null,
    toJSON: () => ({ keys: { p256dh: 'browser-public-key', auth: 'browser-auth' } }),
    unsubscribe: async () => {
      calls.unsubscribe += 1
      options.order?.push('unsubscribe')
      return true
    },
  } : options.subscription
  const pushManager = {
    getSubscription: async () => subscription,
    subscribe: async () => {
      calls.subscribe += 1
      return subscription
    },
  }
  const registration = { pushManager }
  const serviceWorker = {}
  Object.defineProperty(serviceWorker, 'ready', {
    get() {
      calls.ready += 1
      return Promise.resolve(registration)
    },
  })
  const restores = [
    installGlobal('window', { isSecureContext: true, PushManager: class {}, Notification: class {} }),
    installGlobal('navigator', { serviceWorker }),
    installGlobal('Notification', {
      permission: options.permission ?? 'default',
      requestPermission: async () => {
        calls.permission += 1
        return options.permissionResult ?? 'granted'
      },
    }),
    installGlobal('fetch', async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.fetches.push(url)
      if (url.endsWith('/api/push/subscriptions/remove')) options.order?.push('remove')
      if (url.endsWith('/api/push/config')) {
        return jsonResponse(200, { enabled: true, public_vapid_key: 'AQID' })
      }
      return jsonResponse(200, { registered: true })
    }),
  ]
  return { calls, restore: () => restores.reverse().forEach((restore) => restore()) }
}

test('unsupported browsers are detected without requesting permission', () => {
  const restoreWindow = installGlobal('window', undefined)
  try {
    assert.equal(detectPushCapability(), 'unsupported')
    assert.equal(currentNotificationPermission(), 'unsupported')
  } finally {
    restoreWindow()
  }
})

test('VAPID public keys are converted from URL-safe base64', () => {
  assert.deepEqual([...urlBase64ToUint8Array('AQID-_8')], [1, 2, 3, 251, 255])
})

test('activation requests permission only when explicitly invoked and stops on denial', async () => {
  const environment = pushEnvironment({ permissionResult: 'denied' })
  try {
    assert.equal(environment.calls.permission, 0)
    const activation = activatePushNotifications('access-token', enabledPushConfig)
    assert.equal(environment.calls.permission, 1)
    assert.deepEqual(await activation, { status: 'denied' })
    assert.equal(environment.calls.ready, 0)
  } finally {
    environment.restore()
  }
})

test('configuration preload performs no permission or subscription action', async () => {
  const environment = pushEnvironment()
  try {
    assert.deepEqual(await preloadPushConfiguration('access-token'), enabledPushConfig)
    assert.equal(environment.calls.permission, 0)
    assert.equal(environment.calls.ready, 0)
    assert.equal(environment.calls.subscribe, 0)
  } finally {
    environment.restore()
  }
})

test('already denied permission is not requested again', async () => {
  const environment = pushEnvironment({ permission: 'denied' })
  try {
    assert.deepEqual(
      await activatePushNotifications('access-token', enabledPushConfig),
      { status: 'denied' },
    )
    assert.equal(environment.calls.permission, 0)
    assert.equal(environment.calls.ready, 0)
  } finally {
    environment.restore()
  }
})

test('activation waits for service worker, reuses subscription and registers with bearer auth', async () => {
  const environment = pushEnvironment({ permission: 'granted' })
  const fetchCalls: Array<{ url: string, init?: RequestInit }> = []
  const restoreFetch = installGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    fetchCalls.push({ url, init })
    if (url.endsWith('/api/push/config')) {
      return jsonResponse(200, { enabled: true, public_vapid_key: 'AQID' })
    }
    return jsonResponse(200, { registered: true })
  })
  try {
    assert.deepEqual(
      await activatePushNotifications('access-token', enabledPushConfig),
      { status: 'enabled' },
    )
    assert.equal(environment.calls.permission, 0)
    assert.equal(environment.calls.ready, 1)
    assert.equal(environment.calls.subscribe, 0)
    const registration = fetchCalls.find(({ url }) => url.endsWith('/api/push/subscriptions'))
    if (!registration?.init) throw new Error('registration request was not sent')
    assert.equal((registration.init.headers as Record<string, string>).Authorization, 'Bearer access-token')
    assert.deepEqual(JSON.parse(String(registration.init.body)), {
      endpoint: 'https://push.example/device',
      expiration_time: null,
      keys: { p256dh: 'browser-public-key', auth: 'browser-auth' },
    })
  } finally {
    restoreFetch()
    environment.restore()
  }
})

test('permission request begins before any awaited registration work', async () => {
  const order: string[] = []
  const environment = pushEnvironment({
    permissionResult: 'granted',
    order,
  })
  const restoreNotification = installGlobal('Notification', {
    permission: 'default',
    requestPermission: () => {
      order.push('permission')
      return Promise.resolve('granted')
    },
  })
  try {
    const activation = activatePushNotifications('access-token', enabledPushConfig)
    assert.deepEqual(order, ['permission'])
    await activation
    assert.equal(order[0], 'permission')
  } finally {
    restoreNotification()
    environment.restore()
  }
})

test('unsupported activation is non-blocking and performs no permission request', async () => {
  const restoreWindow = installGlobal('window', undefined)
  try {
    assert.deepEqual(
      await activatePushNotifications('access-token', enabledPushConfig),
      { status: 'unsupported' },
    )
  } finally {
    restoreWindow()
  }
})

test('explicit disable removes server registration before browser unsubscribe', async () => {
  const order: string[] = []
  const environment = pushEnvironment({ permission: 'granted', order })
  try {
    assert.deepEqual(await disableCurrentDevicePush('access-token'), {
      serverRemoved: true,
      browserUnsubscribed: true,
    })
    assert.deepEqual(order, ['remove', 'unsubscribe'])
  } finally {
    environment.restore()
  }
})

test('current-device inspection distinguishes subscription, denial and no subscription', async () => {
  const subscribed = pushEnvironment({ permission: 'granted' })
  try {
    assert.equal(await inspectCurrentDevicePushState(), 'subscribed')
  } finally {
    subscribed.restore()
  }

  const unsubscribed = pushEnvironment({ permission: 'granted', subscription: null })
  try {
    assert.equal(await inspectCurrentDevicePushState(), 'unsubscribed')
  } finally {
    unsubscribed.restore()
  }

  const denied = pushEnvironment({ permission: 'denied' })
  try {
    assert.equal(await inspectCurrentDevicePushState(), 'denied')
    assert.equal(denied.calls.ready, 0)
  } finally {
    denied.restore()
  }
})

test('cleanup failure never blocks logout caller', async () => {
  const environment = pushEnvironment({ permission: 'granted' })
  const restoreFetch = installGlobal('fetch', async () => { throw new Error('offline') })
  try {
    const result = await cleanupPushBeforeLogout('access-token')
    assert.equal(result.serverRemoved, false)
    assert.equal(typeof result.browserUnsubscribed, 'boolean')
  } finally {
    restoreFetch()
    environment.restore()
  }
})

test('logout cleanup has a bounded timeout before the auth flow continues', async () => {
  const source = await readFile(new URL('../src/push/pushNotifications.ts', import.meta.url), 'utf8')
  assert.match(source, /Promise\.race\(\[/)
  assert.match(source, /setTimeout\([\s\S]*?3000\)/)
  assert.match(source, /finally \{[\s\S]*?clearTimeout/)
})

test('application startup contains no automatic push activation or notification UI', async () => {
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const dashboard = await readFile(new URL('../src/components/DashboardScreen.tsx', import.meta.url), 'utf8')
  const chat = await readFile(new URL('../src/components/MainAppScreen.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(app, /activatePushNotifications\(/)
  assert.doesNotMatch(dashboard, /Notification\.requestPermission|התראות/)
  assert.doesNotMatch(chat, /Notification\.requestPermission|התראות/)
})
