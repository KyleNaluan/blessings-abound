import { useState } from 'react'

import type { Appraisal, ItemCard, PricedComp } from '@/api/appraisal'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { money } from '@/pages/approval/format'

import { Panel } from './parts'

// How many listings show before staff ask for all of them, spread from the cheapest to the dearest.
const SAMPLE = 6

const CONFIDENCE = { low: 'low', medium: 'medium', high: 'high' } as const

type Tone = 'yes' | 'no' | 'check'

const TONES: Record<Tone, string> = {
  yes: 'border-yes bg-yes-soft text-yes-ink',
  no: 'border-no-ink bg-no-soft text-no-ink',
  check: 'border-warn-line bg-warn-soft text-warn-ink',
}

function verdict(appraisal: Appraisal): { tone: Tone; title: string } {
  const confidence = `${CONFIDENCE[appraisal.confidence]} confidence`
  if (appraisal.price_typical_cents == null) return { tone: 'check', title: 'No price' }
  if (appraisal.recommendation === 'yes')
    return { tone: 'yes', title: `Worth listing, ${confidence}` }
  if (appraisal.recommendation === 'no') {
    return { tone: 'no', title: `Not worth listing, ${confidence}` }
  }
  return { tone: 'check', title: `Check it by hand, ${confidence}` }
}

// The numbers the appraisal was priced by, which it keeps with itself as it was on the day.
function pricedBy(appraisal: Appraisal, category: ItemCard['category']) {
  const pricing = appraisal.rules_config.pricing as Record<string, unknown> | undefined
  const search = appraisal.rules_config.search as Record<string, unknown> | undefined
  const factorName =
    category === 'electronics_games' ? 'games_ask_to_sale_factor' : 'ask_to_sale_factor'
  const factor = typeof pricing?.[factorName] === 'number' ? pricing[factorName] : null
  const queries = Array.isArray(search?.queries)
    ? search.queries.filter((query): query is string => typeof query === 'string')
    : []
  return { factor, queries }
}

// Evenly spaced across the listings, so the few shown still run from the cheapest to the dearest.
function spread(comps: PricedComp[], count: number) {
  if (comps.length <= count) return comps
  const picks = new Set(
    Array.from({ length: count }, (_, index) =>
      Math.round((index * (comps.length - 1)) / (count - 1)),
    ),
  )
  return comps.filter((_, index) => picks.has(index))
}

function RangeBar({ low, typical, high }: { low: number; typical: number; high: number }) {
  const at = high > low ? ((typical - low) / (high - low)) * 100 : 50
  return (
    <div
      aria-hidden="true"
      className="relative mt-1.5 mb-4 h-[1.1rem] before:absolute before:inset-x-0 before:top-1/2 before:-mt-px before:h-0.5 before:bg-foreground before:content-['']"
    >
      <i className="absolute top-0 left-0 h-full w-0.5 bg-foreground" />
      <i className="absolute top-0 -ml-0.5 h-full w-1 bg-foreground" style={{ left: `${at}%` }} />
      <i className="absolute top-0 right-0 h-full w-0.5 bg-foreground" />
    </div>
  )
}

function Listings({ comps, factor }: { comps: PricedComp[]; factor: number | null }) {
  const [all, setAll] = useState(false)
  const used = comps.filter((comp) => !comp.outlier)
  const leftOut = comps.length - used.length
  const sample = spread(used, SAMPLE)
  const canExpand = sample.length < comps.length
  const shown = all ? comps : sample
  const caption = all
    ? `All ${comps.length} similar eBay listings, cheapest first`
    : canExpand
      ? `${sample.length} of ${comps.length} similar eBay listings, cheapest to dearest`
      : `${comps.length} similar eBay listing${comps.length === 1 ? '' : 's'}`

  return (
    <div className="mt-5">
      <table className="w-full table-fixed border-collapse text-sm">
        <caption className="pb-1.5 text-left text-[0.9375rem] font-bold">{caption}</caption>
        {/* A fixed table takes its widths from here, since the headings are only for screen readers. */}
        <colgroup>
          <col />
          <col className="w-[5.5rem]" />
        </colgroup>
        <thead className="sr-only">
          <tr>
            <th scope="col">Listing</th>
            <th scope="col">Asking price</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((comp, index) => (
            <tr
              key={`${comp.url}-${index}`}
              className={cn(comp.outlier && 'text-muted-foreground')}
            >
              <td className="border-t border-rule py-2 pr-3 align-top">
                <a
                  href={comp.url}
                  target="_blank"
                  rel="noreferrer"
                  title={comp.title}
                  className="block truncate"
                >
                  {comp.title}
                </a>
                {(comp.condition || comp.outlier) && (
                  <span className="block text-[0.8125rem] text-muted-foreground">
                    {[comp.condition, comp.outlier && 'Left out, far from the other prices']
                      .filter(Boolean)
                      .join('. ')}
                  </span>
                )}
              </td>
              <td className="border-t border-rule py-2 text-right align-top tabular-nums">
                {money(comp.asking_cents)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {canExpand && (
        <Button
          variant="outline"
          size="lg"
          className="mt-3 max-sm:w-full"
          aria-expanded={all}
          onClick={() => setAll(!all)}
        >
          {all ? 'Show fewer listings' : `Show all ${comps.length} listings`}
        </Button>
      )}
      <p className="mt-3 text-[0.8125rem] text-muted-foreground">
        {factor != null &&
          `The range is these asking prices times ${factor}, because items sell for less than they're listed at. `}
        {leftOut > 0 &&
          `${leftOut} listing${leftOut === 1 ? ' was' : 's were'} left out for being far from the rest.`}
      </p>
    </div>
  )
}

export function PricePanel({ appraisal, card }: { appraisal: Appraisal; card: ItemCard }) {
  const { tone, title } = verdict(appraisal)
  const { factor, queries } = pricedBy(appraisal, card.category)
  const low = appraisal.price_low_cents
  const typical = appraisal.price_typical_cents
  const high = appraisal.price_high_cents
  const searched = queries.at(-1)

  return (
    <Panel id="price" title="Price">
      {low != null && typical != null && high != null && (
        <>
          <dl className="grid grid-cols-3 tabular-nums">
            <div>
              <dt className="text-[0.8125rem] text-muted-foreground">Low</dt>
              <dd className="text-[1.35rem] font-bold">{money(low)}</dd>
            </div>
            <div className="text-center">
              <dt className="text-[0.8125rem] text-muted-foreground">Typical</dt>
              <dd className="text-[2rem] leading-[1.2] font-bold">{money(typical)}</dd>
            </div>
            <div className="text-right">
              <dt className="text-[0.8125rem] text-muted-foreground">High</dt>
              <dd className="text-[1.35rem] font-bold">{money(high)}</dd>
            </div>
          </dl>
          <RangeBar low={low} typical={typical} high={high} />
          <dl className="mb-4 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-[0.9375rem]">
            <dt>Left after eBay fees and supplies</dt>
            <dd className="text-right font-bold tabular-nums">
              {appraisal.net_after_fees_cents == null
                ? 'None'
                : money(appraisal.net_after_fees_cents)}
            </dd>
            <dt>Listings the price comes from</dt>
            <dd className="text-right font-bold tabular-nums">{appraisal.comps_count}</dd>
          </dl>
        </>
      )}
      <div className={cn('border-l-[5px] px-3.5 py-2.5 text-[0.9375rem]', TONES[tone])}>
        <p className="font-bold">{title}</p>
        {appraisal.explanation && <p>{appraisal.explanation}</p>}
      </div>
      {searched && (
        <p className="mt-3 text-[0.9375rem] break-words">
          Searched eBay for "{searched}"
          {queries.length > 1 && `, because "${queries[0]}" found too few listings`}.
        </p>
      )}
      {appraisal.comps.length > 0 && <Listings comps={appraisal.comps} factor={factor} />}
    </Panel>
  )
}
