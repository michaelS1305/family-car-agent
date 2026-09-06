/// <reference lib="webworker" />

import { clientsClaim } from 'workbox-core'
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
} from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { parsePushNotificationPayload } from './push/pushPayload'

declare let self: ServiceWorkerGlobalScope & typeof globalThis

self.skipWaiting()
clientsClaim()
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()
registerRoute(new NavigationRoute(createHandlerBoundToURL('index.html')))

self.addEventListener('push', (event) => {
  let rawPayload: unknown
  try {
    rawPayload = event.data?.json()
  } catch {
    return
  }
  const payload = parsePushNotificationPayload(rawPayload)
  if (!payload) return

  event.waitUntil(self.registration.showNotification(payload.title, {
    body: payload.body,
    icon: '/icons/family-car-agent-192.png',
    tag: payload.tag,
    data: { url: '/' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil((async () => {
    const windowClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    })
    const existingClient = windowClients.find((client) => {
      try {
        return new URL(client.url).origin === self.location.origin
      } catch {
        return false
      }
    })
    if (existingClient) {
      await existingClient.focus()
      return
    }
    await self.clients.openWindow('/')
  })())
})
