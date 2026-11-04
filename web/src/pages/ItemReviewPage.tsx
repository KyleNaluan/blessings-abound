import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { loadBoxSizes, loadItemReview, type BoxSizeOption, type ItemReview } from '@/api/approval'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { itemName, releaseMonth, STATUS_NAMES, when } from '@/pages/approval/format'
import { DecisionPanel, ListingPanel, PackagePanel } from '@/pages/approval/panels'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; review: ItemReview; boxes: BoxSizeOption[] }

const STORABLE = new Set(['approved', 'held_for_season'])

// How often the page asks again while a channel is still taking a listing.
const LISTING_REFRESH_MS = 2000

// What happened to the item, said once the manager has acted on it.
function outcome(review: ItemReview) {
  if (review.status === 'declined') {
    return 'Rejected. Staff can say yes again to fix the listing and send it back.'
  }
  if (!STORABLE.has(review.status) && review.status !== 'listed') return null
  if (review.location_code) {
    return `Stored on ${review.location_code} as ${review.full_sku ?? review.sku}.`
  }
  return 'Approved. Enter its shelf or bin below to store it.'
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
  }, [beingListed, load, itemId])

  function changed(review: ItemReview) {
    setLoad((current) => (current.state === 'ready' ? { ...current, review } : current))
  }

  const review = load.state === 'ready' ? load.review : null
  const waiting =
    review?.status === 'appraised' &&
    review.listings.some((listing) => listing.state === 'awaiting_approval')
  const note = review ? outcome(review) : null

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        {refused ? (
          <Link to="/app">Back to home</Link>
        ) : (
          <Link to="/app/approvals">Back to approvals</Link>
        )}
      </p>
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
            <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
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
              <dl className="mb-7 border-y border-rule py-3">
                <div className="flex justify-between gap-4">
                  <dt>SKU</dt>
                  <dd className="text-right font-bold wrap-anywhere">
                    {review.full_sku ?? review.sku}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt>Status</dt>
                  <dd className="text-right">{STATUS_NAMES[review.status] ?? review.status}</dd>
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
              </dl>
              <div aria-live="polite">{note && <p className="mb-7 font-bold">{note}</p>}</div>
              {waiting && (
                <Lead>
                  Check each listing and its price, enter the package, then approve or reject it.
                </Lead>
              )}
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
              {waiting && <DecisionPanel review={review} onChange={changed} />}
            </>
          )}
        </>
      )}
    </AuthLayout>
  )
}
