import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import {
  confirmItemCard,
  createAppraisal,
  createItemCard,
  listRecentDecisions,
  RepeatPhotoError,
  RetakePhotosError,
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
  type RetakePhoto,
} from '@/api/appraisal'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { money, when } from '@/pages/approval/format'

import { CardDetails, CardForm } from './appraisal/CardPanel'
import { DecisionForm, type DecisionDetails } from './appraisal/DecisionForm'
import { Panel } from './appraisal/parts'
import { PricePanel } from './appraisal/PricePanel'
import { RepeatWarning, RetakePrompt } from './appraisal/prompts'
import { ChannelChoice } from './ChannelChoice'
import {
  DESTINATIONS,
  goesAgainst,
  label,
  STORE_DEPARTMENTS,
  WHERE_IT_GOES,
  type Photo,
} from './intake'
import { IntakeForm, type Intake } from './IntakeForm'
import { ListingDrafts } from './ListingDrafts'

// The steps so far for one item. A step that fails can be tried again without repeating the ones before it.
type Progress = {
  intake: Intake
  // Staff saw the prompt to take a photo again and kept the photos as they are.
  keepPhotos: boolean
  // Staff saw that a photo matches a rejected item and chose to take it in anyway.
  allowRepeat: boolean
  item?: Item
  card?: ItemCard
  appraisal?: Appraisal
}

type Status =
  | { step: 'idle' }
  | { step: 'working'; label: string }
  | { step: 'retake'; photos: RetakePhoto[] }
  | { step: 'repeat'; matches: RejectedMatch[] }
  | { step: 'checking' }
  | { step: 'failed'; message: string }
  | { step: 'ready' }
  // A no, or a call against the recommendation, which needs more before it saves.
  | { step: 'explaining'; decision: DecisionChoice; error?: string }
  | { step: 'deciding'; decision: DecisionChoice; explained: boolean }
  | { step: 'saved'; decision: DecisionChoice; destination?: Destination }

// The one screen staff use for an item: intake, the card, the price with its evidence, and the call.
export function AppraisalPage() {
  usePageTitle('Appraise an item')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [status, setStatus] = useState<Status>({ step: 'idle' })
  const [editingCard, setEditingCard] = useState(false)
  const [recent, setRecent] = useState<RecentDecision[] | null>(null)
  const [recentError, setRecentError] = useState<string | null>(null)
  const [channels, setChannels] = useState<Channel[] | null>(null)
  const [listingSent, setListingSent] = useState(false)
  // A new key clears the intake form when staff start over.
  const [formKey, setFormKey] = useState(0)
  // A new number puts focus back on the photo input, after starting over or to retake a photo.
  const [photoFocus, setPhotoFocus] = useState(0)
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
        next.item = await takeItemIn(next.intake.item, next)
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
      if (error instanceof RetakePhotosError) setStatus({ step: 'retake', photos: error.photos })
      else if (error instanceof RepeatPhotoError) {
        setStatus({ step: 'repeat', matches: error.matches })
      } else setStatus({ step: 'failed', message: (error as Error).message })
    }
  }

  function takeIn(intake: Intake) {
    const start = { intake, keepPhotos: false, allowRepeat: false }
    setProgress(start)
    void run(start)
  }

  function goOn(choice: 'keepPhotos' | 'allowRepeat') {
    if (!progress) return
    const next = { ...progress, [choice]: true }
    setProgress(next)
    void run(next)
  }

  // The photos changed, so a question about the old ones no longer applies.
  function changePhotos(next: Photo[]) {
    setPhotos(next)
    if (status.step === 'retake' || status.step === 'repeat') {
      setProgress(null)
      setStatus({ step: 'idle' })
    }
  }

  // Takes the flagged photos out of the form, so staff can add new ones in their place.
  function retake(flagged: RetakePhoto[]) {
    const out = new Set(flagged.map((photo) => photo.number - 1))
    photos.forEach((photo, index) => out.has(index) && URL.revokeObjectURL(photo.url))
    setPhotos(photos.filter((_, index) => !out.has(index)))
    setProgress(null)
    setStatus({ step: 'idle' })
    setPhotoFocus(photoFocus + 1)
  }

  async function confirmCard(edit: ItemCardEdit) {
    if (!progress?.item) return
    setStatus({ step: 'working', label: 'Saving the card' })
    try {
      const card = await confirmItemCard(progress.item.id, edit)
      // A changed card needs a new price, so the old one goes.
      const next = { ...progress, card, appraisal: undefined }
      setProgress(next)
      setEditingCard(false)
      await run(next)
    } catch (error) {
      setStatus({ step: 'failed', message: (error as Error).message })
    }
  }

  function choose(decision: DecisionChoice) {
    if (!progress?.appraisal) return
    if (decision === 'no' || goesAgainst(progress.appraisal.recommendation, decision)) {
      setStatus({ step: 'explaining', decision })
    } else void decide(decision, {}, false)
  }

  async function decide(decision: DecisionChoice, details: DecisionDetails, explained: boolean) {
    if (!progress?.item || !progress.appraisal) return
    setStatus({ step: 'deciding', decision, explained })
    try {
      await saveDecision(progress.item.id, progress.appraisal.id, decision, details)
      setStatus({ step: 'saved', decision, destination: details.rejection?.destination })
      await loadRecent()
    } catch (error) {
      const message = (error as Error).message
      // A call that didn't save stays in its form, so what staff entered isn't lost.
      setStatus(
        explained ? { step: 'explaining', decision, error: message } : { step: 'failed', message },
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
    setEditingCard(false)
    setChannels(null)
    setListingSent(false)
    setFormKey(formKey + 1)
    setPhotoFocus(photoFocus + 1)
    photos.forEach((photo) => URL.revokeObjectURL(photo.url))
    setPhotos([])
  }

  const busy = status.step === 'working' || status.step === 'deciding'
  const { item, card, appraisal } = progress ?? {}
  const explaining =
    status.step === 'explaining' || (status.step === 'deciding' && status.explained)
      ? status.decision
      : null
  const canEdit = !!appraisal && !editingCard && status.step === 'ready'

  const working = (
    <div aria-live="polite">
      {status.step === 'working' && <p className="mb-7 font-bold">{status.label}...</p>}
    </div>
  )

  const failure = status.step === 'failed' && (
    <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
      <p className="mb-3 font-bold">{status.message}</p>
      <div className="flex flex-wrap gap-3">
        {progress && (
          <Button variant="outline" size="lg" className="max-sm:w-full" onClick={retry}>
            Try again
          </Button>
        )}
        <Button variant="outline" size="lg" className="max-sm:w-full" onClick={startOver}>
          Start over
        </Button>
      </div>
    </div>
  )

  return (
    <AuthLayout wide end={<SignOutButton />}>
      <div className="max-w-[30rem]">
        <p className="mb-4">
          <Link to="/app">Back to home</Link>
        </p>
        <PageHeading>Appraise an item</PageHeading>
        <Lead>Take the item in with its photos, check the card and the price, then decide.</Lead>
      </div>

      {!item && (
        <div className="max-w-[30rem]">
          <IntakeForm
            key={formKey}
            focusPhotos={photoFocus}
            retakes={status.step === 'retake' ? status.photos.map((photo) => photo.number) : []}
            busy={busy}
            photos={photos}
            onPhotosChange={changePhotos}
            onSubmit={takeIn}
          />
          {working}
          {status.step === 'retake' && (
            <RetakePrompt
              photos={status.photos}
              onRetake={() => retake(status.photos)}
              onKeep={() => goOn('keepPhotos')}
            />
          )}
          {status.step === 'repeat' && (
            <RepeatWarning
              matches={status.matches}
              onTakeIn={() => goOn('allowRepeat')}
              onStop={startOver}
            />
          )}
          {failure}
        </div>
      )}

      {item && (
        <div className="grid grid-cols-1 gap-x-8 *:min-w-0 wide:grid-cols-2">
          <div>
            <Panel id="item" title={`Taken in as ${item.sku}`}>
              <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 wide:grid-cols-2 lg:grid-cols-4">
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
              <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
                <dt className="font-bold">Department</dt>
                <dd>
                  {item.store_department ? label(STORE_DEPARTMENTS, item.store_department) : 'None'}
                </dd>
                <dt className="font-bold">Notes</dt>
                <dd className="min-w-0 break-words">{item.notes ?? 'None'}</dd>
              </dl>
            </Panel>

            {card && (
              <Panel id="card" title="Item card">
                {!card.staff_confirmed || editingCard ? (
                  <CardForm
                    card={card}
                    busy={busy}
                    onConfirm={(edit) => void confirmCard(edit)}
                    onCancel={editingCard ? () => setEditingCard(false) : undefined}
                  />
                ) : (
                  <>
                    <CardDetails card={card} />
                    {canEdit && (
                      <Button
                        variant="outline"
                        size="lg"
                        className="mt-4 max-sm:w-full"
                        onClick={() => setEditingCard(true)}
                      >
                        Edit the card
                      </Button>
                    )}
                  </>
                )}
              </Panel>
            )}
          </div>

          <div>
            {working}
            {failure}

            {card && !card.staff_confirmed && status.step === 'checking' && (
              <p className="mb-7 hidden border-l-4 border-rule pl-3.5 wide:block">
                Check the card, and the price shows here once you confirm it.
              </p>
            )}

            {card && appraisal && <PricePanel appraisal={appraisal} card={card} />}

            {appraisal && status.step !== 'saved' && (
              <Panel id="decision" title="Your call">
                {explaining ? (
                  <DecisionForm
                    decision={explaining}
                    recommendation={appraisal.recommendation}
                    busy={busy}
                    error={status.step === 'explaining' ? status.error : undefined}
                    onSave={(details) => void decide(explaining, details, true)}
                    onBack={() => setStatus({ step: 'ready' })}
                  />
                ) : (
                  <div className="flex flex-wrap gap-3">
                    <Button
                      size="lg"
                      className="flex-1 max-sm:w-full"
                      disabled={busy || editingCard}
                      onClick={() => choose('yes')}
                    >
                      Yes, list it
                    </Button>
                    <Button
                      variant="outline"
                      size="lg"
                      className="flex-1 max-sm:w-full"
                      disabled={busy || editingCard}
                      onClick={() => choose('no')}
                    >
                      No, don't list it
                    </Button>
                  </div>
                )}
              </Panel>
            )}

            {status.step === 'saved' && item && (
              <div className="mb-7">
                <p role="status" className="mb-7 font-bold">
                  Saved your decision: {status.decision}.
                  {status.destination && ` ${WHERE_IT_GOES[status.destination]}`}
                </p>
                {status.decision === 'yes' && (
                  <ChannelChoice itemId={item.id} onChoose={setChannels} />
                )}
                {status.decision === 'yes' && channels && (
                  <ListingDrafts
                    itemId={item.id}
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
          </div>
        </div>
      )}

      <section aria-labelledby="recent-heading" className="max-w-[30rem] border-t border-rule pt-6">
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
