// Only FCA-owned local state; Supabase session clearing uses the existing logout.
export function clearDeletionLocalState(storages: Array<Storage | null>) {
  for (const storage of storages) {
    if (!storage) continue
    try {
      for (let index = storage.length - 1; index >= 0; index--) {
        const key = storage.key(index)
        if (key?.startsWith('family-car-agent:')) storage.removeItem(key)
      }
    } catch { /* storage restrictions must not undo server-side deletion */ }
  }
}
