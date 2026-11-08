import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import {
  createListingDrafts,
  editListingDraft,
  submitListingDrafts,
  type Channel,
  type ListingDraft,
} from '@/api/appraisal'
import { Field, SubmitButton, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import { CHANNEL_NAMES } from './approval/format'

const TITLE_MAX = 80
const DESCRIPTION_MAX = 1000

const FIELD_CLASSES =
  'w-full min-w-0 rounded-md border-2 border-input bg-background px-2.5 text-foreground'

// Where the text came from, so staff know how far to trust it.
function sourceNote(draft: ListingDraft) {
  if (draft.source === 'model') {
    const check = draft.state === 'draft' ? ' Check it before sending.' : ''
    return `The model wrote this from the item card.${check}`
  }
  if (draft.fallback_reason === 'flagged')
    return "The model's draft made claims the card doesn't support, so this is the fixed template."
  if (draft.fallback_reason === 'model_failed')
    return "The model couldn't write a draft, so this is the fixed template."
  return 'No model is set up here, so this is the fixed template.'
}

type Values = { title: string; description: string; category: string }

const valuesOf = (draft: ListingDraft): Values => ({
  title: draft.title,
  description: draft.description,
  category: draft.category,
})

function DraftForm({
  draft,
  locked,
  onSaved,
  onDirty,
}: {
  draft: ListingDraft
  locked: boolean
  onSaved: (draft: ListingDraft) => void
  onDirty: (channel: Channel, dirty: boolean) => void
}) {
  const [values, setValues] = useState(() => valuesOf(draft))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const saved = valuesOf(draft)
  const dirty = (Object.keys(saved) as (keyof Values)[]).some(
    (name) => values[name] !== saved[name],
  )
  const id = `draft-${draft.channel}`
  const titleMissing = !values.title.trim()
  const descriptionMissing = !values.description.trim()
  const disabled = locked || saving

  useEffect(() => onDirty(draft.channel, dirty), [draft.channel, dirty, onDirty])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!dirty || titleMissing || descriptionMissing || disabled) return
    setSaving(true)
    setError(null)
    try {
      const next = await editListingDraft(draft.item_id, draft.channel, values)
      setValues(valuesOf(next))
      onSaved(next)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby={`${id}-heading`} className="mb-7 border border-rule p-4">
      <h3 id={`${id}-heading`} className="mb-2 text-xl font-bold">
        {CHANNEL_NAMES[draft.channel]}
      </h3>
      <p className="mb-4 text-muted-foreground">{sourceNote(draft)}</p>
      {draft.fallback_reason === 'flagged' && draft.model_flags.length > 0 && (
        <p className="mb-4 text-sm text-muted-foreground">
          It said: {draft.model_flags.map((flag) => flag.phrase).join(', ')}.
        </p>
      )}
      {draft.flags.length > 0 && (
        <div className="mb-6 border-l-4 border-destructive pl-3.5">
          <p className="mb-1 font-bold">Change or remove these claims, then save.</p>
          <ul className="list-disc pl-5">
            {draft.flags.map((flag) => (
              <li key={flag.rule + flag.phrase}>{flag.message}</li>
            ))}
          </ul>
        </div>
      )}
      {locked ? (
        <dl>
          <dt className="font-bold">Title</dt>
          <dd className="mb-3 min-w-0 break-words">{draft.title}</dd>
          <dt className="font-bold">Category</dt>
          <dd className="mb-3">{draft.category}</dd>
          <dt className="font-bold">Description</dt>
          <dd className="min-w-0 break-words whitespace-pre-line">{draft.description}</dd>
        </dl>
      ) : (
        <form onSubmit={(event) => void save(event)} noValidate>
          <Field
            id={`${id}-title`}
            label="Title"
            hint={`${values.title.length} of ${TITLE_MAX} characters.`}
            error={titleMissing ? 'Enter a title.' : undefined}
          >
            {({ id: inputId, describedBy, invalid }) => (
              <TextInput
                id={inputId}
                value={values.title}
                maxLength={TITLE_MAX}
                disabled={disabled}
                invalid={invalid}
                aria-describedby={describedBy}
                onChange={(event) => setValues({ ...values, title: event.target.value })}
              />
            )}
          </Field>
          <Field id={`${id}-category`} label="Category">
            {({ id: inputId }) => (
              <select
                id={inputId}
                value={values.category}
                disabled={disabled}
                onChange={(event) => setValues({ ...values, category: event.target.value })}
                className={`h-11 ${FIELD_CLASSES}`}
              >
                {draft.category_options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            id={`${id}-description`}
            label="Description"
            error={descriptionMissing ? 'Enter a description.' : undefined}
          >
            {({ id: inputId, describedBy, invalid }) => (
              <textarea
                id={inputId}
                value={values.description}
                rows={6}
                maxLength={DESCRIPTION_MAX}
                disabled={disabled}
                aria-invalid={invalid}
                aria-describedby={describedBy}
                onChange={(event) => setValues({ ...values, description: event.target.value })}
                className={`block py-2 ${FIELD_CLASSES} ${invalid ? 'border-destructive' : ''}`}
              />
            )}
          </Field>
          {error && (
            <p role="alert" className="mb-4 font-bold text-destructive">
              {error}
            </p>
          )}
          {dirty ? (
            <SubmitButton pending={saving}>{saving ? 'Saving...' : 'Save and check'}</SubmitButton>
          ) : (
            <p className="text-sm text-muted-foreground">
              {draft.staff_edited ? 'Your changes are saved.' : 'No changes yet.'}
            </p>
          )}
        </form>
      )}
    </section>
  )
}

type Status =
  | { step: 'loading' }
  | { step: 'failed'; message: string }
  | { step: 'ready' }
  | { step: 'sending' }
  | { step: 'send_failed'; message: string }

// The listing for each channel staff chose, which they check and send on to a manager.
export function ListingDrafts({
  itemId,
  channels,
  onSent,
}: {
  itemId: string
  channels: Channel[]
  onSent: () => void
}) {
  const [drafts, setDrafts] = useState<ListingDraft[]>([])
  const [status, setStatus] = useState<Status>({ step: 'loading' })
  const [dirty, setDirty] = useState<Partial<Record<Channel, boolean>>>({})
  const started = useRef(false)

  const load = useCallback(() => {
    setStatus({ step: 'loading' })
    createListingDrafts(itemId, channels)
      .then((rows) => {
        setDrafts(rows)
        setStatus({ step: 'ready' })
      })
      .catch((error: Error) => setStatus({ step: 'failed', message: error.message }))
  }, [itemId, channels])

  useEffect(() => {
    // The model can take a few seconds, so draft once even when React runs this effect twice.
    if (started.current) return
    started.current = true
    load()
  }, [load])

  const markDirty = useCallback(
    (channel: Channel, value: boolean) =>
      setDirty((current) =>
        current[channel] === value ? current : { ...current, [channel]: value },
      ),
    [],
  )

  function saved(next: ListingDraft) {
    setDrafts((current) => current.map((draft) => (draft.id === next.id ? next : draft)))
  }

  async function send() {
    setStatus({ step: 'sending' })
    try {
      setDrafts(await submitListingDrafts(itemId))
      setStatus({ step: 'ready' })
      onSent()
    } catch (error) {
      setStatus({ step: 'send_failed', message: (error as Error).message })
    }
  }

  const sent = drafts.length > 0 && drafts.every((draft) => draft.state !== 'draft')
  const flagged = drafts.some((draft) => draft.flags.length > 0)
  const unsaved = Object.values(dirty).some(Boolean)
  const sending = status.step === 'sending'
  const blocker = flagged
    ? 'Fix the flagged claims before sending.'
    : unsaved
      ? 'Save your changes before sending.'
      : null

  return (
    <section aria-labelledby="drafts-heading" className="mb-7">
      <h2 id="drafts-heading" className="mb-3 text-xl font-bold">
        Listing drafts
      </h2>
      <div aria-live="polite">
        {status.step === 'loading' && <p className="mb-7 font-bold">Writing the listing...</p>}
      </div>
      {status.step === 'failed' && (
        <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
          <p className="mb-3 font-bold">{status.message}</p>
          <Button variant="outline" size="lg" onClick={load}>
            Try again
          </Button>
        </div>
      )}
      {drafts.map((draft) => (
        <DraftForm
          key={draft.id}
          draft={draft}
          locked={draft.state !== 'draft' || sending}
          onSaved={saved}
          onDirty={markDirty}
        />
      ))}
      {status.step === 'send_failed' && (
        <p role="alert" className="mb-4 font-bold text-destructive">
          {status.message}
        </p>
      )}
      {sent ? (
        <p role="status" className="font-bold">
          Sent to a manager for approval.
        </p>
      ) : (
        drafts.length > 0 && (
          <div>
            {blocker && <p className="mb-3">{blocker}</p>}
            <Button
              size="lg"
              className="max-sm:w-full"
              disabled={Boolean(blocker) || sending}
              aria-busy={sending}
              onClick={() => void send()}
            >
              {sending ? 'Sending...' : 'Send for manager approval'}
            </Button>
          </div>
        )
      )}
    </section>
  )
}
