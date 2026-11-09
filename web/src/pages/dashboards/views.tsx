import type { ReactNode } from 'react'

import type {
  ConflictKind,
  Dashboards,
  FunnelCounts,
  LiveTimeToSell,
  PriceBand,
} from '@/api/dashboards'
import { SectionCard } from '@/components/site/SectionCard'
import { when } from '@/pages/approval/format'

import { BarColumns, Bars, Chart, Empty, Legend, MonthLines, type Bar } from './charts'
import {
  bandName,
  CATEGORIES,
  CATEGORY_NAMES,
  count,
  elapsed,
  monthName,
  percent,
  SERIES_COLOR,
} from './format'

const NO_HISTORY = 'There is no sales history to chart yet.'

function View({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <SectionCard id={id} title={title}>
      {children}
    </SectionCard>
  )
}

function Pair({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-1 gap-x-10 wide:grid-cols-2">{children}</div>
}

function bandOf(bands: PriceBand[], band: number) {
  return bands.find((entry) => entry.band === band) ?? { band, low_cents: null, high_cents: null }
}

function LiveTimes({ rows, bands }: { rows: LiveTimeToSell[]; bands: PriceBand[] }) {
  if (rows.length === 0) return <Empty>No listings have gone up yet.</Empty>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[0.9375rem]">
        <thead>
          <tr className="border-b border-rule">
            <th className="py-2 pr-3 font-bold">Category and price</th>
            <th className="py-2 pr-3 text-right font-bold">Listed</th>
            <th className="py-2 pr-3 text-right font-bold">Sold</th>
            <th className="py-2 text-right font-bold">Middle time to sell</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.category}-${row.band}`} className="border-b border-rule">
              <td className="py-2 pr-3">
                {CATEGORY_NAMES[row.category]}, {bandName(bandOf(bands, row.band))}
              </td>
              <td className="py-2 pr-3 text-right">{row.listed}</td>
              <td className="py-2 pr-3 text-right">{row.sold}</td>
              <td className="py-2 text-right whitespace-nowrap">
                {row.median_hours === null ? 'None sold yet' : elapsed(row.median_hours)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TimeToSellView({ data }: { data: Dashboards }) {
  const runDays = data.history?.run_days ?? 90
  return (
    <View id="time-to-sell" title="Time to sell by category and price">
      {data.history === null ? (
        <Chart source="history" title="Middle days to sell, by price band">
          <Empty>{NO_HISTORY}</Empty>
        </Chart>
      ) : (
        <Pair>
          {CATEGORIES.map((category) => {
            const bars: Bar[] = data.time_to_sell.synthetic
              .filter((row) => row.category === category)
              .map((row) => ({
                label: bandName(bandOf(data.price_bands, row.band)),
                value: row.median_days,
                text: row.median_days === null ? 'None sold' : count(row.median_days, 'day'),
                note: row.listed === 0 ? 'None listed' : `${row.sold} of ${row.listed} sold`,
                color: SERIES_COLOR[category],
              }))
            return (
              <Chart
                key={category}
                source="history"
                title={`${CATEGORY_NAMES[category]}, middle days to sell`}
                description={`The middle of the days each sold listing took, with a full bar at ${runDays} days, when an unsold listing comes down.`}
              >
                <Bars
                  bars={bars}
                  max={runDays}
                  label={`${CATEGORY_NAMES[category]}, middle days to sell by price band`}
                />
              </Chart>
            )
          })}
        </Pair>
      )}
      <Chart
        source="live"
        title="Listings on the sales channels"
        description="From the time a channel confirmed the listing to the time it took the order."
      >
        <LiveTimes rows={data.time_to_sell.live} bands={data.price_bands} />
      </Chart>
    </View>
  )
}

export function SeasonalityView({ data }: { data: Dashboards }) {
  const series = CATEGORIES.map((category) => ({
    category,
    points: Array.from({ length: 12 }, (_, month) => {
      const row = data.seasonality.find(
        (entry) => entry.category === category && entry.month === month + 1,
      )
      return row?.sales_per_100_weekly ?? null
    }),
  }))
  const row = (category: string, month: number) =>
    data.seasonality.find((entry) => entry.category === category && entry.month === month)
  return (
    <View id="seasonality" title="Seasonality by category">
      <Chart
        source="history"
        title="Sales for every 100 listings up a week, by month"
        description="Each month's sales over the days listings were up in it, so the months when the history was filling up or running out aren't low just for having fewer listings."
      >
        {data.history === null ? (
          <Empty>{NO_HISTORY}</Empty>
        ) : (
          <>
            <Legend categories={CATEGORIES} />
            <MonthLines
              series={series}
              label="Line chart of past sales for every 100 listings up a week, by month, for apparel and for electronics and games. The table below has the numbers."
            />
            <details className="mt-3">
              <summary className="cursor-pointer font-bold text-link">Show the numbers</summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-[0.9375rem]">
                  <thead>
                    <tr className="border-b border-rule">
                      <th className="py-2 pr-3 font-bold">Month</th>
                      {CATEGORIES.map((category) => (
                        <th key={category} className="py-2 pr-3 text-right font-bold">
                          {CATEGORY_NAMES[category]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => (
                      <tr key={month} className="border-b border-rule">
                        <td className="py-2 pr-3">{monthName(month, 'long')}</td>
                        {CATEGORIES.map((category) => {
                          const entry = row(category, month)
                          return (
                            <td key={category} className="py-2 pr-3 text-right">
                              {entry?.sales_per_100_weekly == null
                                ? 'No listings up'
                                : `${entry.sales_per_100_weekly.toFixed(1)}, from ${count(entry.sales, 'sale')}`}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </Chart>
    </View>
  )
}

function funnelBars(counts: FunnelCounts, runDays: number | null, color?: string): Bar[] {
  const stage = (label: string, value: number): Bar => ({
    label,
    value,
    text: value.toLocaleString(),
    note: counts.forwarded === 0 ? undefined : `${percent(value, counts.forwarded)} of forwarded`,
    color,
  })
  return [
    stage('Forwarded to Ecommerce', counts.forwarded),
    stage('Accepted by staff', counts.accepted),
    stage('Listed', counts.listed),
    stage(runDays === null ? 'Sold' : `Sold within ${runDays} days`, counts.sold),
  ]
}

function Against({ counts }: { counts: FunnelCounts }) {
  if (counts.called === 0) return null
  return (
    <p className="mt-3 text-[0.9375rem]">
      Staff went against a yes or a no on {counts.against_recommendation} of {counts.called} calls,{' '}
      {percent(counts.against_recommendation, counts.called)}. A check has no side, so it isn't
      counted.
    </p>
  )
}

export function FunnelView({ data }: { data: Dashboards }) {
  const runDays = data.history?.run_days ?? 90
  const live = data.triage_funnel.live
  return (
    <View id="funnel" title="Triage funnel">
      {data.history === null ? (
        <Chart source="history" title="From forwarded to sold">
          <Empty>{NO_HISTORY}</Empty>
        </Chart>
      ) : (
        <Pair>
          {data.triage_funnel.synthetic.map((counts) => (
            <Chart
              key={counts.category}
              source="history"
              title={`${CATEGORY_NAMES[counts.category]}, from forwarded to sold`}
            >
              <Bars
                bars={funnelBars(counts, runDays, SERIES_COLOR[counts.category])}
                max={counts.forwarded}
                label={`${CATEGORY_NAMES[counts.category]} triage funnel`}
              />
              <Against counts={counts} />
            </Chart>
          ))}
        </Pair>
      )}
      <Chart
        source="live"
        title="Items in Turnstone, from intake to sold"
        description="Each item is counted by the call that stands on it, which is the newest one."
      >
        {live.forwarded === 0 ? (
          <Empty>No item has come through intake yet.</Empty>
        ) : (
          <>
            <Bars
              bars={funnelBars(live, null, 'bg-info-ink')}
              max={live.forwarded}
              label="Live triage funnel"
            />
            <Against counts={live} />
          </>
        )}
      </Chart>
    </View>
  )
}

const CONFLICT_NAMES: Record<ConflictKind, string> = {
  double_sale: 'Sold on both channels',
  stale_listing: 'Still up after Turnstone took it down',
  unknown_listing: 'A listing or sale Turnstone has no record of',
}

export function SyncView({ data }: { data: Dashboards }) {
  const health = data.sync_health
  const good = 'bg-info-ink'
  const bad = 'bg-destructive'
  const groups: { title: string; bars: Bar[] }[] = [
    {
      title: 'Putting listings up',
      bars: [
        { label: 'Confirmed', value: health.published, text: `${health.published}`, color: good },
        {
          label: 'Refused by the channel',
          value: health.publish_rejected,
          text: `${health.publish_rejected}`,
          color: bad,
        },
        {
          label: 'Failed tries',
          value: health.publish_failed,
          text: `${health.publish_failed}`,
          color: bad,
        },
        {
          label: 'Gave up',
          value: health.publish_gave_up,
          text: `${health.publish_gave_up}`,
          color: bad,
        },
      ],
    },
    {
      title: 'Hearing about sales',
      bars: [
        {
          label: 'By webhook',
          value: health.sales_by_webhook,
          text: `${health.sales_by_webhook}`,
          color: good,
        },
        {
          label: 'By polling',
          value: health.sales_by_polling,
          text: `${health.sales_by_polling}`,
          color: good,
        },
      ],
    },
    {
      title: 'Taking listings down after a sale',
      bars: [
        { label: 'Taken down', value: health.delisted, text: `${health.delisted}`, color: good },
        {
          label: 'Found already sold',
          value: health.delist_found_sold,
          text: `${health.delist_found_sold}`,
          color: bad,
        },
        {
          label: 'Failed tries',
          value: health.delist_failed,
          text: `${health.delist_failed}`,
          color: bad,
        },
        {
          label: 'Gave up',
          value: health.delist_gave_up,
          text: `${health.delist_gave_up}`,
          color: bad,
        },
      ],
    },
  ]
  const max = Math.max(1, ...groups.flatMap((group) => group.bars.map((bar) => bar.value ?? 0)))
  const openFlags = health.flags.reduce((total, flag) => total + flag.open, 0)

  return (
    <View id="sync" title="Sync health and agreement">
      {health.first_event_at === null || health.last_event_at === null ? (
        <Chart source="live" title="What sync did on the sales channels">
          <Empty>Sync hasn't done anything yet.</Empty>
        </Chart>
      ) : (
        <Pair>
          <Chart
            source="live"
            title="What sync did on the sales channels"
            description={`From ${when(health.first_event_at)} to ${when(health.last_event_at)}, with every bar on the same scale. A sale found by polling is one whose webhook never came.`}
          >
            <BarColumns>
              {groups.map((group) => (
                <div key={group.title} className="col-span-full mb-5 grid grid-cols-subgrid">
                  <h3 className="col-span-full mb-1 text-[0.9375rem] font-bold">{group.title}</h3>
                  <Bars bars={group.bars} max={max} label={group.title} inColumns />
                </div>
              ))}
            </BarColumns>
          </Chart>
          <Chart
            source="live"
            title="Where Turnstone and a channel disagreed"
            description="Each one is a flag on Needs Attention until someone settles it."
          >
            <table className="mb-4 w-full text-left text-[0.9375rem]">
              <thead>
                <tr className="border-b border-rule">
                  <th className="py-2 pr-3 font-bold">Disagreement</th>
                  <th className="py-2 pr-3 text-right font-bold">Open</th>
                  <th className="py-2 text-right font-bold">Settled</th>
                </tr>
              </thead>
              <tbody>
                {health.flags.map((flag) => (
                  <tr key={flag.conflict} className="border-b border-rule">
                    <td className="py-2 pr-3">{CONFLICT_NAMES[flag.conflict]}</td>
                    <td
                      className={`py-2 pr-3 text-right ${flag.open > 0 ? 'font-bold text-destructive' : ''}`}
                    >
                      {flag.open}
                    </td>
                    <td className="py-2 text-right">{flag.resolved}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mb-2 text-[0.9375rem]">
              {openFlags === 0
                ? 'Turnstone and both channels agree on everything sync has seen.'
                : `${count(openFlags, 'disagreement is', 'disagreements are')} still open on Needs Attention.`}
            </p>
            <p className="mb-2 text-[0.9375rem]">
              {health.oversold_items === 0
                ? 'No item has two orders that are still standing.'
                : `${count(health.oversold_items, 'item has', 'items have')} two orders still standing, and one of each needs cancelling.`}
            </p>
            <p className="text-[0.9375rem]">
              {count(health.jobs_waiting, 'channel job is', 'channel jobs are')} waiting to run, and{' '}
              {count(health.jobs_given_up, 'has', 'have')} given up.
            </p>
          </Chart>
        </Pair>
      )}
    </View>
  )
}
