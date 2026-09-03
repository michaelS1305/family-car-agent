import assert from 'node:assert/strict'
import test from 'node:test'

import type { SupabaseClient } from '@supabase/supabase-js'
import {
  CAR_STATUS_FALLBACK_POLL_MS,
  CAR_STATUS_REALTIME_EVENT,
  CAR_STATUS_SIGNAL_DEBOUNCE_MS,
  carStatusRealtimeTopic,
  createCarStatusRealtimeSync,
} from '../src/carStatus/carStatusRealtime.ts'

class FakeScheduler {
  nextId = 1
  timeouts = new Map<number, { callback: () => void; delay: number }>()
  intervals = new Map<number, { callback: () => void; delay: number }>()

  setTimeout = (callback: () => void, delay: number) => {
    const id = this.nextId++
    this.timeouts.set(id, { callback, delay })
    return id
  }

  clearTimeout = (id: unknown) => {
    this.timeouts.delete(id as number)
  }

  setInterval = (callback: () => void, delay: number) => {
    const id = this.nextId++
    this.intervals.set(id, { callback, delay })
    return id
  }

  clearInterval = (id: unknown) => {
    this.intervals.delete(id as number)
  }

  runTimeouts() {
    const pending = [...this.timeouts.values()]
    this.timeouts.clear()
    pending.forEach(({ callback }) => callback())
  }

  runIntervals() {
    ;[...this.intervals.values()].forEach(({ callback }) => callback())
  }
}

class FakeChannel {
  event = ''
  broadcastCallback: (() => void) | undefined
  statusCallback: ((status: 'SUBSCRIBED' | 'CHANNEL_ERROR' | 'TIMED_OUT' | 'CLOSED') => void) | undefined

  on(_type: string, filter: { event: string }, callback: () => void) {
    this.event = filter.event
    this.broadcastCallback = callback
    return this
  }

  subscribe(callback: typeof this.statusCallback) {
    this.statusCallback = callback
    return this
  }

  signal() {
    this.broadcastCallback?.()
  }

  status(value: 'SUBSCRIBED' | 'CHANNEL_ERROR' | 'TIMED_OUT' | 'CLOSED') {
    this.statusCallback?.(value)
  }
}

class FakeClient {
  channelCalls: Array<{ topic: string; options: unknown; channel: FakeChannel }> = []
  removed: FakeChannel[] = []

  channel(topic: string, options: unknown) {
    const channel = new FakeChannel()
    this.channelCalls.push({ topic, options, channel })
    return channel
  }

  async removeChannel(channel: FakeChannel) {
    this.removed.push(channel)
    return 'ok'
  }
}

function setup({ visible = true, familyId = 17 } = {}) {
  const scheduler = new FakeScheduler()
  const client = new FakeClient()
  let isVisible = visible
  let refreshes = 0
  const sync = createCarStatusRealtimeSync({
    client: client as unknown as SupabaseClient,
    familyId,
    isVisible: () => isVisible,
    refreshStatus: () => { refreshes += 1 },
    scheduler,
  })
  return {
    scheduler,
    client,
    sync,
    refreshCount: () => refreshes,
    setVisible: (next: boolean) => { isVisible = next },
  }
}

test('subscribes once to the authenticated family private topic', () => {
  const first = setup({ familyId: 11 })
  const second = setup({ familyId: 22 })

  first.sync.start()
  first.sync.start()
  second.sync.start()

  assert.equal(carStatusRealtimeTopic(11), 'family:11:car-status')
  assert.equal(first.client.channelCalls.length, 1)
  assert.equal(first.client.channelCalls[0]?.topic, 'family:11:car-status')
  assert.deepEqual(first.client.channelCalls[0]?.options, { config: { private: true } })
  assert.equal(first.client.channelCalls[0]?.channel.event, CAR_STATUS_REALTIME_EVENT)
  assert.equal(second.client.channelCalls[0]?.topic, 'family:22:car-status')
})

test('debounces a burst of status signals into one backend refresh', () => {
  const fixture = setup()
  fixture.sync.start()
  const channel = fixture.client.channelCalls[0]!.channel

  channel.signal()
  channel.signal()

  assert.equal(fixture.refreshCount(), 0)
  assert.equal(fixture.scheduler.timeouts.size, 1)
  assert.equal([...fixture.scheduler.timeouts.values()][0]?.delay, CAR_STATUS_SIGNAL_DEBOUNCE_MS)
  fixture.scheduler.runTimeouts()
  assert.equal(fixture.refreshCount(), 1)
})

test('fallback polling runs only while visible and realtime is disconnected', () => {
  const fixture = setup()
  fixture.sync.start()
  const channel = fixture.client.channelCalls[0]!.channel

  channel.status('CHANNEL_ERROR')
  assert.equal(fixture.scheduler.intervals.size, 1)
  assert.equal([...fixture.scheduler.intervals.values()][0]?.delay, CAR_STATUS_FALLBACK_POLL_MS)
  fixture.scheduler.runIntervals()
  assert.equal(fixture.refreshCount(), 1)

  fixture.sync.handleBackground()
  fixture.setVisible(false)
  assert.equal(fixture.scheduler.intervals.size, 0)
  fixture.scheduler.runIntervals()
  assert.equal(fixture.refreshCount(), 1)

  fixture.setVisible(true)
  channel.status('CHANNEL_ERROR')
  assert.equal(fixture.scheduler.intervals.size, 1)
  channel.status('SUBSCRIBED')
  assert.equal(fixture.scheduler.intervals.size, 0)
})

test('foreground refreshes immediately and recreates a failed subscription', async () => {
  const fixture = setup({ visible: false })
  fixture.sync.start()
  const oldChannel = fixture.client.channelCalls[0]!.channel
  oldChannel.status('TIMED_OUT')

  fixture.sync.handleForeground()
  assert.equal(fixture.refreshCount(), 0)

  fixture.setVisible(true)
  fixture.sync.handleForeground()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(fixture.refreshCount(), 1)
  assert.deepEqual(fixture.client.removed, [oldChannel])
  assert.equal(fixture.client.channelCalls.length, 2)
})

test('returning from the background recreates even a previously subscribed channel', async () => {
  const fixture = setup()
  fixture.sync.start()
  const oldChannel = fixture.client.channelCalls[0]!.channel
  oldChannel.status('SUBSCRIBED')

  fixture.setVisible(false)
  fixture.sync.handleBackground()
  fixture.setVisible(true)
  fixture.sync.handleForeground()
  await Promise.resolve()
  await Promise.resolve()

  assert.equal(fixture.refreshCount(), 1)
  assert.deepEqual(fixture.client.removed, [oldChannel])
  assert.equal(fixture.client.channelCalls.length, 2)
})

test('stop removes the channel and clears debounce and polling timers', () => {
  const fixture = setup()
  fixture.sync.start()
  const channel = fixture.client.channelCalls[0]!.channel
  channel.signal()
  channel.status('CLOSED')

  assert.equal(fixture.scheduler.timeouts.size, 1)
  assert.equal(fixture.scheduler.intervals.size, 1)
  fixture.sync.stop()

  assert.equal(fixture.scheduler.timeouts.size, 0)
  assert.equal(fixture.scheduler.intervals.size, 0)
  assert.deepEqual(fixture.client.removed, [channel])
  fixture.scheduler.runTimeouts()
  fixture.scheduler.runIntervals()
  assert.equal(fixture.refreshCount(), 0)
})
