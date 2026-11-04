import { useRef, useState } from 'react'

import { SettingsError, type SettingsPage } from '@/api/settings'

export type SaveStatus =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'failed'; problems: string[]; stale: boolean; attempt: number }

// Runs a save and keeps its status. A field the page could not read fails before the API is called.
export function useSave(onSaved: (page: SettingsPage) => void) {
  const [status, setStatus] = useState<SaveStatus>({ kind: 'idle' })
  const attempt = useRef(0)

  function fail(problems: string[], stale = false) {
    attempt.current += 1
    setStatus({ kind: 'failed', problems, stale, attempt: attempt.current })
  }

  async function save(call: () => Promise<SettingsPage>) {
    setStatus({ kind: 'saving' })
    try {
      const page = await call()
      setStatus({ kind: 'idle' })
      onSaved(page)
    } catch (error) {
      if (error instanceof SettingsError) fail(error.problems, error.stale)
      else fail(['Something went wrong. Try again.'])
    }
  }

  return { status, save, fail }
}
