import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'

import {
  loadBoxSizes,
  loadItemReview,
  lookUpFreshComps,
  type BoxSizeOption,
  type ItemReview,
} from '@/api/approval'
import type { Channel } from '@/api/appraisal'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { Lead, PageHeading } from '@/components/site/AuthLayout'
import { SectionCard } from '@/components/site/SectionCard'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { PricePanel } from '@/pages/appraisal/PricePanel'
import { ChannelChoice } from '@/pages/ChannelChoice'
import { ListingDrafts } from '@/pages/ListingDrafts'
import { itemName, money, releaseMonth, STATUS_NAMES, when } from '@/pages/approval/format'
import {
  DecisionPanel,
  HeldPanel,
  HistoryPanel,
  ListingPanel,
  NotOnlinePanel,
  PackagePanel,
  PutBackPanel,
} from '@/pages/approval/panels'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; review: ItemReview; boxes: BoxSizeOption[] }

const STORABLE = new Set(['approved', 'held_for_season'])

// How often the page asks again while a channel is still taking a listing.
const LISTING_REFRESH_MS = 2000

// What happened to the item, said once the manager has acted on it.
function outcome(review: ItemReview) {
  if (review.status === 'not_listed_online') {
    return 'Not listed online. It stays off every channel until a manager puts it back for review, and the note is in its history.'
  }
  if (review.status === 'declined') {
    return 'Rejected. Staff can say yes again to fix the listing and send it back.'
  }
  if (!STORABLE.has(review.status) && review.status !== 'listed') return null
  if (review.location_code) {
    return `Stored on ${review.location_code} as ${review.full_sku ?? review.sku}.`
  }
  return 'Approved. Enter its shelf or bin below to store it.'
}

type Fresh = { step: 'idle' } | { step: 'loading' } | { step: 'failed'; message: string }

// What similar items sell for now, looked up when a held item comes back for review.
function FreshComps({
  review,
  onChange,
}: {
  review: ItemReview
  onChange: (review: ItemReview) => void
}) {
  const [fresh, setFresh] = useState<Fresh>({ step: 'idle' })
  const asked = useRef(false)

  const lookUp = useCallback(() => {
    setFresh({ step: 'loading' })
    lookUpFreshComps(review.item_id)
      .then((changed) => {
        setFresh({ step: 'idle' })
        onChange(changed)
      })
      .catch((error: Error) => setFresh({ step: 'failed', message: error.message }))
  }, [review.item_id, onChange])

  const missing = review.fresh_appraisal === null
  useEffect(() => {
    // The lookup can search eBay, so ask once even when React runs this effect twice.
    if (!missing || asked.current) return
    asked.current = true
    lookUp()
  }, [missing, lookUp])

  const appraisal = review.fresh_appraisal
  if (appraisal) {
    const then = review.appraisal?.price_typical_cents ?? null
    return (
      <PricePanel
        appraisal={appraisal}
        category={review.category}
        id="fresh-price"
        title="What it sells for now"
        intro={
          <dl className="mb-4 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-b border-rule pb-3 text-[0.9375rem]">
            <dt>Typical sale price when approved</dt>
            <dd className="text-right font-bold tabular-nums">
              {then === null ? 'None found' : money(then)}
            </dd>
            <dt>Typical sale price now</dt>
            <dd className="text-right font-bold tabular-nums">
              {appraisal.price_typical_cents == null
                ? 'None found'
                : money(appraisal.price_typical_cents)}
            </dd>
          </dl>
        }
      />
    )
  }
  return (
    <SectionCard id="fresh-price" title="What it sells for now">
      <div aria-live="polite">
        {fresh.step !== 'failed' && (
          <p className="font-bold">Looking up what similar items sell for now...</p>
        )}
      </div>
      {fresh.step === 'failed' && (
        <div role="alert" className="rounded-xl border-4 border-destructive bg-card px-5 py-4">
          <p className="mb-3 font-bold">{fresh.message}</p>
          <Button variant="outline" size="lg" className="max-sm:w-full" onClick={lookUp}>
            Try again
          </Button>
        </div>
      )}
    </SectionCard>
  )
}

// An item kept off online before staff wrote its listing, which the manager writes and sends here.
function WriteListing({ review, onSent }: { review: ItemReview; onSent: () => void }) {
  const [channels, setChannels] = useState<Channel[] | null>(null)
  return (
    <>
      <Lead>
        It was kept off online before its listing was written, so choose its channels and write the
        listing here. Once it's sent, you can check it and approve it as usual.
      </Lead>
      <ChannelChoice itemId={review.item_id} onChoose={setChannels} onKeptOff={onSent} />
      {channels && <ListingDrafts itemId={review.item_id} channels={channels} onSent={onSent} />}
    </>
  )
}

// What the status line says, with put back named so the manager knows why it's here again.
function statusName(review: ItemReview) {
  if (review.put_back) return 'Put back for review'
  if (review.back_for_review) return 'Back for review in its season'
  return STATUS_NAMES[review.status] ?? review.status
}

// One item a manager reviews: its listings and prices, its package, and the decision.
export function ItemReviewPage() {
  const { itemId = '' } = useParams()
  const { me } = useAuth()
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  usePageTitle(load.state === 'ready' ? itemName(load.review) : 'Review')

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchReview = useCallback(() => {
    return Promise.all([loadItemReview(itemId), loadBoxSizes()])
      .then(([review, boxes]) => setLoad({ state: 'ready', review, boxes }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [itemId])

  useEffect(() => {
    if (!refused) void fetchReview()
  }, [refused, fetchReview])

  const changed = useCallback((review: ItemReview) => {
    setLoad((current) => (current.state === 'ready' ? { ...current, review } : current))
  }, [])

  const beingListed =
    load.state === 'ready' &&
    load.review.listings.some((listing) => listing.channel_status === 'pending')

  // The scheduler lists the item within seconds of storing it, so the page follows along.
  useEffect(() => {
    if (!beingListed) return
    const timer = window.setTimeout(() => {
      loadItemReview(itemId)
        .then(changed)
        .catch(() => {
          // A missed refresh is tried again on the next one, so the page keeps what it has.
        })
    }, LISTING_REFRESH_MS)
    return () => window.clearTimeout(timer)
  }, [beingListed, load, itemId, changed])

  const review = load.state === 'ready' ? load.review : null
  const waiting =
    review?.status === 'appraised' &&
    review.listings.some((listing) => listing.state === 'awaiting_approval')
  const back = review?.back_for_review ?? false
  const putBack = review?.put_back ?? false
  // Kept off before staff sent a listing, so there's nothing to approve until it's written.
  const unwritten = review?.status === 'appraised' && putBack && !waiting
  const held = review?.status === 'held_for_season' && !back
  // Where the timing hint says to hold it, the item can stay off online selling instead.
  const offerNotOnline =
    (waiting && review.release_month !== null) || review?.status === 'held_for_season'
  const note = review ? outcome(review) : null

  return (
    <AppLayout>
      {!refused && (
        <p className="mb-4">
          <Link to="/app/approvals">Back to approvals</Link>
        </p>
      )}
      {refused ? (
        <>
          <PageHeading>Review</PageHeading>
          <p className="mb-7">Only a manager can approve listings and store items.</p>
        </>
      ) : (
        <>
          {!review && <PageHeading>Review</PageHeading>}
          <div aria-live="polite">
            {load.state === 'loading' && <p className="mb-7 font-bold">Loading the item...</p>}
          </div>
          {load.state === 'failed' && (
            <div
              role="alert"
              className="mb-7 rounded-xl border-4 border-destructive bg-card px-5 py-4"
            >
              <p className="mb-3 font-bold">{load.message}</p>
              <Button
                variant="outline"
                size="lg"
                className="max-sm:w-full"
                onClick={() => {
                  setLoad({ state: 'loading' })
                  void fetchReview()
                }}
              >
                Try again
              </Button>
            </div>
          )}
          {review && load.state === 'ready' && (
            <>
              <PageHeading>{itemName(review)}</PageHeading>
              <dl className="mb-7 border-y border-rule py-3 [&_dt]:shrink-0">
                <div className="flex justify-between gap-4">
                  <dt>SKU</dt>
                  <dd className="text-right font-bold wrap-anywhere">
                    {review.full_sku ?? review.sku}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt>Status</dt>
                  <dd className="text-right">{statusName(review)}</dd>
                </div>
                {review.release_month && (
                  <div className="flex justify-between gap-4">
                    <dt>Release month</dt>
                    <dd className="text-right">{releaseMonth(review.release_month)}</dd>
                  </div>
                )}
                {review.submitted_by_name && review.submitted_at && (
                  <div className="flex justify-between gap-4">
                    <dt>Sent by</dt>
                    <dd className="text-right">
                      {review.submitted_by_name}, {when(review.submitted_at)}
                    </dd>
                  </div>
                )}
                {review.approved_by_name && review.approved_at && (
                  <div className="flex justify-between gap-4">
                    <dt>Approved by</dt>
                    <dd className="text-right">
                      {review.approved_by_name}, {when(review.approved_at)}
                    </dd>
                  </div>
                )}
              </dl>
              <div aria-live="polite">{note && <p className="mb-7 font-bold">{note}</p>}</div>
              {waiting && (
                <Lead>
                  Check each listing and its price, enter the package, then approve or reject it.
                </Lead>
              )}
              {back && (
                <Lead>
                  {putBack
                    ? 'It was put back for review, so nothing is listed until you look again.'
                    : 'Its release month has come, so nothing is listed until you look again.'}{' '}
                  Compare the approved prices with what it sells for now, then approve it as it is,
                  change a price, or reject it.
                </Lead>
              )}
              {unwritten && (
                <WriteListing
                  review={review}
                  onSent={() => {
                    loadItemReview(review.item_id)
                      .then(changed)
                      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
                  }}
                />
              )}
              {back && <FreshComps review={review} onChange={changed} />}
              {held && <HeldPanel review={review} onChange={changed} />}
              {review.listings.map((listing) => (
                <ListingPanel
                  key={`${listing.channel}-${listing.price_override_cents ?? 'typical'}`}
                  review={review}
                  listing={listing}
                  onChange={changed}
                />
              ))}
              {(waiting || STORABLE.has(review.status)) && (
                <PackagePanel review={review} boxes={load.boxes} onChange={changed} />
              )}
              {(waiting || back) && <DecisionPanel review={review} onChange={changed} />}
              {offerNotOnline && <NotOnlinePanel review={review} onChange={changed} />}
              {review.status === 'not_listed_online' && (
                <PutBackPanel review={review} onChange={changed} />
              )}
              <HistoryPanel review={review} />
            </>
          )}
        </>
      )}
    </AppLayout>
  )
}
