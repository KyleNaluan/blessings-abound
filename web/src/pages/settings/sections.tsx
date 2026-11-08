import { useState, type ReactNode } from 'react'

import {
  saveAskToSale,
  saveBoxSizes,
  saveChannelBFees,
  saveFees,
  saveSeasonalCalendar,
  saveShippingWeight,
  saveWorthListing,
  type BoxSize,
  type Season,
  type SettingsPage,
} from '@/api/settings'
import { Field, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import { SectionFrame } from './frame'
import {
  dollars,
  parseDollars,
  parseNumber,
  parseNumberList,
  parsePercent,
  parseWholeNumber,
  percent,
  words,
} from './numbers'
import { useSave } from './useSave'

// One form per section, each saved on its own. The API checks every value again and says what is wrong.

export type SectionProps<K extends keyof SettingsPage> = {
  read: SettingsPage[K]
  saved: boolean
  onSaved: (page: SettingsPage) => void
  onReload: () => void
}

type Errors = Record<string, string>

// Collects the field errors found while reading a form, so they show on the fields and in the section's summary.
function reader() {
  const errors: Errors = {}
  return {
    errors,
    read<T>(id: string, value: T | null, message: string): T {
      if (value === null) errors[id] = message
      return value as T
    },
  }
}

const SELECT =
  'h-11 w-full min-w-0 rounded-md border-2 border-input bg-background px-2.5 text-foreground'
const WORDS =
  'block min-h-11 w-full min-w-0 resize-y rounded-md border-2 border-input bg-background px-2.5 py-2 text-foreground field-sizing-content'

function TextField({
  id,
  label,
  hint,
  value,
  error,
  disabled,
  inputMode = 'decimal',
  onChange,
}: {
  id: string
  label: string
  hint?: string
  value: string
  error?: string
  disabled: boolean
  inputMode?: 'decimal' | 'numeric' | 'text'
  onChange: (value: string) => void
}) {
  return (
    <Field id={id} label={label} hint={hint} error={error}>
      {({ id, describedBy, invalid }) => (
        <TextInput
          id={id}
          value={value}
          disabled={disabled}
          invalid={invalid}
          inputMode={inputMode}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </Field>
  )
}

export function WorthListingSection({
  read,
  saved,
  onSaved,
  onReload,
}: SectionProps<'worth_listing'>) {
  const { status, save, fail } = useSave(onSaved)
  const [threshold, setThreshold] = useState(dollars(read.value.threshold_cents))
  const [errors, setErrors] = useState<Errors>({})

  function submit() {
    const form = reader()
    const cents = form.read(
      'worth-threshold',
      parseDollars(threshold),
      'Enter the worth-listing price in dollars, such as 30.00.',
    )
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveWorthListing({ threshold_cents: cents }, read.updated_at))
  }

  return (
    <SectionFrame
      id="worth"
      title="Worth listing"
      description="An item is worth listing when its typical sale price is at least this much. The net after fees is shown beside it."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the worth-listing price"
      onSubmit={submit}
      onReload={onReload}
    >
      <TextField
        id="worth-threshold"
        label="Worth-listing price"
        hint="In dollars."
        value={threshold}
        error={errors['worth-threshold']}
        disabled={status.kind === 'saving'}
        onChange={setThreshold}
      />
    </SectionFrame>
  )
}

export function FeesSection({ read, saved, onSaved, onReload }: SectionProps<'fees'>) {
  const { status, save, fail } = useSave(onSaved)
  const [rate, setRate] = useState(percent(read.value.fee_rate))
  const [perOrder, setPerOrder] = useState(dollars(read.value.per_order_fee_cents))
  const [supplies, setSupplies] = useState(dollars(read.value.supplies_cents))
  const [errors, setErrors] = useState<Errors>({})

  function submit() {
    const form = reader()
    const value = {
      fee_rate: form.read(
        'fees-rate',
        parsePercent(rate),
        'Enter the fee rate as a percent, such as 13.6.',
      ),
      per_order_fee_cents: form.read(
        'fees-per-order',
        parseDollars(perOrder),
        'Enter the per-order fee in dollars, such as 0.40.',
      ),
      supplies_cents: form.read(
        'fees-supplies',
        parseDollars(supplies),
        'Enter the supplies cost in dollars, such as 1.50.',
      ),
    }
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveFees(value, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="fees"
      title="Channel A fees"
      description="What a sale on Channel A costs, which the worth-listing net after fees takes off the typical sale price."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the Channel A fees"
      onSubmit={submit}
      onReload={onReload}
    >
      <TextField
        id="fees-rate"
        label="Fee rate"
        hint="A percent of the sale price, including shipping and tax."
        value={rate}
        error={errors['fees-rate']}
        disabled={busy}
        onChange={setRate}
      />
      <TextField
        id="fees-per-order"
        label="Per-order fee"
        hint="In dollars, charged once on every sale."
        value={perOrder}
        error={errors['fees-per-order']}
        disabled={busy}
        onChange={setPerOrder}
      />
      <TextField
        id="fees-supplies"
        label="Supplies"
        hint="In dollars, the mailer or box and the tape for one sale."
        value={supplies}
        error={errors['fees-supplies']}
        disabled={busy}
        onChange={setSupplies}
      />
    </SectionFrame>
  )
}

export function ChannelBFeesSection({
  read,
  saved,
  onSaved,
  onReload,
}: SectionProps<'channel_b_fees'>) {
  const { status, save, fail } = useSave(onSaved)
  const [rate, setRate] = useState(percent(read.value.fee_rate))
  const [smallFee, setSmallFee] = useState(dollars(read.value.small_sale_fee_cents))
  const [smallBelow, setSmallBelow] = useState(dollars(read.value.small_sale_below_cents))
  const [supplies, setSupplies] = useState(dollars(read.value.supplies_cents))
  const [errors, setErrors] = useState<Errors>({})

  function submit() {
    const form = reader()
    const value = {
      fee_rate: form.read(
        'channel-b-rate',
        parsePercent(rate),
        'Enter the fee rate as a percent, such as 20.',
      ),
      small_sale_fee_cents: form.read(
        'channel-b-small-fee',
        parseDollars(smallFee),
        'Enter the flat fee in dollars, such as 2.95.',
      ),
      small_sale_below_cents: form.read(
        'channel-b-small-below',
        parseDollars(smallBelow),
        'Enter the small sale price in dollars, such as 15.00.',
      ),
      supplies_cents: form.read(
        'channel-b-supplies',
        parseDollars(supplies),
        'Enter the supplies cost in dollars, such as 1.50.',
      ),
    }
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveChannelBFees(value, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="channel-b"
      title="Channel B fees"
      description="What a sale on Channel B costs, which the approval page takes off each Channel B price. The buyer pays for the shipping label."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the Channel B fees"
      onSubmit={submit}
      onReload={onReload}
    >
      <TextField
        id="channel-b-rate"
        label="Fee rate"
        hint="A percent of the sale price, charged when the sale is at least the small sale price."
        value={rate}
        error={errors['channel-b-rate']}
        disabled={busy}
        onChange={setRate}
      />
      <TextField
        id="channel-b-small-fee"
        label="Flat fee on a small sale"
        hint="In dollars, charged instead of the fee rate."
        value={smallFee}
        error={errors['channel-b-small-fee']}
        disabled={busy}
        onChange={setSmallFee}
      />
      <TextField
        id="channel-b-small-below"
        label="Small sale price"
        hint="In dollars. A sale under this pays the flat fee."
        value={smallBelow}
        error={errors['channel-b-small-below']}
        disabled={busy}
        onChange={setSmallBelow}
      />
      <TextField
        id="channel-b-supplies"
        label="Supplies"
        hint="In dollars, the mailer or box and the tape for one sale."
        value={supplies}
        error={errors['channel-b-supplies']}
        disabled={busy}
        onChange={setSupplies}
      />
    </SectionFrame>
  )
}

export function AskToSaleSection({ read, saved, onSaved, onReload }: SectionProps<'ask_to_sale'>) {
  const { status, save, fail } = useSave(onSaved)
  const [apparel, setApparel] = useState(String(read.value.apparel))
  const [games, setGames] = useState(String(read.value.electronics_games))
  const [errors, setErrors] = useState<Errors>({})

  function submit() {
    const form = reader()
    const message = 'Enter the factor as a number, such as 0.645.'
    const value = {
      apparel: form.read('ask-apparel', parseNumber(apparel), `Apparel: ${message}`),
      electronics_games: form.read(
        'ask-games',
        parseNumber(games),
        `Electronics and games: ${message}`,
      ),
    }
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveAskToSale(value, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="ask"
      title="Ask-to-sale factor"
      description="Listings show asking prices, and items sell for less. The price range is the asking prices times this factor."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the factors"
      onSubmit={submit}
      onReload={onReload}
    >
      <TextField
        id="ask-apparel"
        label="Apparel"
        hint="0.645 means an item asking $100 is expected to sell for $64.50."
        value={apparel}
        error={errors['ask-apparel']}
        disabled={busy}
        onChange={setApparel}
      />
      <TextField
        id="ask-games"
        label="Electronics and games"
        value={games}
        error={errors['ask-games']}
        disabled={busy}
        onChange={setGames}
      />
    </SectionFrame>
  )
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]
const CATEGORY_LABELS = { apparel: 'Apparel', electronics_games: 'Electronics and games' }

type SeasonDraft = {
  key: number
  name: string
  category: Season['category']
  words: string
  months: number[]
}

// The fieldset's legend names the row for screen readers, and the visible heading sits beside its Remove button.
function RowHeading({
  children,
  onRemove,
  removeLabel,
  disabled,
}: {
  children: ReactNode
  onRemove: () => void
  removeLabel: string
  disabled: boolean
}) {
  return (
    <>
      <legend className="sr-only">{children}</legend>
      <div className="mb-4 flex items-center justify-between gap-3">
        <p aria-hidden="true" className="text-lg font-bold">
          {children}
        </p>
        <Button
          type="button"
          variant="outline"
          size="lg"
          disabled={disabled}
          aria-label={removeLabel}
          onClick={onRemove}
        >
          Remove
        </Button>
      </div>
    </>
  )
}

export function SeasonalCalendarSection({
  read,
  saved,
  onSaved,
  onReload,
}: SectionProps<'seasonal_calendar'>) {
  const { status, save, fail } = useSave(onSaved)
  const [nextKey, setNextKey] = useState(read.value.seasons.length)
  const [seasons, setSeasons] = useState<SeasonDraft[]>(() =>
    read.value.seasons.map((season, key) => ({
      key,
      name: season.name,
      category: season.category,
      words: season.match_words.join(', '),
      months: season.months,
    })),
  )

  function change(key: number, update: Partial<SeasonDraft>) {
    setSeasons(seasons.map((season) => (season.key === key ? { ...season, ...update } : season)))
  }

  function toggle(season: SeasonDraft, month: number) {
    const months = season.months.includes(month)
      ? season.months.filter((each) => each !== month)
      : [...season.months, month].sort((a, b) => a - b)
    change(season.key, { months })
  }

  function add() {
    setSeasons([...seasons, { key: nextKey, name: '', category: 'apparel', words: '', months: [] }])
    setNextKey(nextKey + 1)
  }

  function submit() {
    const value = {
      seasons: seasons.map((season) => ({
        name: season.name,
        category: season.category,
        match_words: words(season.words),
        months: season.months,
      })),
    }
    if (!value.seasons.length)
      return fail(['Keep at least one season, or the calendar holds nothing.'])
    void save(() => saveSeasonalCalendar(value, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="seasons"
      title="Seasonal calendar"
      description={
        <>
          The months an item of each kind is worth listing in, with the rest of the year held for
          its season. An item matches a season when its card has one of the words. The first season
          that matches is the one used, and an item that matches none can be listed in any month.
        </>
      }
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the calendar"
      onSubmit={submit}
      onReload={onReload}
    >
      {seasons.map((season, index) => (
        <fieldset key={season.key} className="mb-5 border-t border-rule pt-4">
          <RowHeading
            removeLabel={`Remove season ${index + 1}${season.name ? `, ${season.name}` : ''}`}
            disabled={busy}
            onRemove={() => setSeasons(seasons.filter((each) => each.key !== season.key))}
          >
            Season {index + 1}
          </RowHeading>
          <TextField
            id={`season-${season.key}-name`}
            label="Name"
            value={season.name}
            disabled={busy}
            inputMode="text"
            onChange={(name) => change(season.key, { name })}
          />
          <Field id={`season-${season.key}-category`} label="Category">
            {({ id }) => (
              <select
                id={id}
                value={season.category}
                disabled={busy}
                onChange={(event) =>
                  change(season.key, { category: event.target.value as Season['category'] })
                }
                className={SELECT}
              >
                {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            id={`season-${season.key}-words`}
            label="Words to match"
            hint="Separated by commas, such as coat, parka."
          >
            {({ id, describedBy }) => (
              // A text area, so a long list wraps and shows every word on a phone.
              <textarea
                id={id}
                rows={2}
                value={season.words}
                disabled={busy}
                aria-describedby={describedBy}
                onChange={(event) => change(season.key, { words: event.target.value })}
                className={WORDS}
              />
            )}
          </Field>
          <fieldset className="mb-2">
            <legend className="mb-1.5 font-bold">Months to list in</legend>
            <div className="grid grid-cols-4 gap-x-3 gap-y-2 sm:grid-cols-6">
              {MONTHS.map((label, monthIndex) => {
                const month = monthIndex + 1
                return (
                  <label key={label} className="flex min-h-11 cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      className="size-5 accent-primary"
                      checked={season.months.includes(month)}
                      disabled={busy}
                      aria-label={MONTH_NAMES[monthIndex]}
                      onChange={() => toggle(season, month)}
                    />
                    <span aria-hidden="true">{label}</span>
                  </label>
                )
              })}
            </div>
          </fieldset>
        </fieldset>
      ))}
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="mb-6 max-sm:w-full"
        disabled={busy}
        onClick={add}
      >
        Add a season
      </Button>
    </SectionFrame>
  )
}

type BoxDraft = {
  key: number
  kind: BoxSize['kind']
  length: string
  width: string
  height: string
}

const side = (inches: number | null | undefined) => (inches == null ? '' : String(inches))

export function BoxSizesSection({ read, saved, onSaved, onReload }: SectionProps<'box_sizes'>) {
  const { status, save, fail } = useSave(onSaved)
  const [nextKey, setNextKey] = useState(read.value.boxes.length)
  const [boxes, setBoxes] = useState<BoxDraft[]>(() =>
    read.value.boxes.map((box, key) => ({
      key,
      kind: box.kind,
      length: side(box.length_in),
      width: side(box.width_in),
      height: side(box.height_in),
    })),
  )
  const [errors, setErrors] = useState<Errors>({})

  function change(key: number, update: Partial<BoxDraft>) {
    setBoxes(boxes.map((box) => (box.key === key ? { ...box, ...update } : box)))
  }

  function add() {
    setBoxes([...boxes, { key: nextKey, kind: 'box', length: '', width: '', height: '' }])
    setNextKey(nextKey + 1)
  }

  function submit() {
    const form = reader()
    const value = {
      boxes: boxes.map((box, index) => {
        const message = (name: string) =>
          `Size ${index + 1}: enter the ${name} in inches, such as 12 or 15.5.`
        const id = `box-${box.key}`
        return {
          kind: box.kind,
          length_in: form.read(`${id}-length`, parseNumber(box.length), message('length')),
          width_in: form.read(`${id}-width`, parseNumber(box.width), message('width')),
          height_in:
            box.kind === 'mailer'
              ? null
              : form.read(`${id}-height`, parseNumber(box.height), message('height')),
        }
      }),
    }
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveBoxSizes(value, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="boxes"
      title="Box sizes"
      description="The sizes staff choose from when they pack an item. A box is written length by width by height, and a flat mailer width by length."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the box sizes"
      onSubmit={submit}
      onReload={onReload}
    >
      {boxes.map((box, index) => {
        const id = `box-${box.key}`
        const mailer = box.kind === 'mailer'
        return (
          <fieldset key={box.key} className="mb-5 border-t border-rule pt-4">
            <RowHeading
              removeLabel={`Remove size ${index + 1}`}
              disabled={busy}
              onRemove={() => setBoxes(boxes.filter((each) => each.key !== box.key))}
            >
              Size {index + 1}
            </RowHeading>
            <Field id={`${id}-kind`} label="Kind">
              {({ id: kindId }) => (
                <select
                  id={kindId}
                  value={box.kind}
                  disabled={busy}
                  onChange={(event) => {
                    const kind = event.target.value as BoxSize['kind']
                    change(box.key, { kind, height: kind === 'mailer' ? '' : box.height })
                  }}
                  className={SELECT}
                >
                  <option value="box">Box</option>
                  <option value="mailer">Mailer</option>
                </select>
              )}
            </Field>
            <div className="grid grid-cols-3 gap-3">
              {(mailer
                ? [
                    ['width', 'Width'],
                    ['length', 'Length'],
                  ]
                : [
                    ['length', 'Length'],
                    ['width', 'Width'],
                    ['height', 'Height'],
                  ]
              ).map(([name, label]) => (
                <TextField
                  key={name}
                  id={`${id}-${name}`}
                  label={`${label} (in)`}
                  value={box[name as 'length' | 'width' | 'height']}
                  error={errors[`${id}-${name}`] ? 'Enter inches.' : undefined}
                  disabled={busy}
                  onChange={(text) => change(box.key, { [name]: text })}
                />
              ))}
            </div>
          </fieldset>
        )
      })}
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="mb-6 max-sm:w-full"
        disabled={busy}
        onClick={add}
      >
        Add a size
      </Button>
    </SectionFrame>
  )
}

export function ShippingWeightSection({
  read,
  saved,
  onSaved,
  onReload,
}: SectionProps<'shipping_weight'>) {
  const { status, save, fail } = useSave(onSaved)
  const value = read.value
  const [tiers, setTiers] = useState(value.ounce_tiers_oz.join(', '))
  const [maxWeight, setMaxWeight] = useState(String(value.max_weight_oz))
  const [maxGirth, setMaxGirth] = useState(String(value.max_length_plus_girth_in))
  const [dimFrom, setDimFrom] = useState(String(value.dim_weight_min_cubic_in))
  const [divisor, setDivisor] = useState(String(value.dim_weight_divisor))
  const [errors, setErrors] = useState<Errors>({})

  function submit() {
    const form = reader()
    const next = {
      ounce_tiers_oz: form.read(
        'ship-tiers',
        parseNumberList(tiers),
        'Enter the ounce tiers as numbers separated by commas, such as 4, 8, 12, 15.999.',
      ),
      max_weight_oz: form.read(
        'ship-max-weight',
        parseWholeNumber(maxWeight),
        'Enter the weight limit in whole ounces.',
      ),
      max_length_plus_girth_in: form.read(
        'ship-max-girth',
        parseNumber(maxGirth),
        'Enter the length plus girth limit in inches.',
      ),
      dim_weight_min_cubic_in: form.read(
        'ship-dim-from',
        parseWholeNumber(dimFrom),
        'Enter the size-based weight starting volume in whole cubic inches.',
      ),
      dim_weight_divisor: form.read(
        'ship-divisor',
        parseWholeNumber(divisor),
        'Enter the divisor as a whole number.',
      ),
    }
    setErrors(form.errors)
    if (Object.keys(form.errors).length) return fail(Object.values(form.errors))
    void save(() => saveShippingWeight(next, read.updated_at))
  }

  const busy = status.kind === 'saving'
  return (
    <SectionFrame
      id="shipping"
      title="Shipping weight rules"
      description="USPS Ground Advantage's rules, which a package's weight and size are checked against."
      read={read}
      status={status}
      saved={saved}
      saveLabel="Save the shipping rules"
      onSubmit={submit}
      onReload={onReload}
    >
      <TextField
        id="ship-tiers"
        label="Ounce tiers (oz)"
        hint="A weight rounds up to the next tier, and past the last one to the next pound."
        value={tiers}
        error={errors['ship-tiers']}
        disabled={busy}
        inputMode="text"
        onChange={setTiers}
      />
      <TextField
        id="ship-max-weight"
        label="Weight limit (oz)"
        hint="1120 oz is 70 lb."
        value={maxWeight}
        error={errors['ship-max-weight']}
        disabled={busy}
        inputMode="numeric"
        onChange={setMaxWeight}
      />
      <TextField
        id="ship-max-girth"
        label="Length plus girth limit (in)"
        hint="The longest side plus the distance around the other two. Every box size has to fit under it."
        value={maxGirth}
        error={errors['ship-max-girth']}
        disabled={busy}
        onChange={setMaxGirth}
      />
      <TextField
        id="ship-dim-from"
        label="Size-based weight starts above (cubic in)"
        hint="1728 cubic inches is 1 cubic foot."
        value={dimFrom}
        error={errors['ship-dim-from']}
        disabled={busy}
        inputMode="numeric"
        onChange={setDimFrom}
      />
      <TextField
        id="ship-divisor"
        label="Size-based weight divisor"
        hint="Length times width times height, divided by this, gives the weight in pounds."
        value={divisor}
        error={errors['ship-divisor']}
        disabled={busy}
        inputMode="numeric"
        onChange={setDivisor}
      />
    </SectionFrame>
  )
}
