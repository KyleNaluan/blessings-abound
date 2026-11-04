import { TestRunner, type RunnerTestCase } from 'vitest'

import { withRunningTimeLimit } from './runningTime'

// Only a test that hangs ever reaches this, because each findBy or waitFor already fails after 1 second.
// The first test in a file also does the slow cold start, which is why it is well above that.
const TEST_LIMIT_MS = 15000

// Runs each test with a time limit that leaves out the seconds the shared CI runner keeps this process frozen.
// Vitest's own limit is a plain timer, so vite.config.ts turns it off.
export default class FreezeTolerantRunner extends TestRunner {
  async runTask(test: RunnerTestCase) {
    const fn = TestRunner.getTestFn(test)
    if (!fn) throw new Error(`Test function is not found for "${test.name}".`)
    await withRunningTimeLimit(fn, TEST_LIMIT_MS)
  }
}
