import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { Attention, Flag } from '@/api/attention'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const DOUBLE = 'flag-double'
const STALE = 'flag-stale'

function flag(changes: Partial<Flag> = {}): Flag {
  return {
    id: DOUBLE,
    conflict: 'double_sale',
    message: 'Carhartt canvas jacket sold on Channel A and again on Channel B.',
    channel: 'channel_b',
    item_id: 'item-1',
    sku: 'RT11042601 12x12x6',
    title: 'Carhartt canvas jacket - Pre-owned',
    channel_listing_id: 'b-listing-1',
    channel_order_id: 'b-order-1',
    created_at: '2026-11-04T15:00:00Z',
    explanation:
      'Carhartt canvas jacket - Pre-owned sold on Channel A and then again on Channel B, but the store has only one to send.',
    suggested_fix:
      'Cancel the Channel B order, which refunds that buyer, so the Channel A buyer who paid first keeps the item.',
    explained_by: 'model',
    double_sale: {
      keep: {
        channel: 'channel_a',
        channel_order_id: 'a-order-1',
        price_cents: 4800,
        sold_at: '2026-11-04T14:58:00Z',
      },
      cancel: {
        channel: 'channel_b',
        channel_order_id: 'b-order-1',
        price_cents: 4500,
        sold_at: '2026-11-04T14:59:00Z',
      },
      cancelling: null,
    },
    resolved_at: null,
    resolved_by: null,
    resolution: null,
    ...changes,
  }
}

const STALE_FLAG = flag({
  id: STALE,
  conflict: 'stale_listing',
  channel: 'channel_a',
  channel_listing_id: 'a-listing-9',
  channel_order_id: null,
  explanation: 'The jacket is still up for sale on Channel A, but the item has already sold.',
  suggested_fix: 'End the listing on Channel A by hand, then mark this handled.',
  double_sale: null,
})

const RESOLVED = flag({
  id: 'flag-old',
  conflict: 'unknown_listing',
  title: null,
  sku: null,
  double_sale: null,
  resolved_at: '2026-11-03T10:00:00Z',
  resolved_by: null,
  resolution: 'Turnstone took the listing down.',
})

const CANCELLED = flag({
  resolved_at: '2026-11-04T15:05:00Z',
  resolved_by: 'Staff One',
  resolution: 'Cancelled the Channel B order, so the Channel A buyer keeps the item.',
  double_sale: null,
})

type Call = { key: string; body: unknown }

function stubApi(
  role: string,
  overrides: Record<string, () => Response> = {},
  attention: Attention = { open: [flag(), STALE_FLAG], resolved: [RESOLVED] },
) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const key = `${request.method} ${new URL(request.url).pathname}`
      const text = request.method === 'POST' ? await request.text() : ''
      calls.push({ key, body: text ? JSON.parse(text) : undefined })
      if (overrides[key]) return overrides[key]()
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      if (key === 'GET /attention') return Response.json(attention)
      if (key === `POST /attention/${DOUBLE}/fix`) return Response.json(CANCELLED)
      throw new Error(`unexpected ${key}`)
    }),
  )
  return calls
}

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderAttention() {
  render(
    <MemoryRouter initialEntries={['/app/attention']}>
      <App />
    </MemoryRouter>,
  )
}

// Opens a flag's details with its Review button, and searches that flag's row and details.
async function review(name: string) {
  const button = await screen.findByRole('button', { name: `Review ${name}` })
  fireEvent.click(button)
  return within(button.closest('tbody') as HTMLElement)
}

async function section(name: string) {
  const heading = await screen.findByRole('heading', { name })
  return within(heading.closest('section') as HTMLElement)
}

function flagRow(name: string) {
  return screen.queryByRole('button', { name: new RegExp(`^(Review|Close) ${name}$`) })
}

test.each(['staff', 'manager'])('%s see each flag with what to do about it', async (role) => {
  stubApi(role)
  renderAttention()
  const double = await review('Double sale')
  const doubleRow = within(
    screen.getByRole('button', { name: 'Close Double sale' }).closest('tr') as HTMLElement,
  )
  expect(doubleRow.getByText('Carhartt canvas jacket - Pre-owned')).toBeVisible()
  expect(doubleRow.getByText('RT11042601 12x12x6')).toBeVisible()
  expect(double.getByText(/but the store has only one to send\.$/)).toBeVisible()
  expect(double.getByText(/^Cancel the Channel B order, which refunds/)).toBeVisible()
  expect(double.getByText('Keeps the item').nextSibling).toHaveTextContent(
    /^Channel A, \$48\.00, sold /,
  )
  expect(double.getByText('Order to cancel').nextSibling).toHaveTextContent(
    /^Channel B, \$45\.00, sold /,
  )
  expect(double.getByRole('button', { name: 'Cancel the Channel B order' })).toBeEnabled()

  const stale = await review('Stale listing on Channel A')
  expect(double.queryByText('Keeps the item')).not.toBeInTheDocument()
  expect(stale.getByText('a-listing-9')).toBeVisible()
  expect(stale.queryByRole('button', { name: /^Cancel/ })).not.toBeInTheDocument()
  expect(stale.getByRole('button', { name: 'Mark handled' })).toBeEnabled()

  const handled = await section('Recently handled')
  expect(handled.getByText('Turnstone took the listing down.')).toBeVisible()
  expect(handled.getByText('Turnstone')).toBeVisible()
})

test('a double sale is fixed in one click', async () => {
  const calls = stubApi('staff')
  renderAttention()
  fireEvent.click(
    (await review('Double sale')).getByRole('button', { name: 'Cancel the Channel B order' }),
  )

  expect(
    await screen.findByText(
      'Handled. Cancelled the Channel B order, so the Channel A buyer keeps the item.',
    ),
  ).toBeVisible()
  expect(flagRow('Double sale')).not.toBeInTheDocument()
  const handled = await section('Recently handled')
  expect(handled.getByText('Staff One')).toBeVisible()
  expect(calls.filter((call) => call.key.endsWith('/fix'))).toEqual([
    { key: `POST /attention/${DOUBLE}/fix`, body: undefined },
  ])
})

test('a cancel the channel is down for is retried until it lands', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const retrying = flag({
    double_sale: {
      ...flag().double_sale!,
      cancelling: {
        status: 'pending',
        attempts: 1,
        max_attempts: 10,
        last_error: 'Channel B is down for now.',
      },
    },
  })
  let landed = false
  stubApi('staff', {
    [`POST /attention/${DOUBLE}/fix`]: () => Response.json(retrying),
    'GET /attention': () =>
      Response.json(
        landed
          ? { open: [STALE_FLAG], resolved: [CANCELLED] }
          : { open: [flag(), STALE_FLAG], resolved: [] },
      ),
  })
  try {
    renderAttention()
    const double = await review('Double sale')
    fireEvent.click(double.getByRole('button', { name: 'Cancel the Channel B order' }))
    expect(
      await double.findByText(
        "Try 1 of 10 didn't go through: Channel B is down for now. Turnstone tries again by itself.",
        { exact: false },
      ),
    ).toBeVisible()
    expect(
      double.queryByRole('button', { name: 'Cancel the Channel B order' }),
    ).not.toBeInTheDocument()

    landed = true
    await vi.advanceTimersByTimeAsync(3000)
    expect(await section('Recently handled')).toBeTruthy()
    expect(screen.getByText(CANCELLED.resolution!)).toBeVisible()
    expect(flagRow('Double sale')).not.toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

test('a cancel that stopped can be tried again', async () => {
  const stopped = flag({
    double_sale: {
      ...flag().double_sale!,
      cancelling: {
        status: 'failed',
        attempts: 10,
        max_attempts: 10,
        last_error: 'Channel B is down for now.',
      },
    },
  })
  stubApi('staff', {}, { open: [stopped], resolved: [] })
  renderAttention()
  const double = await review('Double sale')
  expect(double.getByRole('alert')).toHaveTextContent(
    "The Channel B order wasn't cancelled. Channel B is down for now.",
  )
  fireEvent.click(double.getByRole('button', { name: 'Cancel the Channel B order' }))
  expect(await screen.findByText(/^Handled\. Cancelled the Channel B order/)).toBeVisible()
})

test('a fix the API refuses stays on the screen with the reason', async () => {
  stubApi('staff', {
    [`POST /attention/${DOUBLE}/fix`]: () =>
      Response.json({ detail: 'Someone has already handled this.' }, { status: 409 }),
  })
  renderAttention()
  const double = await review('Double sale')
  fireEvent.click(double.getByRole('button', { name: 'Cancel the Channel B order' }))
  expect(await double.findByRole('alert')).toHaveTextContent('Someone has already handled this.')
  expect(double.getByRole('button', { name: 'Cancel the Channel B order' })).toBeEnabled()
})

test('any flag can be marked handled with a note on what was done', async () => {
  const calls = stubApi('staff', {
    [`POST /attention/${STALE}/resolve`]: () =>
      Response.json({
        ...STALE_FLAG,
        resolved_at: '2026-11-04T16:00:00Z',
        resolved_by: 'Staff One',
        resolution: 'Ended it on Channel A by hand.',
      }),
  })
  renderAttention()
  const stale = await review('Stale listing on Channel A')
  fireEvent.click(stale.getByRole('button', { name: 'Mark handled' }))
  fireEvent.change(stale.getByLabelText('What you did (optional)'), {
    target: { value: '  Ended it on Channel A by hand. ' },
  })
  fireEvent.click(stale.getByRole('button', { name: 'Mark handled' }))

  expect(await screen.findByText('Handled. Ended it on Channel A by hand.')).toBeVisible()
  expect(flagRow('Stale listing on Channel A')).not.toBeInTheDocument()
  expect(calls.find((call) => call.key.endsWith('/resolve'))?.body).toEqual({
    note: 'Ended it on Channel A by hand.',
  })
})

test('marking handled can be backed out of', async () => {
  stubApi('staff')
  renderAttention()
  const stale = await review('Stale listing on Channel A')
  fireEvent.click(stale.getByRole('button', { name: 'Mark handled' }))
  fireEvent.click(stale.getByRole('button', { name: 'Keep it open' }))
  expect(stale.queryByLabelText('What you did (optional)')).not.toBeInTheDocument()
})

test('an explanation still being written shows the fixed text, then the written one', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const answers: Attention[] = [
    { open: [flag({ explained_by: null })], resolved: [] },
    {
      open: [flag({ explanation: 'The jacket sold twice, and there is only one.' })],
      resolved: [],
    },
  ]
  stubApi('staff', { 'GET /attention': () => Response.json(answers.shift() ?? answers.at(-1)) })
  try {
    renderAttention()
    const double = await review('Double sale')
    expect(double.getByText(/but the store has only one to send\.$/)).toBeVisible()
    await vi.advanceTimersByTimeAsync(3000)
    expect(await double.findByText('The jacket sold twice, and there is only one.')).toBeVisible()
  } finally {
    vi.useRealTimers()
  }
})

test('nothing open says so', async () => {
  stubApi('staff', {}, { open: [], resolved: [] })
  renderAttention()
  expect(await screen.findByText('Nothing needs attention right now.')).toBeVisible()
  expect(screen.queryByRole('heading', { name: 'Recently handled' })).not.toBeInTheDocument()
})

test('a screen that fails to load can be tried again', async () => {
  let fail = true
  stubApi('staff', {
    'GET /attention': () =>
      fail
        ? Response.json({ detail: 'The database is down.' }, { status: 503 })
        : Response.json({ open: [], resolved: [] }),
  })
  renderAttention()
  expect(await screen.findByRole('alert')).toHaveTextContent('The database is down.')
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.getByText('Nothing needs attention right now.')).toBeVisible())
})
