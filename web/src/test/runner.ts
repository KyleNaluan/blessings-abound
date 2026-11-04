import { TestRunner, type RunnerTestCase, type RunnerTestSuite } from 'vitest'

import { withHookRunningTimeLimit, withRunningTimeLimit } from './runningTime'

// Only a test that hangs ever reaches this, because each findBy or waitFor already fails after 1 second.
// The first test in a file also does the slow cold start, which is why it is well above that.
const TEST_LIMIT_MS = 15000
// Vitest's default for a hook.
const HOOK_LIMIT_MS = 10000

const limited = new WeakSet<RunnerTestSuite>()

// Runs each test and hook with a time limit that leaves out the seconds the shared CI runner keeps this process frozen.
// Vitest's own limits are plain timers, so vite.config.ts turns them off.
export default class FreezeTolerantRunner extends TestRunner {
  async onBeforeRunSuite(suite: RunnerTestSuite) {
    await super.onBeforeRunSuite(suite)
    if (limited.has(suite)) return
    limited.add(suite)
    // aroundEach and aroundAll wrap the tests themselves, so they are left out, and no test file uses them.
    const hooks = TestRunner.getSuiteHooks(suite)
    for (const name of ['beforeAll', 'afterAll', 'beforeEach', 'afterEach'] as const) {
      const list: Array<(...args: never[]) => unknown> = hooks[name]
      list.forEach((hook, index) => (list[index] = withHookRunningTimeLimit(hook, HOOK_LIMIT_MS)))
    }
  }

  async runTask(test: RunnerTestCase) {
    const fn = TestRunner.getTestFn(test)
    if (!fn) throw new Error(`Test function is not found for "${test.name}".`)
    await withRunningTimeLimit(fn, TEST_LIMIT_MS)
  }
}
