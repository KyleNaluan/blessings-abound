import type { Dashboards } from '@/api/dashboards'
import { cardSurface } from '@/components/site/card'
import { cn } from '@/lib/utils'

import { SourceNote } from './charts'

// How far the tiles sit below the top of this section: the heading row's fixed height and the
// gap under it. The insight chat starts this far down, so its top lines up with the tiles.
export const TILES_OFFSET = 'xl:mt-12'

// The few counts a manager looks at first, all from the live test sales, so the row carries one
// tag for all of them.
export function Headlines({ data }: { data: Dashboards }) {
  const live = data.triage_funnel.live
  const tiles: [string, number][] = [
    ['Taken in', live.forwarded],
    ['Listed on the sales channels', live.listed],
    ['Sold', live.sold],
    ['Sold twice', data.sync_health.oversold_items],
  ]
  return (
    <section aria-labelledby="headlines-heading" className="mb-8">
      <div className="mb-3 flex h-9 items-center gap-x-3">
        <h2 id="headlines-heading" className="text-xl font-bold">
          At a glance
        </h2>
        <SourceNote source="live" className="mt-0" />
      </div>
      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {tiles.map(([label, value]) => (
          <div key={label} className={cn(cardSurface, 'p-4 wide:p-5')}>
            <dt className="text-sm text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-3xl font-semibold">{value.toLocaleString()}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
