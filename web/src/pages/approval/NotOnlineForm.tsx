import { useState, type FormEvent } from 'react'

import { keepOffOnline, type NotOnlineResult } from '@/api/approval'
import { Field, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

// The longest note the API keeps, which is enough for a short reason.
const NOTE_MAX = 200

// Takes an item out of online selling for good, with a short note on why that goes in its history.
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
  const [note, setNote] = useState('')
  const [noteError, setNoteError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    const text = note.trim()
    if (!text) {
      setNoteError("Enter why it isn't going online, such as to sell it on the store floor.")
      return
    }
    setNoteError(null)
    setError(null)
    setPending(true)
    try {
      onDone(await keepOffOnline(itemId, text))
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
        label="Why it isn't going online"
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
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          disabled={pending}
          aria-busy={pending}
        >
          {pending ? 'Saving...' : "Don't list online"}
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
