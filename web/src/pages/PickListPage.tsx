import { useCallback, useEffect, useState } from 'react'

import { loadPickList, markPicked, type PickListEntry } from '@/api/approval'
import { AppLayout } from '@/components/site/AppLayout'
import { Lead, PageHeading } from '@/components/site/AuthLayout'
import {
  ActionCell,
  Cell,
  DataTable,
  EmptyTable,
  Row,
  SubText,
  TableBody,
  TableSection,
  type Column,
} from '@/components/site/DataTable'
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

const COLUMNS: Column[] = [
  { label: 'Shelf or bin', width: 'w-[9rem]' },
  { label: 'Item' },
  { label: 'Weight', width: 'w-[7rem]' },
  { label: 'Done', width: 'w-[8.5rem]', hidden: true },
]

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
    <Row>
      <Cell label="Shelf or bin" className="text-lg font-bold break-words">
        {entry.location_code ?? 'No shelf recorded'}
      </Cell>
      <Cell>
        <span className="block font-bold break-words">{entry.title}</span>
        <SubText>{entry.full_sku ?? entry.sku}</SubText>
        {error && (
          <span role="alert" className="mt-2 block font-bold text-destructive">
            {error}
          </span>
        )}
      </Cell>
      <Cell label="Weight" className="text-muted-foreground">
        {entry.package_weight_oz === null ? (
          <span className="wide:hidden">No weight recorded</span>
        ) : (
          `${entry.package_weight_oz} oz`
        )}
      </Cell>
      <ActionCell>
        <Button
          variant="outline"
          size="lg"
          disabled={pending}
          aria-busy={pending}
          aria-label={`Picked ${entry.full_sku ?? entry.sku}`}
          onClick={() => void pick()}
        >
          {pending ? 'Saving...' : 'Picked'}
        </Button>
      </ActionCell>
    </Row>
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
    <AppLayout>
      <PageHeading>Pick list</PageHeading>
      <Lead>
        Sold items to pull, grouped by box size in the order Settings lists them, then by shelf or
        bin.
      </Lead>
      <div aria-live="polite">
        {load.state === 'loading' && <p className="mb-7 font-bold">Loading the pick list...</p>}
        {load.state === 'ready' && load.entries.length === 0 && (
          <EmptyTable>Nothing sold is waiting to be picked.</EmptyTable>
        )}
      </div>
      {load.state === 'failed' && (
        <div role="alert" className="mb-7 rounded-xl border-4 border-destructive bg-card px-5 py-4">
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
        sections(load.entries).map((section) => (
          <TableSection
            key={section.box ?? 'none'}
            id={`pick-${section.box ?? 'none'}`}
            title={section.box ? boxLabel(section.box) : 'No box recorded'}
            count={section.entries.length}
          >
            <DataTable columns={COLUMNS}>
              <TableBody>
                {section.entries.map((entry) => (
                  <Entry key={entry.item_id} entry={entry} onPicked={picked} />
                ))}
              </TableBody>
            </DataTable>
          </TableSection>
        ))}
    </AppLayout>
  )
}
