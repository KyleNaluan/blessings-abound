import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'

import { loadApprovals, type ApprovalQueue, type QueueItem } from '@/api/approval'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { CHANNEL_NAMES, itemName, when } from '@/pages/approval/format'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; queue: ApprovalQueue }

function Queue({
  id,
  title,
  empty,
  items,
  since,
}: {
  id: string
  title: string
  empty: string
  items: QueueItem[]
  since: string
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="mb-9">
      <h2 id={`${id}-heading`} className="mb-3 text-xl font-bold">
        {title}
      </h2>
      {items.length === 0 ? (
        <p className="border-y border-rule py-3.5">{empty}</p>
      ) : (
        <ul className="border-t border-rule">
          {items.map((item) => (
            <li key={item.item_id} className="border-b border-rule py-3.5">
              <Link to={`/app/approvals/${item.item_id}`} className="font-bold break-words">
                {itemName(item)}
              </Link>
              <p className="text-muted-foreground">
                {item.full_sku ?? item.sku}, for{' '}
                {item.channels.map((channel) => CHANNEL_NAMES[channel]).join(' and ')}
                {item.status === 'held_for_season' && ', held for its season'}
              </p>
              {item.waiting_since && (
                <p className="text-sm text-muted-foreground">
                  {since} {when(item.waiting_since)}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// The items waiting for a manager: listings staff sent on, and approved items with no shelf yet.
export function ApprovalsPage() {
  usePageTitle('Approvals')
  const { me } = useAuth()
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchQueue = useCallback(() => {
    return loadApprovals()
      .then((queue) => setLoad({ state: 'ready', queue }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    if (!refused) void fetchQueue()
  }, [refused, fetchQueue])

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Approvals</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can approve listings and store items.</p>
      ) : (
        <>
          <Lead>
            Check each listing staff sent on, set its prices and package, then approve or reject it.
            An approved item gets its shelf or bin here too.
          </Lead>
          <div aria-live="polite">
            {load.state === 'loading' && <p className="mb-7 font-bold">Loading the items...</p>}
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
                  void fetchQueue()
                }}
              >
                Try again
              </Button>
            </div>
          )}
          {load.state === 'ready' && (
            <>
              <Queue
                id="approval"
                title="Waiting for approval"
                empty="Nothing is waiting for approval."
                items={load.queue.awaiting_approval}
                since="Sent on"
              />
              <Queue
                id="storage"
                title="Waiting for a shelf"
                empty="Every approved item is on a shelf."
                items={load.queue.awaiting_storage}
                since="Approved on"
              />
            </>
          )}
        </>
      )}
    </AuthLayout>
  )
}
