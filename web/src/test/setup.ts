import '@testing-library/jest-dom/vitest'

import { configure } from '@testing-library/react'

// A `findBy*` query that waits out the default 1s can expire on a slow, shared CI runner before a
// starved worker flushes the pending render, so give the async queries more room.
configure({ asyncUtilTimeout: 5000 })
