import { Fragment, useState, type FormEvent } from 'react'

import type { ItemCard, ItemCardEdit } from '@/api/appraisal'
import { Field, SubmitButton, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import { CONDITIONS, label } from '../intake'

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

const SELECT =
  'h-11 w-full min-w-0 rounded-none border-2 border-input bg-background px-2.5 text-foreground'

export function CardForm({
  card,
  busy,
  onConfirm,
  onCancel,
}: {
  card: ItemCard
  busy: boolean
  onConfirm: (edit: ItemCardEdit) => void
  // Only an edit after the price has a way back, because a new card needs confirming first.
  onCancel?: () => void
}) {
  const [category, setCategory] = useState(card.category)
  const [condition, setCondition] = useState(card.condition)
  const [searchQuery, setSearchQuery] = useState(card.search_query)
  const [text, setText] = useState(() =>
    Object.fromEntries(TEXT_FIELDS.map(([name]) => [name, card[name] ?? ''])),
  )
  const searchMissing = !searchQuery.trim()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (searchMissing || busy) return
    onConfirm({ ...text, category, condition, search_query: searchQuery })
  }

  return (
    <form onSubmit={submit} noValidate>
      {card.needs_confirmation && (
        <p className="mb-6 border-l-4 border-destructive pl-3.5 font-bold">
          The model isn't sure about this item. Check the brand and exact model before we search.
        </p>
      )}
      <p className="mb-6">
        The model's confidence: <b>{CONFIDENCE_LABELS[card.model_confidence]}</b>
      </p>
      <Field id="card-category" label="Category">
        {({ id }) => (
          <select
            id={id}
            value={category}
            disabled={busy}
            onChange={(event) => setCategory(event.target.value as ItemCard['category'])}
            className={SELECT}
          >
            {Object.entries(CATEGORY_LABELS).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Field id="card-condition" label="Condition">
        {({ id }) => (
          <select
            id={id}
            value={condition}
            disabled={busy}
            onChange={(event) => setCondition(event.target.value as ItemCard['condition'])}
            className={SELECT}
          >
            {CONDITIONS.map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        )}
      </Field>
      {TEXT_FIELDS.map(([name, fieldLabel]) => (
        <Field key={name} id={`card-${name}`} label={fieldLabel}>
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
      <div className="flex flex-wrap gap-3">
        <SubmitButton pending={busy}>Confirm and get the price</SubmitButton>
        {onCancel && (
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="max-sm:w-full"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}

export function CardDetails({ card }: { card: ItemCard }) {
  return (
    <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
      <dt className="font-bold">Category</dt>
      <dd>{CATEGORY_LABELS[card.category]}</dd>
      <dt className="font-bold">Condition</dt>
      <dd>{label(CONDITIONS, card.condition)}</dd>
      {TEXT_FIELDS.map(([name, fieldLabel]) =>
        card[name] ? (
          <Fragment key={name}>
            <dt className="font-bold">{fieldLabel}</dt>
            <dd className="min-w-0 break-words">{card[name]}</dd>
          </Fragment>
        ) : null,
      )}
      <dt className="font-bold">Search</dt>
      <dd className="min-w-0 break-words">{card.search_query}</dd>
    </dl>
  )
}
