import {
  Fragment,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from 'react'
import { Link } from 'react-router'

import {
  confirmItemCard,
  createAppraisal,
  createItemCard,
  listRecentDecisions,
  saveDecision,
  uploadPhoto,
  type Appraisal,
  type DecisionChoice,
  type Item,
  type ItemCard,
  type ItemCardEdit,
  type RecentDecision,
} from '@/api/appraisal'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { Field, SubmitButton, TextInput } from '@/components/site/form'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

const money = (cents: number | null | undefined) =>
  cents == null ? 'None' : `$${(cents / 100).toFixed(2)}`

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

// The steps so far for one photo. A step that fails can be tried again without repeating the ones before it.
type Progress = { photo: File; item?: Item; card?: ItemCard; appraisal?: Appraisal }

type Status =
  | { step: 'idle' }
  | { step: 'working'; label: string }
  | { step: 'checking' }
  | { step: 'failed'; message: string }
  | { step: 'ready' }
  | { step: 'deciding' }
  | { step: 'saved'; decision: DecisionChoice }

const CATEGORY_LABELS = { apparel: 'Apparel', electronics_games: 'Electronics and games' }
const CONFIDENCE_LABELS = { low: 'Low', medium: 'Medium', high: 'High' }
const CONDITION_LABELS = {
  new_with_tags: 'New with tags',
  new_without_tags: 'New without tags',
  pre_owned: 'Pre-owned',
}

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
        <dd>{CONDITION_LABELS[card.condition]}, the default until the intake form is built</dd>
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

// PLACEHOLDER: #17 replaces this screen with the full appraisal design, keeping the same API calls.
export function AppraisalPage() {
  usePageTitle('Appraise an item')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [status, setStatus] = useState<Status>({ step: 'idle' })
  const [preview, setPreview] = useState<string | null>(null)
  const [recent, setRecent] = useState<RecentDecision[] | null>(null)
  const [recentError, setRecentError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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

  useEffect(() => {
    if (!preview) return
    return () => URL.revokeObjectURL(preview)
  }, [preview])

  async function run(start: Progress) {
    const next = { ...start }
    try {
      if (!next.item) {
        setStatus({ step: 'working', label: 'Uploading the photo' })
        next.item = await uploadPhoto(next.photo)
        setProgress({ ...next })
      }
      if (!next.card) {
        setStatus({ step: 'working', label: 'Making the item card' })
        next.card = await createItemCard(next.item.id)
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
      setStatus({ step: 'failed', message: (error as Error).message })
    }
  }

  function onPhoto(event: ChangeEvent<HTMLInputElement>) {
    const photo = event.target.files?.[0]
    if (!photo) return
    setPreview(URL.createObjectURL(photo))
    const start = { photo }
    setProgress(start)
    void run(start)
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

  async function decide(decision: DecisionChoice) {
    if (!progress?.item || !progress.appraisal) return
    setStatus({ step: 'deciding' })
    try {
      await saveDecision(progress.item.id, progress.appraisal.id, decision)
      setStatus({ step: 'saved', decision })
      await loadRecent()
    } catch (error) {
      setStatus({ step: 'failed', message: (error as Error).message })
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
    setPreview(null)
    setStatus({ step: 'idle' })
    if (inputRef.current) inputRef.current.value = ''
  }

  const busy = status.step === 'working' || status.step === 'deciding'
  const { card, appraisal } = progress ?? {}

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Appraise an item</PageHeading>
      <Lead>Take a photo of the item, check the card and the price, then decide.</Lead>

      {!progress?.item && (
        <div className="mb-7">
          <label htmlFor="photo" className="mb-1 block font-bold">
            Take or choose a photo
          </label>
          <input
            ref={inputRef}
            id="photo"
            type="file"
            accept="image/*"
            disabled={busy}
            onChange={onPhoto}
            className="w-full min-w-0 border-2 border-input bg-background p-2 text-foreground"
          />
        </div>
      )}

      {preview && (
        <img
          src={preview}
          alt="The item you photographed"
          className="mb-7 max-h-64 w-full border border-rule bg-surface object-contain"
        />
      )}

      <div aria-live="polite">
        {status.step === 'working' && <p className="mb-7 font-bold">{status.label}...</p>}
      </div>

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

      {appraisal && (status.step === 'ready' || status.step === 'deciding') && (
        <div className="mb-7 flex gap-3">
          <Button size="lg" className="flex-1" disabled={busy} onClick={() => decide('yes')}>
            Yes, list it
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="flex-1"
            disabled={busy}
            onClick={() => decide('no')}
          >
            No, don't list it
          </Button>
        </div>
      )}

      {status.step === 'saved' && (
        <div className="mb-7">
          <p role="status" className="mb-3 font-bold">
            Saved your decision: {status.decision}.
          </p>
          <Button size="lg" className="max-sm:w-full" onClick={startOver}>
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
                  <Badge variant={row.decision === 'yes' ? 'default' : 'secondary'}>
                    {row.decision}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {money(row.price_typical_cents)} typical, {row.decided_by_name},{' '}
                  {when(row.decided_at)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </AuthLayout>
  )
}
