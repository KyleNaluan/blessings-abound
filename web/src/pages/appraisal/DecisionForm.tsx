import { useState, type FormEvent } from 'react'

import type {
  DecisionChoice,
  Destination,
  Override,
  OverrideReason,
  Recommendation,
  Rejection,
} from '@/api/appraisal'
import { Field, RadioGroup, SubmitButton, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import { DESTINATIONS, goesAgainst, OVERRIDE_REASON_LABELS, OVERRIDE_REASONS } from '../intake'

const REASON_MAX = 200
const NOTE_MAX = 500

const SELECT =
  'h-11 w-full min-w-0 rounded-none border-2 border-input bg-background px-2.5 text-foreground'
const AREA =
  'block min-h-11 w-full min-w-0 resize-y rounded-none border-2 border-input bg-background px-2.5 py-2 text-foreground'

export type DecisionDetails = { rejection?: Rejection; override?: Override }

// What a call needs before it saves: why staff disagree, when they do, and where a rejected item goes.
export function DecisionForm({
  decision,
  recommendation,
  busy,
  error,
  onSave,
  onBack,
}: {
  decision: DecisionChoice
  recommendation: Recommendation
  busy: boolean
  error?: string
  onSave: (details: DecisionDetails) => void
  onBack: () => void
}) {
  const against = goesAgainst(recommendation, decision)
  const rejecting = decision === 'no'
  const [override, setOverride] = useState<OverrideReason | ''>('')
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [destination, setDestination] = useState<Destination | null>(null)
  const [errors, setErrors] = useState<Record<string, string | undefined>>({})
  const other = override === 'other'

  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const found = {
      override: against && !override ? 'Choose why you disagree.' : undefined,
      note: against && other && !note.trim() ? 'Add a note to say what the reason is.' : undefined,
      reason:
        rejecting && !against && !reason.trim() ? "Say why it isn't being listed." : undefined,
      destination: rejecting && !destination ? 'Choose where the item goes instead.' : undefined,
    }
    setErrors(found)
    if (Object.values(found).some(Boolean)) return
    const chosen = override ? { reason: override, note } : undefined
    onSave({
      override: chosen,
      rejection:
        rejecting && destination
          ? {
              // The triage log keeps a reason in words, so a disagreement gives its own.
              reason: chosen
                ? other
                  ? note.trim()
                  : OVERRIDE_REASON_LABELS[chosen.reason]
                : reason.trim(),
              destination,
            }
          : undefined,
    })
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="decision-form-heading">
      <h3 id="decision-form-heading" className="mb-3 text-lg font-bold">
        {rejecting ? 'Not listing it' : 'Listing it'}
      </h3>
      {error && (
        <p role="alert" className="mb-4 border-l-4 border-destructive pl-3.5 font-bold">
          {error}
        </p>
      )}
      {against && (
        <>
          <Field
            id="override-reason"
            label="Why you disagree"
            hint={
              recommendation === 'yes'
                ? 'The price says it is worth listing.'
                : "The price says it isn't worth listing."
            }
            error={errors.override}
          >
            {({ id, describedBy }) => (
              <select
                id={id}
                value={override}
                disabled={busy}
                aria-describedby={describedBy}
                onChange={(event) => setOverride(event.target.value as OverrideReason)}
                className={SELECT}
              >
                <option value="">Choose a reason</option>
                {OVERRIDE_REASONS[decision].map((value) => (
                  <option key={value} value={value}>
                    {OVERRIDE_REASON_LABELS[value]}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            id="override-note"
            label={other ? 'Note' : 'Note (optional)'}
            hint={other ? 'Say what the reason is.' : 'Anything the next person should know.'}
            error={errors.note}
          >
            {({ id, describedBy }) => (
              <textarea
                id={id}
                value={note}
                rows={2}
                maxLength={NOTE_MAX}
                disabled={busy}
                aria-describedby={describedBy}
                onChange={(event) => setNote(event.target.value)}
                className={AREA}
              />
            )}
          </Field>
        </>
      )}
      {rejecting && !against && (
        <Field
          id="rejection-reason"
          label="Why it isn't being listed"
          hint="Such as too worn, or worth too little online."
          error={errors.reason}
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
      )}
      {rejecting && (
        <RadioGroup
          id="destination"
          legend="Where it goes instead"
          options={DESTINATIONS}
          value={destination}
          error={errors.destination}
          disabled={busy}
          onChange={setDestination}
        />
      )}
      <div className="flex flex-wrap gap-3">
        <SubmitButton pending={busy}>{rejecting ? 'Save the no' : 'Save the yes'}</SubmitButton>
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
