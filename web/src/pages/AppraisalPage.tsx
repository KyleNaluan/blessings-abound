import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Link } from 'react-router'

import {
  confirmItemCard,
  createAppraisal,
  createItemCard,
  listRecentDecisions,
  RepeatPhotoError,
  saveDecision,
  takeItemIn,
  type Appraisal,
  type Channel,
  type DecisionChoice,
  type Destination,
  type Item,
  type ItemCard,
  type ItemCardEdit,
  type RecentDecision,
  type RejectedMatch,
  type Rejection,
} from '@/api/appraisal'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { Field, RadioGroup, SubmitButton, TextInput } from '@/components/site/form'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

import { ChannelChoice } from './ChannelChoice'
import {
  CONDITIONS,
  DESTINATIONS,
  STORE_DEPARTMENTS,
  WHERE_IT_GOES,
  label,
  type Photo,
} from './intake'
import { IntakeForm, type Intake } from './IntakeForm'
import { ListingDrafts } from './ListingDrafts'

const money = (cents: number | null | undefined) =>
  cents == null ? 'None' : `$${(cents / 100).toFixed(2)}`

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

// The steps so far for one item. A step that fails can be tried again without repeating the ones before it.
type Progress = {
  intake: Intake
  // Staff saw that a photo matches a rejected item and chose to take it in anyway.
  allowRepeat: boolean
  item?: Item
  card?: ItemCard
  appraisal?: Appraisal
}

type Status =
  | { step: 'idle' }
  | { step: 'working'; label: string }
  | { step: 'repeat'; matches: RejectedMatch[] }
  | { step: 'checking' }
  | { step: 'failed'; message: string }
  | { step: 'ready' }
  | { step: 'rejecting'; error?: string }
  | { step: 'deciding'; decision: DecisionChoice }
  | { step: 'saved'; decision: DecisionChoice; destination?: Destination }

const CATEGORY_LABELS = { apparel: 'Apparel', electronics_games: 'Electronics and games' }
const CONFIDENCE_LABELS = { low: 'Low', medium: 'Medium', high: 'High' }

// The card fields staff can change here, in the order they are shown.
const TEXT_FIELDS = [
  ['brand', 'Brand'],
  ['product', 'Product'],
  ['exact_model', 'Exact model'],
  ['color', 'Color'],
  ['material', 'Material'],
  ['platform', 'Platform'],
  ['visible_text', 'Visible text'],
] as const

function CardForm({
  card,
  busy,
  onConfirm,
}: {
  card: ItemCard
  busy: boolean
  onConfirm: (edit: ItemCardEdit) => void
}) {
  const [category, setCategory] = useState(card.category)
  const [searchQuery, setSearchQuery] = useState(card.search_query)
  const [text, setText] = useState(() =>
    Object.fromEntries(TEXT_FIELDS.map(([name]) => [name, card[name] ?? ''])),
  )
  const searchMissing = !searchQuery.trim()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (searchMissing || busy) return
    onConfirm({ ...text, category, search_query: searchQuery })
  }

  return (
    <form onSubmit={submit} noValidate>
      {card.needs_confirmation && (
        <p className="mb-6 border-l-4 border-destructive pl-3.5 font-bold">
          The model isn't sure about this item. Check the brand and exact model before we search.
        </p>
      )}
      <dl className="mb-6 grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
        <dt className="font-bold">Confidence</dt>
        <dd>{CONFIDENCE_LABELS[card.model_confidence]}</dd>
        <dt className="font-bold">Condition</dt>
        <dd>{label(CONDITIONS, card.condition)}</dd>
      </dl>
      <Field id="card-category" label="Category">
        {({ id }) => (
          <select
            id={id}
            value={category}
            disabled={busy}
            onChange={(event) => setCategory(event.target.value as ItemCard['category'])}
            className="h-11 w-full min-w-0 rounded-none border-2 border-input bg-background px-2.5 text-foreground"
          >
            {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
      </Field>
      {TEXT_FIELDS.map(([name, label]) => (
        <Field key={name} id={`card-${name}`} label={label}>
          {({ id }) => (
            <TextInput
              id={id}
              value={text[name]}
              disabled={busy}
              onChange={(event) => setText({ ...text, [name]: event.target.value })}
            />
          )}
        </Field>
      ))}
      <Field
        id="card-search"
        label="Search"
        hint="The words we'll search eBay for."
        error={searchMissing ? 'Enter the words to search for.' : undefined}
      >
        {({ id, describedBy, invalid }) => (
          <TextInput
            id={id}
            value={searchQuery}
            disabled={busy}
            invalid={invalid}
            aria-describedby={describedBy}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        )}
      </Field>
      <SubmitButton pending={busy}>Confirm and get the price</SubmitButton>
    </form>
  )
}

function PhotoStrip({ photos }: { photos: Photo[] }) {
  return (
    <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {photos.map((photo, index) => (
        <li key={photo.url}>
          <img
            src={photo.url}
            alt={`Photo ${index + 1} of the item`}
            className="aspect-square w-full border border-rule bg-surface object-contain"
          />
        </li>
      ))}
    </ul>
  )
}

const itemName = (row: { brand: string | null; product: string | null; sku: string }) =>
  [row.brand, row.product].filter(Boolean).join(' ') || row.sku

function RepeatWarning({
  matches,
  onTakeIn,
  onStop,
}: {
  matches: RejectedMatch[]
  onTakeIn: () => void
  onStop: () => void
}) {
  const ref = useRef<HTMLElement>(null)

  // It shows below the form, so it takes focus to scroll into view, as the error summary does.
  useLayoutEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <section
      ref={ref}
      role="alert"
      tabIndex={-1}
      aria-labelledby="repeat-heading"
      className="mb-7 border-4 border-destructive px-5 py-4 focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid"
    >
      <h2 id="repeat-heading" className="mb-2 text-xl font-bold">
        This may have been rejected before
      </h2>
      <p className="mb-3">
        A photo matches {matches.length === 1 ? 'an item' : `${matches.length} items`} staff said no
        to. Check it isn't the same item before you take it in again.
      </p>
      <ul className="mb-4">
        {matches.map((match) => (
          <li key={match.item_id} className="border-t border-rule py-3">
            <p className="font-bold break-words">{itemName(match)}</p>
            <p className="text-sm text-muted-foreground">
              SKU {match.sku}, rejected {when(match.rejected_at)}
            </p>
            <p className="break-words">Why: {match.rejection_reason}</p>
            <p>Where it went: {label(DESTINATIONS, match.destination)}</p>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3">
        <Button size="lg" className="max-sm:w-full" onClick={onStop}>
          Don't take it in
        </Button>
        <Button variant="outline" size="lg" className="max-sm:w-full" onClick={onTakeIn}>
          Take it in anyway
        </Button>
      </div>
    </section>
  )
}

const REASON_MAX = 200

function RejectionForm({
  busy,
  error,
  onSave,
  onBack,
}: {
  busy: boolean
  error?: string
  onSave: (rejection: Rejection) => void
  onBack: () => void
}) {
  const [reason, setReason] = useState('')
  const [destination, setDestination] = useState<Destination | null>(null)
  const [reasonError, setReasonError] = useState<string | undefined>()
  const [destinationError, setDestinationError] = useState<string | undefined>()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setReasonError(reason.trim() ? undefined : "Say why it isn't being listed.")
    setDestinationError(destination ? undefined : 'Choose where the item goes instead.')
    if (!reason.trim() || !destination) return
    onSave({ reason: reason.trim(), destination })
  }

  return (
    <form
      onSubmit={submit}
      noValidate
      aria-labelledby="rejection-heading"
      className="mb-7 border border-rule p-4"
    >
      <h2 id="rejection-heading" className="mb-3 text-xl font-bold">
        Not listing it
      </h2>
      {error && (
        <p role="alert" className="mb-4 border-l-4 border-destructive pl-3.5 font-bold">
          {error}
        </p>
      )}
      <Field
        id="rejection-reason"
        label="Why it isn't being listed"
        hint="Such as too worn, or worth too little online."
        error={reasonError}
      >
        {({ id, describedBy, invalid }) => (
          <TextInput
            id={id}
            value={reason}
            maxLength={REASON_MAX}
            disabled={busy}
            invalid={invalid}
            aria-describedby={describedBy}
            onChange={(event) => setReason(event.target.value)}
          />
        )}
      </Field>
      <RadioGroup
        id="destination"
        legend="Where it goes instead"
        options={DESTINATIONS}
        value={destination}
        error={destinationError}
        disabled={busy}
        onChange={setDestination}
      />
      <div className="flex flex-wrap gap-3">
        <SubmitButton pending={busy}>Save the no</SubmitButton>
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          disabled={busy}
          onClick={onBack}
        >
          Back
        </Button>
      </div>
    </form>
  )
}

// PLACEHOLDER: #17 replaces this screen with the full appraisal design, keeping the same API calls.
export function AppraisalPage() {
  usePageTitle('Appraise an item')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [status, setStatus] = useState<Status>({ step: 'idle' })
  const [recent, setRecent] = useState<RecentDecision[] | null>(null)
  const [recentError, setRecentError] = useState<string | null>(null)
  const [channels, setChannels] = useState<Channel[] | null>(null)
  const [listingSent, setListingSent] = useState(false)
  // A new key clears the intake form when staff start over.
  const [formKey, setFormKey] = useState(0)
  const [photos, setPhotos] = useState<Photo[]>([])
  const photosRef = useRef(photos)

  useEffect(() => {
    photosRef.current = photos
  }, [photos])

  // The previews' object URLs go with the page.
  useEffect(() => () => photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.url)), [])

  const loadRecent = useCallback(
    () =>
      listRecentDecisions()
        .then((rows) => {
          setRecent(rows)
          setRecentError(null)
        })
        .catch((error: Error) => setRecentError(error.message)),
    [],
  )

  useEffect(() => {
    void loadRecent()
  }, [loadRecent])

  async function run(start: Progress) {
    const next = { ...start }
    try {
      if (!next.item) {
        setStatus({
          step: 'working',
          label:
            next.intake.item.photos.length === 1 ? 'Uploading the photo' : 'Uploading the photos',
        })
        next.item = await takeItemIn(next.intake.item, next.allowRepeat)
        setProgress({ ...next })
      }
      if (!next.card) {
        setStatus({ step: 'working', label: 'Making the item card' })
        next.card = await createItemCard(next.item.id, next.intake.entries)
        setProgress({ ...next })
      }
      // Staff check every card before a search is spent, and the API insists when the model is unsure.
      if (!next.card.staff_confirmed) {
        setStatus({ step: 'checking' })
        return
      }
      if (!next.appraisal) {
        setStatus({ step: 'working', label: 'Working out the price' })
        next.appraisal = await createAppraisal(next.item.id)
        setProgress({ ...next })
      }
      setStatus({ step: 'ready' })
    } catch (error) {
      if (error instanceof RepeatPhotoError) setStatus({ step: 'repeat', matches: error.matches })
      else setStatus({ step: 'failed', message: (error as Error).message })
    }
  }

  function takeIn(intake: Intake) {
    const start = { intake, allowRepeat: false }
    setProgress(start)
    void run(start)
  }

  function takeInAnyway() {
    if (!progress) return
    const next = { ...progress, allowRepeat: true }
    setProgress(next)
    void run(next)
  }

  async function confirmCard(edit: ItemCardEdit) {
    if (!progress?.item) return
    setStatus({ step: 'working', label: 'Saving the card' })
    try {
      const card = await confirmItemCard(progress.item.id, edit)
      const next = { ...progress, card }
      setProgress(next)
      await run(next)
    } catch (error) {
      setStatus({ step: 'failed', message: (error as Error).message })
    }
  }

  async function decide(decision: DecisionChoice, rejection?: Rejection) {
    if (!progress?.item || !progress.appraisal) return
    setStatus({ step: 'deciding', decision })
    try {
      await saveDecision(progress.item.id, progress.appraisal.id, decision, rejection)
      setStatus({ step: 'saved', decision, destination: rejection?.destination })
      await loadRecent()
    } catch (error) {
      const message = (error as Error).message
      // A no that didn't save stays in its form, so the reason staff typed isn't lost.
      setStatus(
        decision === 'no' ? { step: 'rejecting', error: message } : { step: 'failed', message },
      )
    }
  }

  function retry() {
    if (!progress) return
    if (progress.appraisal) setStatus({ step: 'ready' })
    else if (progress.card && !progress.card.staff_confirmed) setStatus({ step: 'checking' })
    else void run(progress)
  }

  function startOver() {
    setProgress(null)
    setStatus({ step: 'idle' })
    setChannels(null)
    setListingSent(false)
    setFormKey(formKey + 1)
    photos.forEach((photo) => URL.revokeObjectURL(photo.url))
    setPhotos([])
  }

  const busy = status.step === 'working' || status.step === 'deciding'
  const { item, card, appraisal } = progress ?? {}
  const rejecting =
    status.step === 'rejecting' || (status.step === 'deciding' && status.decision === 'no')

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Appraise an item</PageHeading>
      <Lead>Take the item in with its photos, check the card and the price, then decide.</Lead>

      {!item && (
        <IntakeForm
          key={formKey}
          // A fresh form after starting over takes focus, so staff are back where the next item starts.
          focusPhotos={formKey > 0}
          busy={busy}
          photos={photos}
          onPhotosChange={setPhotos}
          onSubmit={takeIn}
        />
      )}

      {item && (
        <section aria-labelledby="item-heading" className="mb-7 border border-rule p-4">
          <h2 id="item-heading" className="mb-3 text-xl font-bold">
            Taken in as {item.sku}
          </h2>
          <PhotoStrip photos={photos} />
          <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
            <dt className="font-bold">Department</dt>
            <dd>
              {item.store_department ? label(STORE_DEPARTMENTS, item.store_department) : 'None'}
            </dd>
            <dt className="font-bold">Notes</dt>
            <dd className="min-w-0 break-words">{item.notes ?? 'None'}</dd>
          </dl>
        </section>
      )}

      <div aria-live="polite">
        {status.step === 'working' && <p className="mb-7 font-bold">{status.label}...</p>}
      </div>

      {status.step === 'repeat' && (
        <RepeatWarning matches={status.matches} onTakeIn={takeInAnyway} onStop={startOver} />
      )}

      {status.step === 'failed' && (
        <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
          <p className="mb-3 font-bold">{status.message}</p>
          <div className="flex flex-wrap gap-3">
            {progress && (
              <Button variant="outline" size="lg" onClick={retry}>
                Try again
              </Button>
            )}
            <Button variant="outline" size="lg" onClick={startOver}>
              Start over
            </Button>
          </div>
        </div>
      )}

      {card && (
        <section aria-labelledby="card-heading" className="mb-7 border border-rule p-4">
          <h2 id="card-heading" className="mb-3 text-xl font-bold">
            Item card
          </h2>
          {card.staff_confirmed ? (
            <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
              <dt className="font-bold">Category</dt>
              <dd>{CATEGORY_LABELS[card.category]}</dd>
              {TEXT_FIELDS.map(([name, label]) => (
                <Fragment key={name}>
                  <dt className="font-bold">{label}</dt>
                  <dd className="min-w-0 break-words">{card[name] ?? 'None'}</dd>
                </Fragment>
              ))}
              <dt className="font-bold">Search</dt>
              <dd className="min-w-0 break-words">{card.search_query}</dd>
            </dl>
          ) : (
            <CardForm card={card} busy={busy} onConfirm={(edit) => void confirmCard(edit)} />
          )}
        </section>
      )}

      {appraisal && (
        <section aria-labelledby="price-heading" className="mb-7 border border-rule p-4">
          <h2 id="price-heading" className="mb-3 text-xl font-bold">
            Price range
          </h2>
          <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
            <dt className="font-bold">Low</dt>
            <dd>{money(appraisal.price_low_cents)}</dd>
            <dt className="font-bold">Typical</dt>
            <dd>{money(appraisal.price_typical_cents)}</dd>
            <dt className="font-bold">High</dt>
            <dd>{money(appraisal.price_high_cents)}</dd>
            <dt className="font-bold">Net after fees</dt>
            <dd>{money(appraisal.net_after_fees_cents)}</dd>
            <dt className="font-bold">Worth listing</dt>
            <dd className="capitalize">{appraisal.recommendation}</dd>
          </dl>
          {appraisal.explanation && <p className="mt-3">{appraisal.explanation}</p>}
        </section>
      )}

      {appraisal && (status.step === 'ready' || (status.step === 'deciding' && !rejecting)) && (
        <div className="mb-7 flex gap-3">
          <Button size="lg" className="flex-1" disabled={busy} onClick={() => decide('yes')}>
            Yes, list it
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="flex-1"
            disabled={busy}
            onClick={() => setStatus({ step: 'rejecting' })}
          >
            No, don't list it
          </Button>
        </div>
      )}

      {appraisal && rejecting && (
        <RejectionForm
          busy={busy}
          error={status.step === 'rejecting' ? status.error : undefined}
          onSave={(rejection) => void decide('no', rejection)}
          onBack={() => setStatus({ step: 'ready' })}
        />
      )}

      {status.step === 'saved' && (
        <div className="mb-7">
          <p role="status" className="mb-7 font-bold">
            Saved your decision: {status.decision}.
            {status.destination && ` ${WHERE_IT_GOES[status.destination]}`}
          </p>
          {status.decision === 'yes' && progress?.item && (
            <ChannelChoice itemId={progress.item.id} onChoose={setChannels} />
          )}
          {status.decision === 'yes' && progress?.item && channels && (
            <ListingDrafts
              itemId={progress.item.id}
              channels={channels}
              onSent={() => setListingSent(true)}
            />
          )}
          <Button
            size="lg"
            // The listing is the next step after a yes, until it has gone to a manager.
            variant={status.decision === 'yes' && !listingSent ? 'outline' : 'default'}
            className="max-sm:w-full"
            onClick={startOver}
          >
            Appraise another item
          </Button>
        </div>
      )}

      <section aria-labelledby="recent-heading" className="border-t border-rule pt-6">
        <h2 id="recent-heading" className="mb-3 text-xl font-bold">
          Recent decisions
        </h2>
        {recentError && <p role="alert">{recentError}</p>}
        {!recentError && recent?.length === 0 && <p>No decisions yet.</p>}
        {recent && recent.length > 0 && (
          <ul>
            {recent.map((row) => (
              <li key={row.id} className="border-b border-rule py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="min-w-0 font-bold break-words">{row.product ?? row.sku}</span>
                  <span className="flex-none font-bold">
                    {row.decision === 'yes' ? 'Yes' : 'No'}
                  </span>
                </div>
                {row.destination && <p>{label(DESTINATIONS, row.destination)}</p>}
                <p className="text-sm text-muted-foreground">
                  {[
                    row.price_typical_cents == null
                      ? 'No price'
                      : `${money(row.price_typical_cents)} typical`,
                    row.decided_by_name,
                    when(row.decided_at),
                  ].join(', ')}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </AuthLayout>
  )
}
