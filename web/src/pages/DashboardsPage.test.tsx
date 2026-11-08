import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type {
  Category,
  Dashboards,
  FunnelCounts,
  InsightAnswer,
  SyncHealth,
} from '@/api/dashboards'
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

function stubApi(
  role: string,
  answers: (() => Response)[] = [() => Response.json(LOADED)],
  asks: (() => Response)[] = [],
) {
  const calls: string[] = []
  const questions: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const key = `${request.method} ${new URL(request.url).pathname}`
      calls.push(key)
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      // Each load takes the next answer, and the last one keeps coming after that.
      if (key === 'GET /dashboards') return (answers.length > 1 ? answers.shift()! : answers[0])()
      if (key === 'POST /dashboards/ask') {
        questions.push(((await request.json()) as { question: string }).question)
        return (asks.length > 1 ? asks.shift()! : asks[0])()
      }
      throw new Error(`unexpected ${key}`)
    }),
  )
  return Object.assign(calls, { questions })
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

// Radix tabs open on mouse down.
function openView(name: string) {
  fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0 })
}

const VIEWS = ['Time to sell', 'Seasonality', 'Triage funnel', 'Sync']

test('a manager sees the four views as tabs, with every chart saying where its numbers come from', async () => {
  stubApi('manager')
  renderDashboards()
  const tabs = await screen.findByRole('tablist', { name: 'Dashboard views' })
  expect(
    within(tabs)
      .getAllByRole('tab')
      .map((tab) => tab.textContent),
  ).toEqual(VIEWS)
  expect(screen.getByRole('heading', { name: 'Ask about sales' })).toBeInTheDocument()
  expect(screen.getByText(/^Demo data: past sales are made up/)).toBeInTheDocument()

  const headings: string[] = []
  const sources: string[] = []
  for (const view of VIEWS) {
    openView(view)
    const panel = screen.getByRole('tabpanel')
    headings.push(within(panel).getByRole('heading', { level: 2 }).textContent ?? '')
    for (const chart of within(panel).getAllByRole('figure')) {
      const labels = within(chart).queryAllByText(/^(Demo history|Live test sales)$/)
      // Each chart has one label, so synthetic history and live test sales never share a chart.
      expect(labels).toHaveLength(1)
      sources.push(labels[0].textContent ?? '')
    }
  }
  expect(headings).toEqual([
    'Time to sell by category and price',
    'Seasonality by category',
    'Triage funnel',
    'Sync health and agreement',
  ])
  expect(sources.filter((source) => source === 'Demo history')).toHaveLength(5)
  expect(sources.filter((source) => source === 'Live test sales')).toHaveLength(4)
})

test('the headline numbers are the live counts, tagged as live test sales', async () => {
  stubApi('manager')
  renderDashboards()
  const glance = await screen.findByRole('region', { name: 'At a glance' })
  expect(within(glance).getByText('Live test sales')).toBeInTheDocument()
  const value = (label: string) => within(glance).getByText(label).nextElementSibling
  expect(value('Taken in')).toHaveTextContent('1')
  expect(value('Listed on the sales channels')).toHaveTextContent('1')
  expect(value('Sold')).toHaveTextContent('1')
  expect(value('Sold twice')).toHaveTextContent('0')
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
  openView('Triage funnel')
  expect(
    screen.getAllByText('Staff went against a yes or a no on 9 of 90 calls, 10%.', {
      exact: false,
    }),
  ).toHaveLength(2)
})

test('with nothing loaded or sold, each view says so instead of drawing empty charts', async () => {
  stubApi('manager', [() => Response.json(EMPTY)])
  renderDashboards()
  await screen.findByRole('tablist', { name: 'Dashboard views' })
  let noHistory = 0
  for (const view of VIEWS) {
    openView(view)
    noHistory += screen.queryAllByText('There is no sales history to chart yet.').length
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    for (const chart of charts()) {
      expect(within(chart).getByText(/^(Demo history|Live test sales)$/)).toBeInTheDocument()
    }
    if (view === 'Time to sell')
      expect(screen.getByText('No listings have gone up yet.')).toBeInTheDocument()
    if (view === 'Triage funnel')
      expect(screen.getByText('No item has come through intake yet.')).toBeInTheDocument()
    if (view === 'Sync')
      expect(screen.getByText("Sync hasn't done anything yet.")).toBeInTheDocument()
  }
  expect(noHistory).toBe(3)
})

test('staff are told the dashboards are for managers, and nothing is fetched', async () => {
  const calls = stubApi('staff')
  renderDashboards()
  expect(await screen.findByText('Only a manager can see the dashboards.')).toBeInTheDocument()
  expect(calls).not.toContain('GET /dashboards')
  expect(screen.queryByRole('heading', { name: 'Ask about sales' })).not.toBeInTheDocument()
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
  expect(await screen.findByRole('tab', { name: 'Triage funnel' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

const ANSWER: InsightAnswer = {
  question: 'How fast does apparel around $40 sell?',
  answer: 'In the synthetic history, 23 of 92 apparel listings at $30 to $49.99 sold.',
  written_by: 'model',
  fallback_reason: null,
  rejected_numbers: [],
  query: { function: 'time_to_sell', category: 'apparel', price_band: 2, month: null },
  call: 'time_to_sell(category="apparel", price_band=2)',
  source: 'history',
  facts: [
    { label: 'Listed', value: '92' },
    { label: 'Middle days to sell', value: '51 days' },
  ],
  model_name: 'primary',
}

async function askQuestion(question: string) {
  const input = await screen.findByLabelText('Your question')
  fireEvent.change(input, { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

function answers() {
  const section = screen.getByRole('region', { name: 'Ask about sales' })
  return within(section).queryAllByRole('article')
}

test('an answer shows the function and inputs it came from, labeled like the charts', async () => {
  const calls = stubApi('manager', undefined, [() => Response.json(ANSWER)])
  renderDashboards()
  await askQuestion('  How fast does apparel around $40 sell?  ')
  expect(
    screen.getByText('Working out the answer to “How fast does apparel around $40 sell?”...'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Asking...' })).toBeDisabled()

  const answer = await screen.findByRole('article', { name: ANSWER.question })
  expect(calls.questions).toEqual(['How fast does apparel around $40 sell?'])
  expect(within(answer).getByText(ANSWER.answer)).toBeInTheDocument()
  expect(within(answer).getByText('Demo history')).toBeInTheDocument()
  expect(within(answer).getByText(ANSWER.call!)).toBeInTheDocument()
  expect(within(answer).getByText(/^Worked out with/)).toBeInTheDocument()
  expect(
    within(answer).getByRole('row', { name: 'Middle days to sell 51 days' }),
  ).toBeInTheDocument()
  expect(screen.getByLabelText('Your question')).toHaveValue('')
})

test('an answer from the mock channels says so, and newer answers come last, as in a chat', async () => {
  const live: InsightAnswer = {
    ...ANSWER,
    question: 'How many have sold for real?',
    answer: 'In Turnstone, 1 item has sold, from test sales rather than real buyers.',
    query: { function: 'live_sales', category: null, price_band: null, month: null },
    call: 'live_sales()',
    source: 'live',
  }
  stubApi('manager', undefined, [() => Response.json(ANSWER), () => Response.json(live)])
  renderDashboards()
  await askQuestion(ANSWER.question)
  await screen.findByRole('article', { name: ANSWER.question })
  await askQuestion(live.question)

  const newest = await screen.findByRole('article', { name: live.question })
  expect(within(newest).getByText('Live test sales')).toBeInTheDocument()
  expect(answers().at(-1)).toBe(newest)
  expect(answers()).toHaveLength(2)
})

test('an answer whose wording was refused says which numbers code did not return', async () => {
  stubApi('manager', undefined, [
    () =>
      Response.json({
        ...ANSWER,
        written_by: 'code',
        fallback_reason: 'flagged',
        rejected_numbers: ['11', '40'],
      }),
  ])
  renderDashboards()
  await askQuestion(ANSWER.question)

  const answer = await screen.findByRole('article', { name: ANSWER.question })
  expect(answer).toHaveTextContent(
    "The model's wording had 11 and 40, which the function didn't return, so this is the function's own sentence instead.",
  )
})

test('a question no function covers gets a plain answer with no source or call', async () => {
  stubApi('manager', undefined, [
    () =>
      Response.json({
        ...ANSWER,
        question: 'Who is our best volunteer?',
        answer:
          "None of the questions I can answer cover that, so I can't give you a number for it.",
        written_by: 'code',
        query: null,
        call: null,
        source: null,
        facts: [],
      }),
  ])
  renderDashboards()
  await askQuestion('Who is our best volunteer?')

  const answer = await screen.findByRole('article', { name: 'Who is our best volunteer?' })
  expect(answer).toHaveTextContent('None of the questions I can answer cover that')
  expect(within(answer).queryByText(/^(Demo history|Live test sales)$/)).not.toBeInTheDocument()
  expect(within(answer).queryByText(/^Worked out with/)).not.toBeInTheDocument()
  expect(within(answer).queryByText('Show the numbers')).not.toBeInTheDocument()
})

test('Enter asks the question, and Shift+Enter starts a new line instead', async () => {
  const calls = stubApi('manager', undefined, [() => Response.json(ANSWER)])
  renderDashboards()
  const input = await screen.findByLabelText('Your question')
  fireEvent.change(input, { target: { value: ANSWER.question } })
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
  expect(calls.questions).toEqual([])
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(await screen.findByRole('article', { name: ANSWER.question })).toBeInTheDocument()
  expect(calls.questions).toEqual([ANSWER.question])
})

test('an empty question is not sent', async () => {
  const calls = stubApi('manager')
  renderDashboards()
  await askQuestion('   ')

  expect(await screen.findByText('Type a question first.')).toBeInTheDocument()
  expect(calls).not.toContain('POST /dashboards/ask')
})

test('a question the model could not answer can be asked again', async () => {
  const calls = stubApi('manager', undefined, [
    () =>
      Response.json(
        { detail: "The language model couldn't be reached, so the question wasn't answered." },
        { status: 502 },
      ),
    () => Response.json(ANSWER),
  ])
  renderDashboards()
  await askQuestion(ANSWER.question)

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent("The language model couldn't be reached")
  expect(alert).toHaveTextContent(`You asked “${ANSWER.question}”.`)
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('article', { name: ANSWER.question })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(calls.questions).toEqual([ANSWER.question, ANSWER.question])
})
