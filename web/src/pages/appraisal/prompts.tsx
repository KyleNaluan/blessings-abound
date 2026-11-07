import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { Link } from 'react-router'

import type { RejectedMatch, RetakePhoto } from '@/api/appraisal'
import type { KeptOffMatch } from '@/api/approval'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { when } from '@/pages/approval/format'

import { DESTINATIONS, label } from '../intake'

// The questions intake asks about an item, and the warnings it gives. Nothing is saved until staff
// answer a question.

const itemName = (row: { brand: string | null; product: string | null; sku: string }) =>
  [row.brand, row.product].filter(Boolean).join(' ') || row.sku

function Prompt({
  id,
  title,
  warning = false,
  children,
  actions,
}: {
  id: string
  title: string
  // A warning staff can step past, rather than something that stops the item.
  warning?: boolean
  children: ReactNode
  actions: ReactNode
}) {
  const ref = useRef<HTMLElement>(null)

  // It shows below the form, so it takes focus to scroll into view, as the error summary does.
  useLayoutEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <section
      ref={ref}
      role="alert"
      tabIndex={-1}
      aria-labelledby={`${id}-heading`}
      className={cn(
        'mb-7 border-4 px-5 py-4 focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid',
        warning ? 'border-warn' : 'border-destructive',
      )}
    >
      <h2 id={`${id}-heading`} className="mb-2 text-xl font-bold">
        {title}
      </h2>
      {children}
      <div className="flex flex-wrap gap-3">{actions}</div>
    </section>
  )
}

export function RetakePrompt({
  photos,
  onRetake,
  onKeep,
}: {
  photos: RetakePhoto[]
  onRetake: () => void
  onKeep: () => void
}) {
  const one = photos.length === 1
  return (
    <Prompt
      id="retake"
      warning
      title={one ? 'Take this photo again?' : 'Take these photos again?'}
      actions={
        <>
          <Button size="lg" className="max-sm:w-full" onClick={onRetake}>
            {one ? 'Take it again' : 'Take them again'}
          </Button>
          <Button variant="outline" size="lg" className="max-sm:w-full" onClick={onKeep}>
            {one ? 'Use it anyway' : 'Use them anyway'}
          </Button>
        </>
      }
    >
      <ul className="mb-3">
        {photos.map((photo) => (
          <li key={photo.number} className="border-t border-rule py-2">
            <span className="font-bold">Photo {photo.number}:</span> {photo.reason}
          </li>
        ))}
      </ul>
      <p className="mb-4">
        A clear photo gives a better item card and price, but you can keep {one ? 'it' : 'them'} if
        a retake won't help.
      </p>
    </Prompt>
  )
}

export function RepeatWarning({
  matches,
  onTakeIn,
  onStop,
}: {
  matches: RejectedMatch[]
  onTakeIn: () => void
  onStop: () => void
}) {
  return (
    <Prompt
      id="repeat"
      title="This may have been rejected before"
      actions={
        <>
          <Button size="lg" className="max-sm:w-full" onClick={onStop}>
            Don't take it in
          </Button>
          <Button variant="outline" size="lg" className="max-sm:w-full" onClick={onTakeIn}>
            Take it in anyway
          </Button>
        </>
      }
    >
      <p className="mb-3">
        A photo matches {matches.length === 1 ? 'an item' : `${matches.length} items`} staff said no
        to. Check it isn't the same item before you take it in again.
      </p>
      <ul className="mb-4">
        {matches.map((match) => (
          <li key={match.item_id} className="border-t border-rule py-3">
            <p className="font-bold break-words">{itemName(match)}</p>
            <p className="text-sm text-muted-foreground">
              SKU {match.sku}, rejected {when(match.rejected_at)}
            </p>
            <p className="break-words">Why: {match.rejection_reason}</p>
            <p>Where it went: {label(DESTINATIONS, match.destination)}</p>
          </li>
        ))}
      </ul>
    </Prompt>
  )
}

// A new item that may be one kept off online before. It never stops the item, since staff may have
// a good reason to take it in, but they see who kept the earlier one off and why.
export function KeptOffWarning({
  matches,
  canOpen,
  onCarryOn,
}: {
  matches: KeptOffMatch[]
  // Only a manager can open the earlier item's review, so staff see its SKU instead.
  canOpen: boolean
  onCarryOn: () => void
}) {
  const one = matches.length === 1
  return (
    <Prompt
      id="kept-off"
      warning
      title="This may be an item kept off online"
      actions={
        <Button size="lg" className="max-sm:w-full" onClick={onCarryOn}>
          Carry on
        </Button>
      }
    >
      <p className="mb-3">
        {one ? 'An earlier item' : `${matches.length} earlier items`} like this one{' '}
        {one ? 'was' : 'were'} taken out of online selling. You can carry on, but check{' '}
        {one ? "it isn't" : "they aren't"} the same item first.
      </p>
      <ul className="mb-4">
        {matches.map((match) => (
          <li key={match.item_id} className="border-t border-rule py-3">
            {canOpen ? (
              <Link to={`/app/approvals/${match.item_id}`} className="font-bold break-words">
                {itemName(match)}
              </Link>
            ) : (
              <p className="font-bold break-words">{itemName(match)}</p>
            )}
            <p className="text-sm text-muted-foreground">
              SKU {match.sku}, kept off online by {match.decided_by_name} on{' '}
              {when(match.decided_at)}
            </p>
            {match.note && <p className="break-words">Why: {match.note}</p>}
            <p>
              Matches on:{' '}
              {match.matched_on === 'photo' ? 'the same photo' : 'the same brand and product'}
            </p>
          </li>
        ))}
      </ul>
      {!canOpen && (
        <p className="mb-4">
          Only a manager can put an item back for review, so ask one if it should go online after
          all.
        </p>
      )}
    </Prompt>
  )
}
