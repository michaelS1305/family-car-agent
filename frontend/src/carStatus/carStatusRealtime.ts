import type { RealtimeChannel, SupabaseClient } from '@supabase/supabase-js'

export const CAR_STATUS_REALTIME_EVENT = 'car_status_changed'
export const CAR_STATUS_SIGNAL_DEBOUNCE_MS = 200
export const CAR_STATUS_FALLBACK_POLL_MS = 30_000

export type CarStatusRealtimeState =
  | 'connecting'
  | 'subscribed'
  | 'disconnected'

type Scheduler = {
  setTimeout: (callback: () => void, delay: number) => unknown
  clearTimeout: (timer: unknown) => void
  setInterval: (callback: () => void, delay: number) => unknown
  clearInterval: (timer: unknown) => void
}

const browserScheduler: Scheduler = {
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: (timer) => globalThis.clearTimeout(timer as number),
  setInterval: (callback, delay) => globalThis.setInterval(callback, delay),
  clearInterval: (timer) => globalThis.clearInterval(timer as number),
}

export function carStatusRealtimeTopic(familyId: number) {
  return `family:${familyId}:car-status`
}

export function createCarStatusRealtimeSync({
  client,
  familyId,
  isVisible,
  refreshStatus,
  scheduler = browserScheduler,
}: {
  client: SupabaseClient
  familyId: number
  isVisible: () => boolean
  refreshStatus: () => void | Promise<void>
  scheduler?: Scheduler
}) {
  let channel: RealtimeChannel | null = null
  let state: CarStatusRealtimeState = 'disconnected'
  let stopped = false
  let generation = 0
  let debounceTimer: unknown
  let fallbackTimer: unknown
  let restartPromise: Promise<void> | null = null

  const clearDebounce = () => {
    if (debounceTimer === undefined) return
    scheduler.clearTimeout(debounceTimer)
    debounceTimer = undefined
  }

  const stopFallbackPolling = () => {
    if (fallbackTimer === undefined) return
    scheduler.clearInterval(fallbackTimer)
    fallbackTimer = undefined
  }

  const startFallbackPolling = () => {
    if (
      stopped
      || state === 'subscribed'
      || !isVisible()
      || fallbackTimer !== undefined
    ) return

    fallbackTimer = scheduler.setInterval(() => {
      if (!stopped && state !== 'subscribed' && isVisible()) {
        void refreshStatus()
      }
    }, CAR_STATUS_FALLBACK_POLL_MS)
  }

  const scheduleRefresh = () => {
    if (stopped) return
    clearDebounce()
    debounceTimer = scheduler.setTimeout(() => {
      debounceTimer = undefined
      if (!stopped) void refreshStatus()
    }, CAR_STATUS_SIGNAL_DEBOUNCE_MS)
  }

  const openChannel = () => {
    if (stopped || channel) return
    const currentGeneration = ++generation
    state = 'connecting'

    channel = client
      .channel(carStatusRealtimeTopic(familyId), {
        config: { private: true },
      })
      .on('broadcast', { event: CAR_STATUS_REALTIME_EVENT }, () => {
        if (currentGeneration === generation) scheduleRefresh()
      })
      .subscribe((nextState) => {
        if (stopped || currentGeneration !== generation) return
        if (nextState === 'SUBSCRIBED') {
          state = 'subscribed'
          stopFallbackPolling()
          return
        }
        if (
          nextState === 'CHANNEL_ERROR'
          || nextState === 'TIMED_OUT'
          || nextState === 'CLOSED'
        ) {
          state = 'disconnected'
          startFallbackPolling()
        }
      })
  }

  const ensureSubscribed = () => {
    if (stopped || state === 'subscribed' || state === 'connecting') return
    if (!channel) {
      openChannel()
      return
    }
    if (restartPromise) return

    const previousChannel = channel
    channel = null
    generation += 1
    restartPromise = Promise.resolve(client.removeChannel(previousChannel))
      .catch(() => undefined)
      .then(() => {
        restartPromise = null
        if (!stopped) openChannel()
      })
  }

  const start = () => {
    if (stopped || channel) return
    openChannel()
  }

  const handleForeground = () => {
    if (stopped || !isVisible()) return
    void refreshStatus()
    ensureSubscribed()
    startFallbackPolling()
  }

  const handleBackground = () => {
    stopFallbackPolling()
    if (state !== 'disconnected') state = 'disconnected'
  }

  const stop = () => {
    if (stopped) return
    stopped = true
    generation += 1
    clearDebounce()
    stopFallbackPolling()
    const previousChannel = channel
    channel = null
    if (previousChannel) void client.removeChannel(previousChannel)
  }

  return {
    start,
    stop,
    handleForeground,
    handleBackground,
    getState: () => state,
  }
}
