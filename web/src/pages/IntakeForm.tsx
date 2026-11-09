import { useLayoutEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { ImagePlus } from 'lucide-react'

import type { ItemCardRequest, NewItem, StoreDepartment } from '@/api/appraisal'
import { cardSurface } from '@/components/site/card'
import {
  ErrorSummary,
  Field,
  RadioGroup,
  SubmitButton,
  TextInput,
  type FieldError,
} from '@/components/site/form'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import {
  CONDITIONS,
  DEPARTMENTS,
  FLAWS,
  MAX_PHOTO_MB,
  MAX_PHOTOS,
  PHOTO_ACCEPT,
  SIZE_TYPES,
  STORE_DEPARTMENTS,
  photoProblem,
  type Photo,
} from './intake'

// Everything staff give at intake: the item itself, then what goes on its card.
export type Intake = { item: NewItem; entries: ItemCardRequest }

type Condition = ItemCardRequest['condition']
type Flaw = ItemCardRequest['flaws'][number]
type Department = NonNullable<ItemCardRequest['department']>
type Answer = 'yes' | 'no' | 'unknown'

const TESTED = [
  ['yes', 'Yes, it works'],
  ['no', "No, it doesn't work"],
  ['unknown', 'Not tested'],
] as const satisfies readonly (readonly [Answer, string])[]
const BOXED = [
  ['yes', 'Yes'],
  ['no', 'No'],
  ['unknown', 'Not checked'],
] as const satisfies readonly (readonly [Answer, string])[]

const SELECT =
  'h-11 w-full min-w-0 rounded-md border-2 border-input bg-background px-2.5 text-foreground'
const AREA =
  'block min-h-11 w-full min-w-0 resize-y rounded-md border-2 border-input bg-background px-2.5 py-2 text-foreground'

const answer = (value: Answer) => (value === 'unknown' ? null : value === 'yes')
const optional = (value: string) => value.trim() || null

// The page holds the photos, because it shows them after intake and lets their previews go.
export function IntakeForm({
  focusPhotos = 0,
  retakes = [],
  busy,
  photos,
  onPhotosChange,
  onSubmit,
}: {
  // Each new number moves focus to the photo input, and 0 leaves focus where it is.
  focusPhotos?: number
  // The numbers, from 1, of the photos the check asked staff to take again.
  retakes?: number[]
  busy: boolean
  photos: Photo[]
  onPhotosChange: (photos: Photo[]) => void
  onSubmit: (intake: Intake) => void
}) {
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [storeDepartment, setStoreDepartment] = useState<StoreDepartment | null>(null)
  const [condition, setCondition] = useState<Condition | null>(null)
  const [flaws, setFlaws] = useState<Flaw[]>([])
  const [department, setDepartment] = useState<Department | null>(null)
  const [size, setSize] = useState('')
  const [sizeType, setSizeType] = useState('')
  const [tested, setTested] = useState<Answer>('unknown')
  const [boxed, setBoxed] = useState<Answer>('unknown')
  const [accessories, setAccessories] = useState('')
  const [notes, setNotes] = useState('')
  const [errors, setErrors] = useState<FieldError[]>([])
  const [attempt, setAttempt] = useState(0)
  const photoInput = useRef<HTMLInputElement>(null)

  useLayoutEffect(() => {
    if (focusPhotos > 0) photoInput.current?.focus()
  }, [focusPhotos])

  function addPhotos(event: ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(event.target.files ?? [])
    // Cleared, so choosing the same file again after removing it still counts as a change.
    event.target.value = ''
    if (chosen.length === 0) return
    const room = MAX_PHOTOS - photos.length
    const problem = chosen
      .slice(0, room)
      .map((file, index) => photoProblem(file, photos.length + index + 1))
      .find(Boolean)
    if (problem) {
      setPhotoError(problem)
      return
    }
    setPhotoError(
      chosen.length > room
        ? `Add at most ${MAX_PHOTOS} photos, so only the first ${room} were added.`
        : null,
    )
    onPhotosChange([
      ...photos,
      ...chosen.slice(0, room).map((file) => ({ file, url: URL.createObjectURL(file) })),
    ])
  }

  function removePhoto(index: number) {
    URL.revokeObjectURL(photos[index].url)
    onPhotosChange(photos.filter((_, other) => other !== index))
    setPhotoError(null)
  }

  function toggleFlaw(flaw: Flaw) {
    setFlaws(flaws.includes(flaw) ? flaws.filter((other) => other !== flaw) : [...flaws, flaw])
  }

  function errorFor(fieldId: string) {
    return errors.find((error) => error.fieldId === fieldId)?.message
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    const found: FieldError[] = []
    if (photos.length === 0)
      found.push({ fieldId: 'photos', message: 'Add at least one photo of the item.' })
    if (!storeDepartment) {
      found.push({ fieldId: 'store-department', message: 'Choose the department it came from.' })
    }
    if (!condition) found.push({ fieldId: 'condition', message: 'Choose its condition.' })
    setErrors(found)
    setAttempt(attempt + 1)
    if (!storeDepartment || !condition || found.length > 0) return
    const clothing = storeDepartment === 'clothing'
    onSubmit({
      item: { photos: photos.map((photo) => photo.file), storeDepartment, notes },
      entries: {
        condition,
        flaws,
        ...(clothing
          ? { department, size: optional(size), size_type: optional(sizeType) }
          : {
              tested_working: answer(tested),
              complete_in_box: answer(boxed),
              accessories_included: optional(accessories),
            }),
      },
    })
  }

  const photosFull = photos.length >= MAX_PHOTOS
  const photosError = photoError ?? errorFor('photos')

  return (
    // One card. On a wide screen the photos and notes sit beside the questions about the item, and
    // on a phone the groups stack in the order they're filled in. A line divides each group.
    <form onSubmit={submit} noValidate className={cn('mb-7', cardSurface)}>
      {errors.length > 0 && <ErrorSummary key={attempt} errors={errors} />}

      <div className="grid grid-cols-1 wide:grid-cols-2 wide:grid-rows-[auto_1fr] wide:[grid-template-areas:'photos_item'_'notes_item']">
        <div className="wide:pr-8 wide:[grid-area:photos]">
          {/* The error bar is on a wrapper for the same reason as in RadioGroup. */}
          <div className={photosError ? 'mb-6 border-l-4 border-destructive pl-3.5' : 'mb-6'}>
            <fieldset aria-describedby={`photos-hint${photosError ? ' photos-error' : ''}`}>
              <legend className="mb-1 font-bold">Photos</legend>
              <p id="photos-hint" className="mb-1.5 text-muted-foreground">
                Add 1 to {MAX_PHOTOS} photos. Each can be a JPEG, PNG or WebP image of up to{' '}
                {MAX_PHOTO_MB} MB.
              </p>
              {photosError && (
                <p
                  id="photos-error"
                  // A problem found as the photo is chosen is announced, and one from submitting is in the summary.
                  role={photoError ? 'alert' : undefined}
                  className="mb-1.5 font-bold text-destructive"
                >
                  {photosError}
                </p>
              )}
              {photos.length > 0 && (
                <ul className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {photos.map((photo, index) => (
                    <li key={photo.url} className="flex min-w-0 flex-col gap-2">
                      <div className="relative">
                        <img
                          src={photo.url}
                          alt={`Photo ${index + 1}`}
                          className={cn(
                            'aspect-square w-full bg-surface object-contain',
                            retakes.includes(index + 1)
                              ? 'border-4 border-warn'
                              : 'border border-rule',
                          )}
                        />
                        {/* On the photo rather than under it, so the Remove buttons stay in line. */}
                        {retakes.includes(index + 1) && (
                          <p className="absolute inset-x-0 bottom-0 bg-warn px-1.5 py-0.5 text-sm font-bold text-foreground">
                            <span className="sr-only">Photo {index + 1}: </span>
                            Take again
                          </p>
                        )}
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="lg"
                        disabled={busy}
                        aria-label={`Remove photo ${index + 1}`}
                        onClick={() => removePhoto(index)}
                      >
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {photosFull ? (
                <p>That's the most photos one item can have.</p>
              ) : (
                // An upload area rather than the browser's own file box, which reads like a text
                // field. The real input stays inside, out of sight, so it still opens the camera or
                // the photo library, and keyboard focus shows as a ring around the whole area.
                <label
                  htmlFor="photos"
                  className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-plain-line bg-surface px-4 py-7 text-center transition-colors hover:border-primary hover:bg-muted/40 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 has-[:focus-visible]:outline-4 has-[:focus-visible]:outline-ring has-[:focus-visible]:outline-solid"
                >
                  <ImagePlus aria-hidden="true" className="size-8 text-muted-foreground" />
                  <span className="font-bold text-link">
                    {photos.length === 0 ? 'Take or choose a photo' : 'Add another photo'}
                  </span>
                  <input
                    ref={photoInput}
                    id="photos"
                    type="file"
                    accept={PHOTO_ACCEPT}
                    multiple
                    disabled={busy}
                    onChange={addPhotos}
                    className="sr-only"
                  />
                </label>
              )}
            </fieldset>
          </div>
        </div>

        <div className="divide-y divide-rule border-t border-rule pt-6 wide:border-t-0 wide:border-l wide:pt-0 wide:pl-8 wide:[grid-area:item] [&>*+*]:pt-6">
          <div>
            <RadioGroup
              id="store-department"
              legend="Department it came from"
              options={STORE_DEPARTMENTS}
              value={storeDepartment}
              error={errorFor('store-department')}
              disabled={busy}
              onChange={setStoreDepartment}
            />

            <RadioGroup
              id="condition"
              legend="Condition"
              options={CONDITIONS}
              value={condition}
              error={errorFor('condition')}
              disabled={busy}
              onChange={setCondition}
            />

            <fieldset className="mb-6">
              <legend className="mb-1 font-bold">Flaws</legend>
              <p className="mb-1.5 text-muted-foreground">Tick any you can see, or none.</p>
              {FLAWS.map(([flaw, text]) => (
                <label key={flaw} className="flex min-h-11 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={flaws.includes(flaw)}
                    disabled={busy}
                    onChange={() => toggleFlaw(flaw)}
                    className="size-5 flex-none accent-primary"
                  />
                  {text}
                </label>
              ))}
            </fieldset>
          </div>

          {storeDepartment === 'clothing' && (
            <div>
              <RadioGroup
                id="department"
                legend="Who it's for (optional)"
                options={DEPARTMENTS}
                value={department}
                disabled={busy}
                onChange={setDepartment}
              />
              <Field
                id="size"
                label="Size (optional)"
                hint="As the tag shows it, such as M or 32x30."
              >
                {({ id, describedBy }) => (
                  <TextInput
                    id={id}
                    value={size}
                    disabled={busy}
                    aria-describedby={describedBy}
                    onChange={(event) => setSize(event.target.value)}
                  />
                )}
              </Field>
              <Field id="size-type" label="Size type (optional)">
                {({ id }) => (
                  <select
                    id={id}
                    value={sizeType}
                    disabled={busy}
                    onChange={(event) => setSizeType(event.target.value)}
                    className={SELECT}
                  >
                    <option value="">Not given</option>
                    {SIZE_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
          )}

          {storeDepartment === 'electronics_games' && (
            <div>
              <RadioGroup
                id="tested"
                legend="Tested and working"
                options={TESTED}
                value={tested}
                disabled={busy}
                onChange={setTested}
              />
              <RadioGroup
                id="boxed"
                legend="Complete in its box"
                options={BOXED}
                value={boxed}
                disabled={busy}
                onChange={setBoxed}
              />
              <Field
                id="accessories"
                label="Accessories included (optional)"
                hint="Such as a charger, cables or controllers."
              >
                {({ id, describedBy }) => (
                  <TextInput
                    id={id}
                    value={accessories}
                    disabled={busy}
                    aria-describedby={describedBy}
                    onChange={(event) => setAccessories(event.target.value)}
                  />
                )}
              </Field>
            </div>
          )}
        </div>

        <div className="border-t border-rule pt-6 wide:pr-8 wide:[grid-area:notes]">
          <Field id="notes" label="Notes (optional)" hint="Anything the photos don't show.">
            {({ id, describedBy }) => (
              <textarea
                id={id}
                value={notes}
                rows={3}
                maxLength={1000}
                disabled={busy}
                aria-describedby={describedBy}
                onChange={(event) => setNotes(event.target.value)}
                className={AREA}
              />
            )}
          </Field>
        </div>
      </div>

      <div className="border-t border-rule pt-6">
        <SubmitButton pending={busy}>Take it in</SubmitButton>
      </div>
    </form>
  )
}
