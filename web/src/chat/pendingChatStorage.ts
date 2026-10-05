export function createPendingChatStorage(authUserId: string, storage: Pick<Storage, 'setItem' | 'removeItem'>) {
  const key = `family-car-agent:chat-pending:v1:${authUserId}`
  let retired = false
  return {
    save(request: { requestId: string; message: string } | null) {
      if (retired) return
      if (request) storage.setItem(key, JSON.stringify(request))
      else storage.removeItem(key)
    },
    retire() {
      retired = true
      try { storage.removeItem(key) } catch { /* Browser storage restrictions must not block logout. */ }
    },
    get retired() { return retired },
  }
}
