import { useState, type FormEvent } from 'react'

import {
  keepOffOnline,
  putBackForReview,
  type ItemReview,
  type NotOnlineResult,
} from '@/api/approval'
import { Field, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

// The longest note the API keeps, which is enough for a short reason.
const NOTE_MAX = 200

// A short note that goes in the item's history with a manager's or staff member's choice.
function NoteForm<T>({
  idPrefix,
  label,
  emptyError,
  submitLabel,
  primary = false,
  save,
  onDone,
  onCancel,
}: {
  idPrefix: string
  label: string
  emptyError: string
  submitLabel: string
  // The main action where it's offered, rather than one beside it.
  primary?: boolean
  save: (note: string) => Promise<T>
  onDone: (result: T) => void
  onCancel?: () => void
}) {
  const [note, setNote] = useState('')
  const [noteError, setNoteError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    const text = note.trim()
    if (!text) {
      setNoteError(emptyError)
      return
    }
    setNoteError(null)
    setError(null)
    setPending(true)
    try {
      onDone(await save(text))
    } catch (failure) {
      setError((failure as Error).message)
      setPending(false)
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} noValidate>
      {error && (
        <p role="alert" className="mb-4 font-bold text-destructive">
          {error}
        </p>
      )}
      <Field
        id={`${idPrefix}-note`}
        label={label}
        hint="Up to 200 characters. It goes in the item's history."
        error={noteError ?? undefined}
      >
        {({ id, describedBy, invalid }) => (
          <TextInput
            id={id}
            value={note}
            maxLength={NOTE_MAX}
            disabled={pending}
            invalid={invalid}
            aria-describedby={describedBy}
            onChange={(event) => setNote(event.target.value)}
          />
        )}
      </Field>
      <div className="flex gap-3 max-sm:flex-col">
        <Button
          type="submit"
          variant={primary ? 'default' : 'outline'}
          size="lg"
          className="max-sm:w-full"
          disabled={pending}
          aria-busy={pending}
        >
          {pending ? 'Saving...' : submitLabel}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            size="lg"
            className="max-sm:w-full"
            disabled={pending}
            onClick={onCancel}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}

// Takes an item out of online selling, with a short note on why, until a manager puts it back.
export function NotOnlineForm({
  itemId,
  idPrefix,
  onDone,
  onCancel,
}: {
  itemId: string
  idPrefix: string
  onDone: (result: NotOnlineResult) => void
  onCancel?: () => void
}) {
  return (
    <NoteForm
      idPrefix={idPrefix}
      label="Why it isn't going online"
      emptyError="Enter why it isn't going online, such as to sell it on the store floor."
      submitLabel="Don't list online"
      save={(note) => keepOffOnline(itemId, note)}
      onDone={onDone}
      onCancel={onCancel}
    />
  )
}

// Undoes Don't list online, which sends the item back to Waiting for approval.
export function PutBackForm({
  itemId,
  idPrefix,
  onDone,
  onCancel,
}: {
  itemId: string
  idPrefix: string
  onDone: (review: ItemReview) => void
  onCancel?: () => void
}) {
  return (
    <NoteForm
      idPrefix={idPrefix}
      label="Why it's going back for review"
      emptyError="Enter why it's going back for review, such as a customer asked for it online."
      submitLabel="Put back for review"
      primary
      save={(note) => putBackForReview(itemId, note)}
      onDone={onDone}
      onCancel={onCancel}
    />
  )
}
