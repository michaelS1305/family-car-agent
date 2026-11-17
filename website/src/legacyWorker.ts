// Never register a worker on a new visitor. Request an update only for the verified
// legacy script and root scope. Its replacement at /sw.js performs retirement.
export async function updateLegacyWorker(container: ServiceWorkerContainer, origin: string) {
 try {
  const scope = new URL('/', origin).href
  const script = new URL('/sw.js', origin).href
  for (const registration of await container.getRegistrations()) {
   const workers = [registration.active, registration.waiting, registration.installing].filter(Boolean)
   if (registration.scope === scope && workers.length && workers.every(worker => worker!.scriptURL === script)) {
    await registration.update()
   }
  }
 } catch { /* Unsupported/private/offline contexts must not block the website. */ }
}
