import assert from 'node:assert/strict'
import test from 'node:test'

import { createJoinRequestRunner } from '../src/onboarding/joinFamilyRequests.ts'

test('Join requests are single-flight and expose loading state', async () => {
  const loadingStates: boolean[] = []
  let releaseRequest: (() => void) | undefined
  let requestCount = 0
  const runner = createJoinRequestRunner((loading) => loadingStates.push(loading))

  const first = runner(async () => {
    requestCount += 1
    await new Promise<void>((resolve) => {
      releaseRequest = resolve
    })
  })
  const second = await runner(async () => {
    requestCount += 1
  })

  assert.equal(second.status, 'ignored')
  assert.equal(requestCount, 1)
  releaseRequest?.()
  assert.equal((await first).status, 'completed')
  assert.deepEqual(loadingStates, [true, false])
})
