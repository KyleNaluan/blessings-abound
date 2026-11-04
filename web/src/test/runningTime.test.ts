import { withHookRunningTimeLimit, withRunningTimeLimit } from './runningTime'

// Blocks the event loop, as the runner freezing this process does.
function freeze(ms: number) {
  const until = performance.now() + ms
  while (performance.now() < until);
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

test('a freeze longer than the limit does not count against it', async () => {
  await expect(
    withRunningTimeLimit(async () => {
      await sleep(50)
      freeze(600)
      await sleep(50)
    }, 300),
  ).resolves.toBeUndefined()
})

test('something that never finishes fails once it has run for the limit', async () => {
  const started = performance.now()
  await expect(withRunningTimeLimit(() => new Promise(() => {}), 300)).rejects.toThrow(
    'Test timed out after running for 300ms',
  )
  expect(performance.now() - started).toBeGreaterThanOrEqual(300)
})

test('a failure is passed on as it is', async () => {
  const failure = new Error('the real failure')
  await expect(
    withRunningTimeLimit(() => {
      throw failure
    }, 300),
  ).rejects.toBe(failure)
  await expect(withRunningTimeLimit(() => Promise.reject(failure), 300)).rejects.toBe(failure)
})

test('a hook and the cleanup it returns get the same limit', async () => {
  const cleanup = vi.fn(() => new Promise(() => {}))
  const hook = withHookRunningTimeLimit(async () => {
    freeze(600)
    await sleep(50)
    return cleanup
  }, 300)
  const returned = await hook()
  expect(returned).toBeTypeOf('function')
  await expect((returned as () => Promise<unknown>)()).rejects.toThrow(
    'Hook timed out after running for 300ms',
  )
  expect(cleanup).toHaveBeenCalledOnce()
})
