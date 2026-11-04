// The shared CI runner can freeze every test process at once for 15 seconds or more. A time limit kept by a plain timer
// counts that freeze, so it fails whichever tests happen to be running. This clock counts only the time the process ran.
// It ticks every TICK_MS, and a gap longer than STALL_MS between two ticks is a freeze, so it counts as one tick.

const TICK_MS = 50
const STALL_MS = 250

// Kept from when this file loads, before a test can fake them.
const { setInterval, clearInterval } = globalThis
const now = performance.now.bind(performance)

// Runs `fn` and fails it once it has run for `limitMs` without settling, not counting time the process was frozen.
export function withRunningTimeLimit(fn: () => unknown, limitMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    let ran = 0
    let frozen = 0
    let last = now()
    const tick = setInterval(() => {
      const at = now()
      const gap = at - last
      last = at
      if (gap > STALL_MS) {
        ran += TICK_MS
        frozen += gap - TICK_MS
      } else {
        ran += gap
      }
      if (ran >= limitMs) {
        fail(
          new Error(
            `Test timed out after running for ${limitMs}ms, not counting ${Math.round(frozen)}ms while the process was frozen.`,
          ),
        )
      }
    }, TICK_MS)
    const pass = () => {
      clearInterval(tick)
      resolve()
    }
    function fail(error: unknown) {
      clearInterval(tick)
      reject(error)
    }
    try {
      Promise.resolve(fn()).then(pass, fail)
    } catch (error) {
      fail(error)
    }
  })
}
