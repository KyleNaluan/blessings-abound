import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'

import { loadPickList, markPicked, type PickListEntry } from '@/api/approval'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { boxLabel } from '@/pages/approval/format'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; entries: PickListEntry[] }

type Section = { box: string | null; entries: PickListEntry[] }

// The API sends the list in walking order, so a new section starts wherever the box changes.
function sections(entries: PickListEntry[]) {
  const result: Section[] = []
  for (const entry of entries) {
    const last = result.at(-1)
    if (last && last.box === entry.box_code) last.entries.push(entry)
    else result.push({ box: entry.box_code, entries: [entry] })
  }
  return result
}

function Entry({ entry, onPicked }: { entry: PickListEntry; onPicked: (id: string) => void }) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function pick() {
    setPending(true)
    setError(null)
    try {
      await markPicked(entry.item_id)
      onPicked(entry.item_id)
    } catch (failure) {
      setError((failure as Error).message)
      setPending(false)
    }
  }

  return (
    <li className="border-b border-rule py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <p className="text-xl font-bold">{entry.location_code ?? 'No shelf recorded'}</p>
          <p className="font-bold wrap-anywhere">{entry.full_sku ?? entry.sku}</p>
          <p className="break-words">{entry.title}</p>
          {entry.package_weight_oz !== null && (
            <p className="text-muted-foreground">{entry.package_weight_oz} oz packed</p>
          )}
        </div>
        <Button
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          disabled={pending}
          aria-busy={pending}
          aria-label={`Picked ${entry.full_sku ?? entry.sku}`}
          onClick={() => void pick()}
        >
          {pending ? 'Saving...' : 'Picked'}
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-3 font-bold text-destructive">
          {error}
        </p>
      )}
    </li>
  )
}

// The sold items to pull from the shelves, grouped by box size and in shelf order within each.
export function PickListPage() {
  usePageTitle('Pick list')
  const [load, setLoad] = useState<Load>({ state: 'loading' })

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchList = useCallback(() => {
    return loadPickList()
      .then((entries) => setLoad({ state: 'ready', entries }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    void fetchList()
  }, [fetchList])

  function picked(itemId: string) {
    setLoad((current) =>
      current.state === 'ready'
        ? { ...current, entries: current.entries.filter((entry) => entry.item_id !== itemId) }
        : current,
    )
  }

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Pick list</PageHeading>
      <Lead>
        Sold items to pull, grouped by box size in the order Settings lists them, then by shelf or
        bin.
      </Lead>
      <div aria-live="polite">
        {load.state === 'loading' && <p className="mb-7 font-bold">Loading the pick list...</p>}
        {load.state === 'ready' && load.entries.length === 0 && (
          <p className="mb-7 border-y border-rule py-3.5">Nothing sold is waiting to be picked.</p>
        )}
      </div>
      {load.state === 'failed' && (
        <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
          <p className="mb-3 font-bold">{load.message}</p>
          <Button
            variant="outline"
            size="lg"
            className="max-sm:w-full"
            onClick={() => {
              setLoad({ state: 'loading' })
              void fetchList()
            }}
          >
            Try again
          </Button>
        </div>
      )}
      {load.state === 'ready' &&
        sections(load.entries).map((section) => {
          const id = `pick-${section.box ?? 'none'}`
          return (
            <section key={id} aria-labelledby={`${id}-heading`} className="mb-9">
              <h2 id={`${id}-heading`} className="mb-1 text-xl font-bold">
                {section.box ? boxLabel(section.box) : 'No box recorded'}
              </h2>
              <ul className="border-t border-rule">
                {section.entries.map((entry) => (
                  <Entry key={entry.item_id} entry={entry} onPicked={picked} />
                ))}
              </ul>
            </section>
          )
        })}
    </AuthLayout>
  )
}
