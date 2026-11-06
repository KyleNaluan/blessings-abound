import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { Category, Dashboards, FunnelCounts, SyncHealth } from '@/api/dashboards'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const CATEGORIES: Category[] = ['apparel', 'electronics_games']
const EDGES = [1500, 3000, 5000, 10000, 25000]

const NO_FUNNEL: FunnelCounts = {
  forwarded: 0,
  accepted: 0,
  listed: 0,
  sold: 0,
  called: 0,
  against_recommendation: 0,
}

const NO_SYNC: SyncHealth = {
  first_event_at: null,
  last_event_at: null,
  published: 0,
  publish_rejected: 0,
  publish_failed: 0,
  publish_gave_up: 0,
  sales_by_webhook: 0,
  sales_by_polling: 0,
  delisted: 0,
  delist_failed: 0,
  delist_gave_up: 0,
  delist_found_sold: 0,
  flags: [
    { conflict: 'double_sale', open: 0, resolved: 0 },
    { conflict: 'stale_listing', open: 0, resolved: 0 },
    { conflict: 'unknown_listing', open: 0, resolved: 0 },
  ],
  oversold_items: 0,
  jobs_waiting: 0,
  jobs_given_up: 0,
}

// What the API sends before anything is loaded or sold.
const EMPTY: Dashboards = {
  price_bands: [0, ...EDGES].map((low, band) => ({
    band,
    low_cents: band === 0 ? null : low,
    high_cents: EDGES[band] ?? null,
  })),
  history: null,
  time_to_sell: { synthetic: [], live: [] },
  seasonality: [],
  triage_funnel: { synthetic: [], live: NO_FUNNEL },
  sync_health: NO_SYNC,
}

// A loaded synthetic history, and one item listed on both channels that sold on Channel A.
const LOADED: Dashboards = {
  ...EMPTY,
  history: {
    first_forwarded_on: '2025-07-01',
    last_forwarded_on: '2026-06-30',
    items: 656,
    listings: 369,
    sales: 106,
    run_days: 90,
  },
  time_to_sell: {
    synthetic: CATEGORIES.flatMap((category) =>
      EDGES.concat(0).map((_, band) => ({
        category,
        band,
        listed: band === 5 ? 0 : 10,
        sold: band === 5 ? 0 : 4,
        median_days: band === 5 ? null : 30 + band,
      })),
    ),
    live: [{ category: 'apparel', band: 2, listed: 2, sold: 1, median_hours: 0.5 }],
  },
  seasonality: CATEGORIES.flatMap((category) =>
    Array.from({ length: 12 }, (_, month) => ({
      category,
      month: month + 1,
      sales: 3,
      listing_days: 700,
      sales_per_100_weekly: 3,
    })),
  ),
  triage_funnel: {
    synthetic: CATEGORIES.map((category) => ({
      category,
      forwarded: 100,
      accepted: 60,
      listed: 60,
      sold: 20,
      called: 90,
      against_recommendation: 9,
    })),
    live: { forwarded: 1, accepted: 1, listed: 1, sold: 1, called: 1, against_recommendation: 0 },
  },
  sync_health: {
    ...NO_SYNC,
    first_event_at: '2026-11-05T15:00:00Z',
    last_event_at: '2026-11-05T15:30:00Z',
    published: 2,
    sales_by_webhook: 1,
    delisted: 1,
  },
}

function stubApi(role: string, answers: (() => Response)[] = [() => Response.json(LOADED)]) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const key = `${request.method} ${new URL(request.url).pathname}`
      calls.push(key)
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      // Each load takes the next answer, and the last one keeps coming after that.
      if (key === 'GET /dashboards') return (answers.length > 1 ? answers.shift()! : answers[0])()
      throw new Error(`unexpected ${key}`)
    }),
  )
  return calls
}

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderDashboards() {
  render(
    <MemoryRouter initialEntries={['/app/dashboards']}>
      <App />
    </MemoryRouter>,
  )
}

function charts() {
  return screen.getAllByRole('figure')
}

test('a manager sees the four views, with every chart saying where its numbers come from', async () => {
  stubApi('manager')
  renderDashboards()
  await screen.findByRole('heading', { level: 2, name: 'Triage funnel' })
  expect(
    screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
  ).toEqual([
    'Time to sell by category and price',
    'Seasonality by category',
    'Triage funnel',
    'Sync health and agreement',
  ])
  expect(screen.getByText(/656 items forwarded/)).toBeInTheDocument()
  for (const chart of charts()) {
    const labels = within(chart).queryAllByText(/^Synthetic(, live| history)\.$/)
    // Each chart has one label, so synthetic history and live test sales never share a chart.
    expect(labels).toHaveLength(1)
  }
  const sources = charts().map(
    (chart) => within(chart).getByText(/^Synthetic(, live| history)\.$/).textContent,
  )
  expect(sources.filter((source) => source === 'Synthetic history.')).toHaveLength(5)
  expect(sources.filter((source) => source === 'Synthetic, live.')).toHaveLength(4)
})

test('the bars keep their numbers as text', async () => {
  stubApi('manager')
  renderDashboards()
  const apparel = await screen.findByRole('list', {
    name: 'Apparel, middle days to sell by price band',
  })
  const rows = within(apparel).getAllByRole('listitem')
  expect(rows.map((row) => row.textContent)).toEqual([
    'Under $1530 days4 of 10 sold',
    '$15 to $29.9931 days4 of 10 sold',
    '$30 to $49.9932 days4 of 10 sold',
    '$50 to $99.9933 days4 of 10 sold',
    '$100 to $249.9934 days4 of 10 sold',
    '$250 and upNone soldNone listed',
  ])
  const live = screen.getByRole('row', { name: /Apparel, \$30 to \$49.99/ })
  expect(live).toHaveTextContent('30 minutes')
  expect(
    screen.getAllByText('Staff went against a yes or a no on 9 of 90 calls, 10%.', {
      exact: false,
    }),
  ).toHaveLength(2)
})

test('with nothing loaded or sold, each view says so instead of drawing empty charts', async () => {
  stubApi('manager', [() => Response.json(EMPTY)])
  renderDashboards()
  await screen.findByText("Sync hasn't done anything on the mock channels yet.")
  expect(
    screen.getAllByText('No synthetic history is loaded, so there is nothing to chart yet.'),
  ).toHaveLength(3)
  expect(screen.getByText('No listing has gone up on the mock channels yet.')).toBeInTheDocument()
  expect(screen.getByText('No item has come through intake yet.')).toBeInTheDocument()
  expect(screen.queryByText(/items forwarded/)).not.toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  for (const chart of charts()) {
    expect(within(chart).getByText(/^Synthetic(, live| history)\.$/)).toBeInTheDocument()
  }
})

test('staff are told the dashboards are for managers, and nothing is fetched', async () => {
  const calls = stubApi('staff')
  renderDashboards()
  expect(await screen.findByText('Only a manager can see the dashboards.')).toBeInTheDocument()
  expect(calls).not.toContain('GET /dashboards')
})

test('a failed load can be tried again', async () => {
  stubApi('manager', [
    () => Response.json({ detail: 'The dashboards could not be loaded.' }, { status: 503 }),
    () => Response.json(LOADED),
  ])
  renderDashboards()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('The dashboards could not be loaded.')
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(
    await screen.findByRole('heading', { level: 2, name: 'Triage funnel' }),
  ).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
