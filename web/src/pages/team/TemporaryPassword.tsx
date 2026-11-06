import { useLayoutEffect, useRef, useState } from 'react'

import type { PersonWithTemporaryPassword } from '@/api/team'
import { Button } from '@/components/ui/button'

// A temporary password, shown this once because the API keeps no copy. It takes focus when it appears, so a screen reader
// reads it out and nobody misses it below the fold.
export function TemporaryPassword({
  issued,
  onDone,
}: {
  issued: PersonWithTemporaryPassword
  onDone: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState<'yes' | 'failed' | null>(null)
  const { person, temporary_password: password } = issued

  useLayoutEffect(() => {
    ref.current?.focus()
  }, [issued])

  async function copy() {
    try {
      await navigator.clipboard.writeText(password)
      setCopied('yes')
    } catch {
      setCopied('failed')
    }
  }

  return (
    <div
      ref={ref}
      tabIndex={-1}
      aria-labelledby="temporary-password-heading"
      role="region"
      className="mb-9 max-w-[36rem] border-l-[5px] border-warn-line bg-warn-soft px-4 py-4 focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid"
    >
      <h2 id="temporary-password-heading" className="mb-3 text-xl font-bold">
        Temporary password for {person.display_name}
      </h2>
      <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt>Username</dt>
        <dd className="font-bold break-all">{person.username}</dd>
        <dt>Password</dt>
        <dd className="font-mono text-lg leading-[1.3] font-bold tracking-[0.04em] break-all select-all wide:text-[1.375rem]">
          {password}
        </dd>
      </dl>
      <p className="mb-4">
        This is the only time it's shown, so give it to them now or write it down for them. They'll
        choose their own password the first time they sign in with it.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="lg" className="max-sm:w-full" onClick={() => void copy()}>
          Copy the password
        </Button>
        <Button size="lg" className="max-sm:w-full" onClick={onDone}>
          Done, hide it
        </Button>
      </div>
      {/* Always in the page, so screen readers announce the message when it fills in. */}
      <div role="status">
        {copied && (
          <p className="mt-3">
            {copied === 'yes'
              ? 'Copied.'
              : "This browser wouldn't copy it, so select it and copy it by hand."}
          </p>
        )}
      </div>
    </div>
  )
}
