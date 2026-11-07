import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'

import {
  listNow,
  loadApprovals,
  type ApprovalQueue,
  type KeptOffItem,
  type NotOnlineResult,
  type QueueItem,
} from '@/api/approval'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { CHANNEL_NAMES, itemName, releaseMonth, when } from '@/pages/approval/format'
import { NotOnlineForm, PutBackForm } from '@/pages/approval/NotOnlineForm'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; queue: ApprovalQueue }

function Summary({ item }: { item: QueueItem }) {
  return (
    <>
      {item.full_sku ?? item.sku}, for{' '}
      {item.channels.map((channel) => CHANNEL_NAMES[channel]).join(' and ')}
    </>
  )
}

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
                <Summary item={item} />
                {item.put_back
                  ? ', put back for review'
                  : item.status === 'held_for_season' &&
                    (item.back_for_review ? ', back in its season' : ', held for its season')}
              </p>
              {item.put_back && item.waiting_since ? (
                <p className="text-sm text-muted-foreground">
                  Put back on {when(item.waiting_since)}
                </p>
              ) : item.back_for_review && item.release_month ? (
                <p className="text-sm text-muted-foreground">
                  Approved before, and in season from {releaseMonth(item.release_month)}
                </p>
              ) : (
                item.waiting_since && (
                  <p className="text-sm text-muted-foreground">
                    {since} {when(item.waiting_since)}
                  </p>
                )
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// One held item, which a manager can bring into review early or take out of online selling.
function HeldItem({
  item,
  onGone,
}: {
  item: QueueItem
  onGone: (item: QueueItem, result: NotOnlineResult) => void
}) {
  const navigate = useNavigate()
  const [choosing, setChoosing] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function sendNow() {
    setSending(true)
    setError(null)
    try {
      await listNow(item.item_id)
      void navigate(`/app/approvals/${item.item_id}`)
    } catch (failure) {
      setError((failure as Error).message)
      setSending(false)
    }
  }

  return (
    <li className="border-b border-rule py-3.5">
      <Link to={`/app/approvals/${item.item_id}`} className="font-bold break-words">
        {itemName(item)}
      </Link>
      <p className="text-muted-foreground">
        <Summary item={item} />
      </p>
      <p className="mb-3 text-sm text-muted-foreground">
        {item.release_month && `Held until ${releaseMonth(item.release_month)}`}
        {item.location_code ? `, stored on ${item.location_code}` : ', with no shelf yet'}
      </p>
      {error && (
        <p role="alert" className="mb-3 font-bold text-destructive">
          {error}
        </p>
      )}
      {choosing ? (
        <div className="border-l-4 border-rule pl-3.5">
          <p className="mb-3">
            It comes off online selling, such as to sell it on the store floor, until a manager puts
            it back for review.
          </p>
          <NotOnlineForm
            itemId={item.item_id}
            idPrefix={`held-${item.item_id}`}
            onDone={(result) => onGone(item, result)}
            onCancel={() => setChoosing(false)}
          />
        </div>
      ) : (
        <div className="flex gap-3 max-sm:flex-col">
          <Button
            size="lg"
            className="max-sm:w-full"
            disabled={sending}
            aria-busy={sending}
            onClick={() => void sendNow()}
          >
            {sending ? 'Sending...' : 'List now'}
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="max-sm:w-full"
            disabled={sending}
            onClick={() => setChoosing(true)}
          >
            Don't list online
          </Button>
        </div>
      )}
    </li>
  )
}

// Approved items waiting for their release month, soonest first.
function HeldQueue({
  items,
  onGone,
}: {
  items: QueueItem[]
  onGone: (item: QueueItem, result: NotOnlineResult) => void
}) {
  return (
    <section aria-labelledby="held-heading" className="mb-9">
      <h2 id="held-heading" className="mb-1 text-xl font-bold">
        Held for season
      </h2>
      <p className="mb-3">
        Each item comes back to Waiting for approval in its release month, so you can check its
        price before it's listed. List now brings it back early.
      </p>
      {items.length === 0 ? (
        <p className="border-y border-rule py-3.5">No item is held for its season.</p>
      ) : (
        <ul className="border-t border-rule">
          {items.map((item) => (
            <HeldItem key={item.item_id} item={item} onGone={onGone} />
          ))}
        </ul>
      )}
    </section>
  )
}

// One item kept off online, which a manager can put back for review with a note on why.
function KeptOffRow({ item }: { item: KeptOffItem }) {
  const navigate = useNavigate()
  const [choosing, setChoosing] = useState(false)

  return (
    <li className="border-b border-rule py-3.5">
      <Link to={`/app/approvals/${item.item_id}`} className="font-bold break-words">
        {itemName(item)}
      </Link>
      <p className="text-muted-foreground">
        {item.sku}, kept off online by {item.decided_by_name} on {when(item.decided_at)}
      </p>
      {item.note && <p className="mb-3 break-words">{item.note}</p>}
      {choosing ? (
        <div className="border-l-4 border-rule pl-3.5">
          <p className="mb-3">
            It goes back to Waiting for approval, so you can check its listing and price before
            anything goes online.
          </p>
          <PutBackForm
            itemId={item.item_id}
            idPrefix={`kept-off-${item.item_id}`}
            onDone={() => void navigate(`/app/approvals/${item.item_id}`)}
            onCancel={() => setChoosing(false)}
          />
        </div>
      ) : (
        <Button
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          onClick={() => setChoosing(true)}
        >
          Put back for review
        </Button>
      )}
    </li>
  )
}

// Items taken out of online selling, newest first, which a manager can put back for review.
function KeptOffQueue({ items }: { items: KeptOffItem[] }) {
  return (
    <section aria-labelledby="kept-off-heading" className="mb-9">
      <h2 id="kept-off-heading" className="mb-1 text-xl font-bold">
        Not listed online
      </h2>
      <p className="mb-3">
        Put back for review sends an item to Waiting for approval, where it goes through the usual
        review and price check before it's listed. This shows the latest 50.
      </p>
      {items.length === 0 ? (
        <p className="border-y border-rule py-3.5">No item is kept off online.</p>
      ) : (
        <ul className="border-t border-rule">
          {items.map((item) => (
            <KeptOffRow key={item.item_id} item={item} />
          ))}
        </ul>
      )}
    </section>
  )
}

// The items waiting for a manager: listings staff sent on or back in season, approved items with
// no shelf yet, items held for their season, and items kept off online.
export function ApprovalsPage() {
  usePageTitle('Approvals')
  const { me } = useAuth()
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [keptOff, setKeptOff] = useState<string | null>(null)

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchQueue = useCallback(() => {
    return loadApprovals()
      .then((queue) => setLoad({ state: 'ready', queue }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    if (!refused) void fetchQueue()
  }, [refused, fetchQueue])

  // An item taken out of online selling moves to Not listed online, where it can be put back.
  function gone(item: QueueItem, result: NotOnlineResult) {
    setKeptOff(itemName(item))
    setLoad((current) => {
      if (current.state !== 'ready') return current
      const others = <T extends { item_id: string }>(items: T[]) =>
        items.filter((row) => row.item_id !== item.item_id)
      const { queue } = current
      return {
        state: 'ready',
        queue: {
          awaiting_approval: others(queue.awaiting_approval),
          awaiting_storage: others(queue.awaiting_storage),
          held_for_season: others(queue.held_for_season),
          not_listed_online: [
            {
              item_id: item.item_id,
              sku: item.sku,
              brand: item.brand,
              product: item.product,
              note: result.note,
              decided_by_name: result.decided_by_name,
              decided_at: result.decided_at,
            },
            ...others(queue.not_listed_online),
          ],
        },
      }
    })
  }

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
            An approved item gets its shelf or bin here too, one held for its season comes back here
            in its release month, and one kept off online can be put back for review.
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
              <div aria-live="polite">
                {keptOff && (
                  <p className="mb-3 font-bold">
                    {keptOff} won't be listed online, and it's under Not listed online if it needs
                    to go back.
                  </p>
                )}
              </div>
              <HeldQueue items={load.queue.held_for_season} onGone={gone} />
              <KeptOffQueue items={load.queue.not_listed_online} />
            </>
          )}
        </>
      )}
    </AuthLayout>
  )
}
