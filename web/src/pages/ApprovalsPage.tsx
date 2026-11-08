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
import { AppLayout } from '@/components/site/AppLayout'
import { Lead, PageHeading } from '@/components/site/AuthLayout'
import {
  ActionCell,
  Cell,
  DataTable,
  DetailsRow,
  EmptyTable,
  Row,
  SubText,
  TableBody,
  TableSection,
  type Column,
} from '@/components/site/DataTable'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { CHANNEL_NAMES, itemName, releaseMonth, when } from '@/pages/approval/format'
import { NotOnlineForm, PutBackForm } from '@/pages/approval/NotOnlineForm'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; queue: ApprovalQueue }

function channelNames(item: QueueItem) {
  return item.channels.map((channel) => CHANNEL_NAMES[channel]).join(' and ')
}

// The item's name, linking to its review, with its SKU under it.
function ItemCell({ item, sku }: { item: QueueItem | KeptOffItem; sku: string }) {
  return (
    <Cell>
      <Link to={`/app/approvals/${item.item_id}`} className="font-bold break-words">
        {itemName(item)}
      </Link>
      <SubText>{sku}</SubText>
    </Cell>
  )
}

// Why an item is in a queue, when it isn't simply new.
function queueNote(item: QueueItem) {
  if (item.put_back) return 'Put back for review'
  if (item.back_for_review && item.release_month)
    return `Back in season from ${releaseMonth(item.release_month)}`
  if (item.status === 'held_for_season') return 'Held for its season'
  return null
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
  const columns: Column[] = [
    { label: 'Item' },
    { label: 'Channels', width: 'w-[12rem]' },
    { label: since, width: 'w-[15rem]' },
  ]
  return (
    <TableSection id={id} title={title} count={items.length}>
      {items.length === 0 ? (
        <EmptyTable>{empty}</EmptyTable>
      ) : (
        <DataTable columns={columns}>
          <TableBody>
            {items.map((item) => (
              <Row key={item.item_id}>
                <ItemCell item={item} sku={item.full_sku ?? item.sku} />
                <Cell>{channelNames(item)}</Cell>
                <Cell>
                  {item.waiting_since ? when(item.waiting_since) : 'Not recorded'}
                  {queueNote(item) && <SubText>{queueNote(item)}</SubText>}
                </Cell>
              </Row>
            ))}
          </TableBody>
        </DataTable>
      )}
    </TableSection>
  )
}

const HELD_COLUMNS: Column[] = [
  { label: 'Item' },
  { label: 'Held until', width: 'w-[10rem]' },
  { label: 'Shelf or bin', width: 'w-[9rem]' },
  { label: 'Actions', width: 'w-[19rem]', hidden: true },
]

// One held item, which a manager can bring into review early or take out of online selling.
function HeldItem({
  item,
  open,
  onToggle,
  onGone,
}: {
  item: QueueItem
  open: boolean
  onToggle: () => void
  onGone: (item: QueueItem, result: NotOnlineResult) => void
}) {
  const navigate = useNavigate()
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const detailsId = `held-${item.item_id}-details`

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
    <TableBody>
      <Row open={open}>
        <Cell>
          <Link to={`/app/approvals/${item.item_id}`} className="font-bold break-words">
            {itemName(item)}
          </Link>
          <SubText>
            {item.full_sku ?? item.sku}, for {channelNames(item)}
          </SubText>
          {error && (
            <span role="alert" className="mt-2 block font-bold text-destructive">
              {error}
            </span>
          )}
        </Cell>
        <Cell>{item.release_month ? releaseMonth(item.release_month) : 'Not set'}</Cell>
        <Cell>{item.location_code ?? 'No shelf yet'}</Cell>
        {/* While its form is open the row's buttons step aside, and the form has its own Cancel. */}
        <ActionCell>
          {!open && (
            <>
              <Button
                size="lg"
                disabled={sending}
                aria-busy={sending}
                onClick={() => void sendNow()}
              >
                {sending ? 'Sending...' : 'List now'}
              </Button>
              <Button variant="outline" size="lg" disabled={sending} onClick={onToggle}>
                Don't list online
              </Button>
            </>
          )}
        </ActionCell>
      </Row>
      {open && (
        <DetailsRow id={detailsId} colSpan={HELD_COLUMNS.length}>
          <p className="mt-3 mb-3">
            It comes off online selling, such as to sell it on the store floor, until a manager puts
            it back for review.
          </p>
          <NotOnlineForm
            itemId={item.item_id}
            idPrefix={`held-${item.item_id}`}
            onDone={(result) => onGone(item, result)}
            onCancel={onToggle}
          />
        </DetailsRow>
      )}
    </TableBody>
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
  // One item's form is open at a time.
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <TableSection
      id="held"
      title="Held for season"
      count={items.length}
      description="Each item comes back to Waiting for approval in its release month, so you can check its price before it's listed. List now brings it back early."
    >
      {items.length === 0 ? (
        <EmptyTable>No item is held for its season.</EmptyTable>
      ) : (
        <DataTable columns={HELD_COLUMNS}>
          {items.map((item) => (
            <HeldItem
              key={item.item_id}
              item={item}
              open={openId === item.item_id}
              onToggle={() => setOpenId(openId === item.item_id ? null : item.item_id)}
              onGone={onGone}
            />
          ))}
        </DataTable>
      )}
    </TableSection>
  )
}

const KEPT_OFF_COLUMNS: Column[] = [
  { label: 'Item' },
  { label: 'Kept off by', width: 'w-[13rem]' },
  { label: 'Note' },
  { label: 'Actions', width: 'w-[15rem]', hidden: true },
]

// One item kept off online, which a manager can put back for review with a note on why.
function KeptOffRow({
  item,
  open,
  onToggle,
}: {
  item: KeptOffItem
  open: boolean
  onToggle: () => void
}) {
  const navigate = useNavigate()
  const detailsId = `kept-off-${item.item_id}-details`

  return (
    <TableBody>
      <Row open={open}>
        <ItemCell item={item} sku={item.sku} />
        <Cell>
          {item.decided_by_name}
          <SubText>{when(item.decided_at)}</SubText>
        </Cell>
        <Cell className="break-words">
          {item.note ?? <span className="text-muted-foreground">No note</span>}
        </Cell>
        <ActionCell>
          {!open && (
            <Button variant="outline" size="lg" onClick={onToggle}>
              Put back for review
            </Button>
          )}
        </ActionCell>
      </Row>
      {open && (
        <DetailsRow id={detailsId} colSpan={KEPT_OFF_COLUMNS.length}>
          <p className="mt-3 mb-3">
            It goes back to Waiting for approval, so you can check its listing and price before
            anything goes online.
          </p>
          <PutBackForm
            itemId={item.item_id}
            idPrefix={`kept-off-${item.item_id}`}
            onDone={() => void navigate(`/app/approvals/${item.item_id}`)}
            onCancel={onToggle}
          />
        </DetailsRow>
      )}
    </TableBody>
  )
}

// Items taken out of online selling, newest first, which a manager can put back for review.
function KeptOffQueue({ items }: { items: KeptOffItem[] }) {
  // One item's form is open at a time.
  const [openId, setOpenId] = useState<string | null>(null)
  return (
    <TableSection
      id="kept-off"
      title="Not listed online"
      count={items.length}
      description="Put back for review sends an item to Waiting for approval, where it goes through the usual review and price check before it's listed. This shows the latest 50."
    >
      {items.length === 0 ? (
        <EmptyTable>No item is kept off online.</EmptyTable>
      ) : (
        <DataTable columns={KEPT_OFF_COLUMNS}>
          {items.map((item) => (
            <KeptOffRow
              key={item.item_id}
              item={item}
              open={openId === item.item_id}
              onToggle={() => setOpenId(openId === item.item_id ? null : item.item_id)}
            />
          ))}
        </DataTable>
      )}
    </TableSection>
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
    <AppLayout>
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
            <div
              role="alert"
              className="mb-7 rounded-xl border-4 border-destructive bg-card px-5 py-4"
            >
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
                since="Sent"
              />
              <Queue
                id="storage"
                title="Waiting for a shelf"
                empty="Every approved item is on a shelf."
                items={load.queue.awaiting_storage}
                since="Approved"
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
    </AppLayout>
  )
}
