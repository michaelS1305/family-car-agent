// Durable installation state shared with the service worker. No bearer/keys stored.
export type PushGenerationState = { revision: string; enabled: boolean; generation: string | null; owner: string | null }
export type GenerationStore = {
  read: () => Promise<PushGenerationState | null>
  change: (update: (state: PushGenerationState | null) => PushGenerationState) => Promise<PushGenerationState>
}

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('fca-push-privacy', 1)
    request.onupgradeneeded = () => { request.result.createObjectStore('state') }
    request.onerror = () => reject(new Error('Push privacy storage unavailable'))
    request.onsuccess = () => resolve(request.result)
  })
}

export const generationStore: GenerationStore = {
  async read() {
    const db = await database()
    return new Promise((resolve, reject) => {
      const tx = db.transaction('state', 'readonly')
      const request = tx.objectStore('state').get('installation')
      tx.oncomplete = () => { db.close(); resolve(request.result ?? null) }
      tx.onabort = tx.onerror = () => { db.close(); reject(new Error('Push privacy read failed')) }
    })
  },
  async change(update) {
    const db = await database()
    return new Promise((resolve, reject) => {
      const tx = db.transaction('state', 'readwrite')
      const store = tx.objectStore('state')
      const request = store.get('installation')
      let result: PushGenerationState
      request.onsuccess = () => {
        try {
          result = update(request.result ?? null)
          store.put(result, 'installation')
        } catch { tx.abort() }
      }
      tx.oncomplete = () => { db.close(); resolve(result) }
      tx.onabort = tx.onerror = () => { db.close(); reject(new Error('Push privacy write failed')) }
    })
  },
}

export async function digestPushGeneration(endpoint: string, p256dh: string, auth: string) {
  const bytes = new TextEncoder().encode(`${endpoint}\n${p256dh}\n${auth}`)
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map((value) => value.toString(16).padStart(2, '0')).join('')
}

export function mayDisplayPush(state: PushGenerationState | null, generation: unknown) {
  return !!state?.enabled && typeof generation === 'string' && /^[a-f0-9]{64}$/.test(generation) && state.generation === generation
}

export async function retirePushGeneration(store = generationStore) {
  return store.change((old) => ({ revision: crypto.randomUUID(), enabled: false, generation: old?.generation ?? null, owner: null }))
}

export async function beginPushActivation(store = generationStore): Promise<{ ticket: PushGenerationState; previous: PushGenerationState | null }> {
  let previous: PushGenerationState | null = null
  const ticket = await store.change((old) => {
    previous = old
    return { revision: crypto.randomUUID(), enabled: false, generation: old?.generation ?? null, owner: old?.owner ?? null }
  })
  return { ticket, previous }
}

export async function enablePushGeneration(revision: string, generation: string, owner: string, store = generationStore) {
  const state = await store.change((old) => old?.revision === revision
    ? { revision, enabled: true, generation, owner }
    : old ?? { revision: crypto.randomUUID(), enabled: false, generation: null, owner: null })
  return state.revision === revision && state.enabled
}

export function withPushDisplayLock<T>(operation: () => Promise<T>): Promise<T> {
  if (!navigator.locks) return Promise.reject(new Error('Push privacy lock unavailable'))
  return navigator.locks.request('fca-push-display', operation)
}
