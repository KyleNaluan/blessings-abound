import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  fixDoubleSale,
  loadAttention,
  markHandled,
  type Attention,
  type ConflictKind,
  type Flag,
} from '@/api/attention'
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
import { Field } from '@/components/site/form'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { CHANNEL_NAMES, exactly, money, when } from '@/pages/approval/format'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; attention: Attention }

const KIND_NAMES: Record<ConflictKind, string> = {
  double_sale: 'Double sale',
  stale_listing: 'Stale listing',
  unknown_listing: 'Unknown listing',
}

// Quick while an explanation is being written or a cancel is being tried, and slow otherwise,
// so a new flag still shows up on a screen left open.
const BUSY_REFRESH_MS = 3000
const IDLE_REFRESH_MS = 30000

const AREA =
  'block min-h-11 w-full min-w-0 resize-y rounded-md border-2 border-input bg-background px-2.5 py-2 text-foreground'

function busy(flag: Flag) {
  return flag.explained_by === null || flag.double_sale?.cancelling?.status === 'pending'
}

function problemName(flag: Flag) {
  const channel = flag.channel && !flag.double_sale ? ` on ${CHANNEL_NAMES[flag.channel]}` : ''
  return `${KIND_NAMES[flag.conflict]}${channel}`
}

// The item a flag is about, or a dash for a listing Turnstone doesn't know.
function ItemCell({ flag }: { flag: Flag }) {
  return (
    <Cell>
      {flag.title || flag.sku ? (
        <>
          {flag.title && <span className="block font-bold break-words">{flag.title}</span>}
          {flag.sku && <SubText>{flag.sku}</SubText>}
        </>
      ) : (
        <span className="text-muted-foreground">Not in Turnstone</span>
      )}
    </Cell>
  )
}

const OPEN_COLUMNS: Column[] = [
  { label: 'Problem', width: 'w-[15rem]' },
  { label: 'Item' },
  { label: 'Found', width: 'w-[12rem]' },
  { label: 'Details', width: 'w-[8.5rem]', hidden: true },
]

const HANDLED_COLUMNS: Column[] = [
  { label: 'Problem', width: 'w-[15rem]' },
  { label: 'Item' },
  { label: 'What was done' },
  { label: 'Handled', width: 'w-[12rem]' },
]

function CancelState({ flag }: { flag: Flag }) {
  const cancelling = flag.double_sale?.cancelling
  if (!cancelling || !flag.double_sale) return null
  const channel = CHANNEL_NAMES[flag.double_sale.cancel.channel]
  if (cancelling.status === 'pending') {
    return (
      <p className="mb-5 border-l-4 border-rule pl-3.5">
        <span className="font-bold">Cancelling the {channel} order.</span>{' '}
        {cancelling.attempts > 0 &&
          `Try ${cancelling.attempts} of ${cancelling.max_attempts} didn't go through: ${cancelling.last_error ?? 'no answer'} Turnstone tries again by itself.`}
      </p>
    )
  }
  return (
    <p role="alert" className="mb-5 border-l-4 border-destructive pl-3.5">
      <span className="font-bold">The {channel} order wasn't cancelled.</span>{' '}
      {cancelling.last_error}
    </p>
  )
}

function DoubleSale({ flag }: { flag: Flag }) {
  const sale = flag.double_sale
  if (!sale) return null
  const rows = [
    { label: 'Keeps the item', order: sale.keep },
    { label: 'Order to cancel', order: sale.cancel },
  ]
  return (
    <dl className="mb-5 border-y border-rule py-3">
      {rows.map(({ label, order }) => (
        <div key={label} className="flex flex-wrap justify-between gap-x-4 py-0.5">
          <dt className="font-bold">{label}</dt>
          <dd className="text-right max-sm:text-left">
            {CHANNEL_NAMES[order.channel]}, {money(order.price_cents)}, sold{' '}
            {exactly(order.sold_at)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function ChannelIds({ flag }: { flag: Flag }) {
  if (flag.double_sale || (!flag.channel_listing_id && !flag.channel_order_id)) return null
  const channel = flag.channel ? CHANNEL_NAMES[flag.channel] : 'Channel'
  return (
    <dl className="mb-5 text-muted-foreground">
      {flag.channel_listing_id && (
        <div>
          <dt className="inline">{channel} listing: </dt>
          <dd className="inline wrap-anywhere">{flag.channel_listing_id}</dd>
        </div>
      )}
      {flag.channel_order_id && (
        <div>
          <dt className="inline">{channel} order: </dt>
          <dd className="inline wrap-anywhere">{flag.channel_order_id}</dd>
        </div>
      )}
    </dl>
  )
}

// An open flag as a row, and what Review opens under it: what happened, what to do, and the fix.
function FlagRows({
  flag,
  open,
  onToggle,
  onChange,
}: {
  flag: Flag
  open: boolean
  onToggle: () => void
  onChange: (flag: Flag) => void
}) {
  const [pending, setPending] = useState<'fix' | 'handle' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [handling, setHandling] = useState(false)
  const [note, setNote] = useState('')
  const id = `flag-${flag.id}`
  const sale = flag.double_sale
  const canFix = sale !== null && sale.cancelling?.status !== 'pending'

  async function run(kind: 'fix' | 'handle', call: () => Promise<Flag>) {
    setPending(kind)
    setError(null)
    try {
      onChange(await call())
    } catch (failure) {
      setError((failure as Error).message)
    }
    setPending(null)
  }

  function handle(event: FormEvent) {
    event.preventDefault()
    void run('handle', () => markHandled(flag.id, note.trim()))
  }

  return (
    <TableBody>
      <Row open={open}>
        <Cell className="font-bold break-words">{problemName(flag)}</Cell>
        <ItemCell flag={flag} />
        <Cell className="text-muted-foreground">{when(flag.created_at)}</Cell>
        <ActionCell>
          <Button
            variant="outline"
            size="lg"
            aria-label={`${open ? 'Close' : 'Review'} ${problemName(flag)}`}
            aria-expanded={open}
            aria-controls={open ? id : undefined}
            onClick={onToggle}
          >
            {open ? 'Close' : 'Review'}
          </Button>
        </ActionCell>
      </Row>
      {open && (
        <DetailsRow id={id} colSpan={OPEN_COLUMNS.length}>
          <p className="mt-3 mb-4 break-words">{flag.explanation}</p>
          <p className="font-bold">What to do</p>
          <p className="mb-5 break-words">{flag.suggested_fix}</p>
          <DoubleSale flag={flag} />
          <ChannelIds flag={flag} />
          <CancelState flag={flag} />
          {error && (
            <p role="alert" className="mb-4 font-bold text-destructive">
              {error}
            </p>
          )}
          {handling ? (
            <form onSubmit={handle} noValidate>
              <Field
                id={`${id}-note`}
                label="What you did (optional)"
                hint="Goes in the sync log with the flag."
              >
                {({ id: noteId, describedBy }) => (
                  <textarea
                    id={noteId}
                    value={note}
                    rows={2}
                    maxLength={500}
                    disabled={pending !== null}
                    aria-describedby={describedBy}
                    onChange={(event) => setNote(event.target.value)}
                    className={AREA}
                  />
                )}
              </Field>
              <div className="flex flex-wrap gap-3">
                <Button
                  type="submit"
                  size="lg"
                  className="max-sm:w-full"
                  disabled={pending !== null}
                  aria-busy={pending === 'handle'}
                >
                  {pending === 'handle' ? 'Saving...' : 'Mark handled'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  className="max-sm:w-full"
                  disabled={pending !== null}
                  onClick={() => setHandling(false)}
                >
                  Keep it open
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap gap-3">
              {sale && canFix && (
                <Button
                  size="lg"
                  className="max-sm:w-full"
                  disabled={pending !== null}
                  aria-busy={pending === 'fix'}
                  onClick={() => void run('fix', () => fixDoubleSale(flag.id))}
                >
                  {pending === 'fix'
                    ? 'Cancelling...'
                    : `Cancel the ${CHANNEL_NAMES[sale.cancel.channel]} order`}
                </Button>
              )}
              <Button
                variant="outline"
                size="lg"
                className="max-sm:w-full"
                disabled={pending !== null}
                onClick={() => setHandling(true)}
              >
                Mark handled
              </Button>
            </div>
          )}
        </DetailsRow>
      )}
    </TableBody>
  )
}

function HandledRow({ flag }: { flag: Flag }) {
  return (
    <Row>
      <Cell className="font-bold break-words">{problemName(flag)}</Cell>
      <ItemCell flag={flag} />
      <Cell className="break-words">{flag.resolution}</Cell>
      <Cell>
        {flag.resolved_by ?? 'Turnstone'}
        {flag.resolved_at && <SubText>{when(flag.resolved_at)}</SubText>}
      </Cell>
    </Row>
  )
}

// The conflicts sync flagged and couldn't settle by itself, for staff and managers to fix.
export function NeedsAttentionPage() {
  usePageTitle('Needs attention')
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [notice, setNotice] = useState<string | null>(null)
  // One flag's details are open at a time.
  const [openId, setOpenId] = useState<string | null>(null)

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchAttention = useCallback(() => {
    return loadAttention()
      .then((attention) => setLoad({ state: 'ready', attention }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    void fetchAttention()
  }, [fetchAttention])

  const attention = load.state === 'ready' ? load.attention : null
  const waiting = attention?.open.some(busy) ?? false
  useEffect(() => {
    if (!attention) return
    const timer = window.setTimeout(
      () => {
        loadAttention()
          .then((latest) => setLoad({ state: 'ready', attention: latest }))
          .catch(() => {
            // A missed refresh is tried again on the next one, so the page keeps what it has.
          })
      },
      waiting ? BUSY_REFRESH_MS : IDLE_REFRESH_MS,
    )
    return () => window.clearTimeout(timer)
  }, [attention, waiting])

  function changed(flag: Flag) {
    if (flag.resolved_at) setNotice(`Handled. ${flag.resolution ?? ''}`.trim())
    setLoad((current) => {
      if (current.state !== 'ready') return current
      const open = current.attention.open.filter((row) => row.id !== flag.id)
      if (flag.resolved_at) {
        const resolved = [flag, ...current.attention.resolved.filter((row) => row.id !== flag.id)]
        return { state: 'ready', attention: { open, resolved } }
      }
      const updated = current.attention.open.map((row) => (row.id === flag.id ? flag : row))
      return { state: 'ready', attention: { ...current.attention, open: updated } }
    })
  }

  return (
    <AppLayout>
      <PageHeading>Needs attention</PageHeading>
      <Lead>
        Problems between Turnstone and the sales channels that sync couldn't settle by itself. Fix
        each one, or mark it handled once you've dealt with it on the channel.
      </Lead>
      <div aria-live="polite">
        {notice && <p className="mb-7 border-y border-rule py-3.5 font-bold">{notice}</p>}
        {load.state === 'loading' && (
          <p className="mb-7 font-bold">Loading what needs attention...</p>
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
              void fetchAttention()
            }}
          >
            Try again
          </Button>
        </div>
      )}
      {attention && (
        <TableSection
          id="open"
          title="Open problems"
          count={attention.open.length}
          unit={['problem', 'problems']}
        >
          <div aria-live="polite">
            {attention.open.length === 0 && (
              <EmptyTable>Nothing needs attention right now.</EmptyTable>
            )}
          </div>
          {attention.open.length > 0 && (
            <DataTable columns={OPEN_COLUMNS}>
              {attention.open.map((flag) => (
                <FlagRows
                  key={flag.id}
                  flag={flag}
                  open={openId === flag.id}
                  onToggle={() => setOpenId(openId === flag.id ? null : flag.id)}
                  onChange={changed}
                />
              ))}
            </DataTable>
          )}
        </TableSection>
      )}
      {attention && attention.resolved.length > 0 && (
        <TableSection id="handled" title="Recently handled">
          <DataTable columns={HANDLED_COLUMNS}>
            <TableBody>
              {attention.resolved.map((flag) => (
                <HandledRow key={flag.id} flag={flag} />
              ))}
            </TableBody>
          </DataTable>
        </TableSection>
      )}
    </AppLayout>
  )
}
