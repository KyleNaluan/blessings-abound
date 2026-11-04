import { useState, type FormEvent, type ReactNode } from 'react'

import {
  approveItem,
  rejectItem,
  saveStorage,
  setListingPrice,
  type BoxSizeOption,
  type ItemReview,
  type ListingReview,
} from '@/api/approval'
import { Field, SubmitButton, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'
import { dollars, parseDollars, parseNumber } from '@/pages/settings/numbers'

import { billedWeight, boxLabel, CHANNEL_NAMES, money } from './format'

// The parts of the review page: one panel per listing, the package and shelf, and the decision.

type PanelProps = { review: ItemReview; onChange: (review: ItemReview) => void }

const SELECT =
  'h-11 w-full min-w-0 rounded-none border-2 border-input bg-background px-2.5 text-foreground'
const AREA =
  'block min-h-11 w-full min-w-0 resize-y rounded-none border-2 border-input bg-background px-2.5 py-2 text-foreground'

// Item statuses an approved item has before it is published, which is when it gets a shelf.
const STORABLE = new Set(['approved', 'held_for_season'])

function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-heading`} className="mb-7 border border-rule p-4">
      <h2 id={`${id}-heading`} className="mb-3 text-xl font-bold">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Failure({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="mb-4 font-bold text-destructive">
      {message}
    </p>
  )
}

// Runs one call at a time for a panel and keeps what went wrong.
function useCall(onChange: (review: ItemReview) => void) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(call: () => Promise<ItemReview>) {
    setPending(true)
    setError(null)
    try {
      const review = await call()
      onChange(review)
      return review
    } catch (failure) {
      setError((failure as Error).message)
      return null
    } finally {
      setPending(false)
    }
  }

  return { pending, error, setError, run }
}

const STATE_NOTES: Record<ListingReview['state'], string> = {
  draft: 'Staff are still editing this listing.',
  awaiting_approval: 'Waiting for your approval.',
  approved: 'Approved.',
  rejected: 'Rejected.',
}

export function ListingPanel({
  review,
  listing,
  onChange,
}: PanelProps & { listing: ListingReview }) {
  const name = CHANNEL_NAMES[listing.channel]
  const id = `listing-${listing.channel}`
  const editable = review.status === 'appraised' && listing.state === 'awaiting_approval'
  const [price, setPrice] = useState(
    listing.price_override_cents === null ? '' : dollars(listing.price_override_cents),
  )
  const { pending, error, setError, run } = useCall(onChange)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    const text = price.trim()
    const cents = text ? parseDollars(text) : null
    if (text && (cents === null || cents === 0)) {
      setError('Enter the price in dollars, such as 45.00, or leave it empty.')
      return
    }
    const result = await run(() => setListingPrice(review.item_id, listing.channel, cents))
    if (result) setPrice(cents === null ? '' : dollars(cents))
  }

  return (
    <Panel id={id} title={name}>
      <p className="mb-4 text-muted-foreground">{STATE_NOTES[listing.state]}</p>
      {listing.flags.length > 0 && (
        <div className="mb-5 border-l-4 border-destructive pl-3.5">
          <p className="mb-1 font-bold">The checker found claims the item card doesn't support.</p>
          <ul className="list-disc pl-5">
            {listing.flags.map((flag) => (
              <li key={flag.rule + flag.phrase}>{flag.message}</li>
            ))}
          </ul>
        </div>
      )}
      <dl className="mb-5">
        <dt className="font-bold">Title</dt>
        <dd className="mb-3 min-w-0 break-words">{listing.title}</dd>
        <dt className="font-bold">Category</dt>
        <dd className="mb-3">{listing.category}</dd>
        <dt className="font-bold">Description</dt>
        <dd className="min-w-0 break-words whitespace-pre-line">{listing.description}</dd>
      </dl>
      <dl className="mb-5 border-y border-rule py-3">
        <div className="flex justify-between gap-4">
          <dt>Typical sale price</dt>
          <dd>
            {listing.base_price_cents === null ? 'None found' : money(listing.base_price_cents)}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt>Listing price</dt>
          <dd className="font-bold">
            {listing.price_cents === null ? 'Not set' : money(listing.price_cents)}
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt>Left after {name} fees</dt>
          <dd className="font-bold">
            {listing.net_after_fees_cents === null
              ? 'Not set'
              : money(listing.net_after_fees_cents)}
          </dd>
        </div>
      </dl>
      {editable && (
        <form onSubmit={(event) => void submit(event)} noValidate>
          <Field
            id={`${id}-price`}
            label={`Price for ${name}`}
            hint="In dollars. Leave it empty to use the typical sale price."
            error={error ?? undefined}
          >
            {({ id: inputId, describedBy, invalid }) => (
              <TextInput
                id={inputId}
                value={price}
                inputMode="decimal"
                disabled={pending}
                invalid={invalid}
                aria-describedby={describedBy}
                onChange={(event) => setPrice(event.target.value)}
              />
            )}
          </Field>
          <SubmitButton pending={pending}>{pending ? 'Saving...' : 'Save the price'}</SubmitButton>
        </form>
      )}
    </Panel>
  )
}

export function PackagePanel({ review, boxes, onChange }: PanelProps & { boxes: BoxSizeOption[] }) {
  const storing = STORABLE.has(review.status)
  const [weight, setWeight] = useState(
    review.package_weight_oz === null ? '' : String(review.package_weight_oz),
  )
  const [box, setBox] = useState(review.box_code ?? '')
  const [shelf, setShelf] = useState(review.location_code ?? '')
  const [errors, setErrors] = useState<Record<string, string>>({})
  // The review the last save returned, so "Saved" shows until anything changes after it.
  const [saved, setSaved] = useState<ItemReview | null>(null)
  const { pending, error, run } = useCall(onChange)
  // A box taken out of Settings since it was chosen still shows, so the saved choice reads true.
  const options = boxes.some((option) => option.code === review.box_code)
    ? boxes.map((option) => option.code)
    : [...(review.box_code ? [review.box_code] : []), ...boxes.map((option) => option.code)]

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    const found: Record<string, string> = {}
    const oz = parseNumber(weight)
    if (oz === null || oz === 0) found.weight = 'Enter the package weight in ounces, such as 22.4.'
    if (!box) found.box = 'Choose a box size.'
    if (storing && !shelf.trim()) found.shelf = 'Enter the shelf or bin code, such as A3.'
    setErrors(found)
    if (Object.keys(found).length || oz === null) return
    const result = await run(() =>
      saveStorage(review.item_id, {
        package_weight_oz: oz,
        box_code: box,
        location_code: storing ? shelf : null,
      }),
    )
    if (!result) return
    setShelf(result.location_code ?? '')
    setSaved(result)
  }

  return (
    <Panel id="package" title={storing ? 'Package and shelf' : 'Package'}>
      <p className="mb-5">
        {storing
          ? 'Weigh the packed item and enter where it is stored. The box size is added to the SKU.'
          : 'Channel A needs the packed weight and box size before you approve it. The box size is added to the SKU.'}
      </p>
      <Failure message={error} />
      <form onSubmit={(event) => void submit(event)} noValidate>
        <Field
          id="package-weight"
          label="Package weight (oz)"
          hint="Packed, to the nearest tenth of an ounce. 1 lb is 16 oz."
          error={errors.weight}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              value={weight}
              inputMode="decimal"
              disabled={pending}
              invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => {
                setWeight(event.target.value)
                setSaved(null)
              }}
            />
          )}
        </Field>
        <Field
          id="package-box"
          label="Box size"
          hint="From the box sizes in Settings."
          error={errors.box}
        >
          {({ id, describedBy, invalid }) => (
            <select
              id={id}
              value={box}
              disabled={pending}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => {
                setBox(event.target.value)
                setSaved(null)
              }}
              className={`${SELECT} ${invalid ? 'border-destructive' : ''}`}
            >
              <option value="">Choose a box size</option>
              {options.map((code) => (
                <option key={code} value={code}>
                  {boxLabel(code)}
                </option>
              ))}
            </select>
          )}
        </Field>
        {storing && (
          <Field
            id="package-shelf"
            label="Shelf or bin"
            hint={`Letters, numbers, spaces and dashes, such as A3 or B12\u20112.`}
            error={errors.shelf}
          >
            {({ id, describedBy, invalid }) => (
              <TextInput
                id={id}
                value={shelf}
                maxLength={20}
                autoCapitalize="characters"
                disabled={pending}
                invalid={invalid}
                aria-describedby={describedBy}
                onChange={(event) => {
                  setShelf(event.target.value)
                  setSaved(null)
                }}
              />
            )}
          </Field>
        )}
        <SubmitButton pending={pending}>
          {pending ? 'Saving...' : storing ? 'Save and store' : 'Save the package'}
        </SubmitButton>
      </form>
      <div aria-live="polite">
        {saved === review && (
          <p className="mt-3 font-bold">
            {review.location_code ? `Stored on ${review.location_code}.` : 'Saved.'}
          </p>
        )}
      </div>
      {review.billed_weight_oz !== null && (
        <p className="mt-4 text-muted-foreground">
          The label is billed at {billedWeight(review.billed_weight_oz)}.
        </p>
      )}
    </Panel>
  )
}

export function DecisionPanel({ review, onChange }: PanelProps) {
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const approval = useCall(onChange)
  const rejection = useCall(onChange)
  const pending = approval.pending || rejection.pending
  const blocked = review.blockers.length > 0

  async function reject(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    if (!reason.trim()) {
      setReasonError('Enter why you are rejecting it.')
      return
    }
    setReasonError(null)
    await rejection.run(() => rejectItem(review.item_id, reason.trim(), note.trim()))
  }

  return (
    <Panel id="decision" title="Approve or reject">
      {blocked ? (
        <div className="mb-5 border-l-4 border-destructive pl-3.5">
          <p className="mb-1 font-bold">Before you can approve it:</p>
          <ul className="list-disc pl-5">
            {review.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mb-5">Approving sends every listing above on at its listing price.</p>
      )}
      <Failure message={approval.error} />
      <Button
        size="lg"
        className="mb-8 max-sm:w-full"
        disabled={blocked || pending}
        aria-busy={approval.pending}
        onClick={() => void approval.run(() => approveItem(review.item_id))}
      >
        {approval.pending ? 'Approving...' : 'Approve'}
      </Button>
      <h3 className="mb-1 text-lg font-bold">Reject it instead</h3>
      <p className="mb-4">
        Rejecting records a no, so the item needs no package or shelf. Staff can say yes again to
        fix the listing and send it back.
      </p>
      <Failure message={rejection.error} />
      <form onSubmit={(event) => void reject(event)} noValidate>
        <Field id="reject-reason" label="Why you are rejecting it" error={reasonError ?? undefined}>
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              value={reason}
              maxLength={200}
              disabled={pending}
              invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => setReason(event.target.value)}
            />
          )}
        </Field>
        <Field id="reject-note" label="Note for staff (optional)">
          {({ id }) => (
            <textarea
              id={id}
              value={note}
              rows={3}
              maxLength={1000}
              disabled={pending}
              onChange={(event) => setNote(event.target.value)}
              className={AREA}
            />
          )}
        </Field>
        <Button
          type="submit"
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          disabled={pending}
          aria-busy={rejection.pending}
        >
          {rejection.pending ? 'Rejecting...' : 'Reject'}
        </Button>
      </form>
    </Panel>
  )
}
