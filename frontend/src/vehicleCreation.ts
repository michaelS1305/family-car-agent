/** One immutable logical creation; failures retain the same payload and UUID. */
export function vehicleCreationSubmission(storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>, owner = '') {
  const key = `family-car-agent:vehicle-create:${owner}`
  let pending: { display_name: string; request_id: string } | null = null
  try {
    const saved = JSON.parse(storage?.getItem(key) ?? 'null')
    if (typeof saved?.display_name === 'string' && typeof saved?.request_id === 'string'
      && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(saved.request_id)) pending = saved
  } catch { /* Restricted storage falls back to in-memory retry identity. */ }
  const save = () => { try { if (pending) storage?.setItem(key, JSON.stringify(pending)); else storage?.removeItem(key) } catch { /* Best effort recovery only. */ } }
  let busy = false
  return {
    async submit<T>(name: string, send: (request: { display_name: string; request_id: string }) => Promise<T>, uuid = () => crypto.randomUUID()) {
      if (busy) return undefined
      if (!pending) { pending = { display_name: name, request_id: uuid() }; save() }
      busy = true
      try { const result = await send(pending); pending = null; save(); return result }
      finally { busy = false }
    },
    pending: () => pending,
    reset: () => { if (!busy) { pending = null; save() } },
  }
}
