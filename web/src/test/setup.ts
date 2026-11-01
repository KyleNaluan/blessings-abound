import '@testing-library/jest-dom/vitest'

import { configure, getConfig } from '@testing-library/react'

const WATCH_EVERY_MS = 50
const STALL_MS = 250

// The shared CI runner can freeze this process for seconds. A findBy or waitFor deadline is a plain timer, so when the
// process wakes the expired timer runs before the render that is already due, and the wait fails without looking again.
// So a wait that failed while the process was frozen starts again, and only a wait that ran undisturbed can fail a test.
const { asyncWrapper } = getConfig()

configure({
  asyncWrapper: async (wait) => {
    for (;;) {
      let last = performance.now()
      let stalled = false
      const noteGap = () => {
        const now = performance.now()
        if (now - last > STALL_MS) stalled = true
        last = now
      }
      const watch = setInterval(noteGap, WATCH_EVERY_MS)
      try {
        return await asyncWrapper(wait)
      } catch (error) {
        // The interval may not have run yet since waking, because timers run in the order they expired.
        noteGap()
        if (!stalled) throw error
      } finally {
        clearInterval(watch)
      }
    }
  },
})
