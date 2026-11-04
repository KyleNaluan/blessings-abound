import { useLayoutEffect, useRef, type FormEvent, type ReactNode } from 'react'

import { SubmitButton } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import type { SaveStatus } from './useSave'

// The shared parts of one Settings section: its heading, who changed it last, the save button, and what went wrong.

type Read = { updated_at: string | null; updated_by_name: string | null }

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function lastChanged(read: Read) {
  if (!read.updated_at || !read.updated_by_name) return 'No one has changed these since setup.'
  return `Last changed by ${read.updated_by_name}, ${when(read.updated_at)}.`
}

// Takes focus when it appears, and again on each failed attempt, so a screen reader hears why the save failed.
function Problems({
  status,
  onReload,
}: {
  status: Extract<SaveStatus, { kind: 'failed' }>
  onReload: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    ref.current?.focus()
  }, [status.attempt])

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="mb-5 border-4 border-destructive px-5 py-4 focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid"
    >
      <p className="mb-1 font-bold">This section wasn't saved.</p>
      <ul className="list-disc pl-5">
        {status.problems.map((problem) => (
          <li key={problem}>{problem}</li>
        ))}
      </ul>
      {status.stale && (
        <Button variant="outline" size="lg" className="mt-3 max-sm:w-full" onClick={onReload}>
          Reload the settings
        </Button>
      )}
    </div>
  )
}

export function SectionFrame({
  id,
  title,
  description,
  read,
  status,
  saved,
  saveLabel,
  onSubmit,
  onReload,
  children,
}: {
  id: string
  title: string
  description: ReactNode
  read: Read
  status: SaveStatus
  saved: boolean
  saveLabel: string
  onSubmit: () => void
  onReload: () => void
  children: ReactNode
}) {
  function submit(event: FormEvent) {
    event.preventDefault()
    if (status.kind !== 'saving') onSubmit()
  }

  return (
    <section aria-labelledby={`${id}-heading`} className="mb-7 border border-rule p-4">
      <h2 id={`${id}-heading`} className="mb-1 text-xl font-bold">
        {title}
      </h2>
      <p className="mb-5">{description}</p>
      {status.kind === 'failed' && <Problems status={status} onReload={onReload} />}
      <form onSubmit={submit} noValidate>
        {children}
        <SubmitButton pending={status.kind === 'saving'}>{saveLabel}</SubmitButton>
      </form>
      <div aria-live="polite">
        {saved && status.kind === 'idle' && <p className="mt-3 font-bold">Saved.</p>}
      </div>
      <p className="mt-3 text-sm text-muted-foreground">{lastChanged(read)}</p>
    </section>
  )
}
