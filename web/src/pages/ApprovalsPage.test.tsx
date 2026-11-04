import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { ApprovalQueue, BoxSizeOption, ItemReview, ListingReview } from '@/api/approval'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const ITEM = '0b6c6f3e-6f43-4c4f-9a39-0e4c1a0f2b11'
const SENT_AT = '2026-11-04T15:00:00+00:00'

function listing(changes: Partial<ListingReview> = {}): ListingReview {
  return {
    channel: 'channel_a',
    title: 'Carhartt canvas jacket - Pre-owned',
    description: 'Brown Carhartt canvas jacket, pre-owned.',
    category: 'Unisex Clothing',
    state: 'awaiting_approval',
    flags: [],
    base_price_cents: 5160,
    price_override_cents: null,
    price_cents: 5160,
    net_after_fees_cents: 4268,
    channel_status: null,
    channel_detail: null,
    ...changes,
  }
}

function review(changes: Partial<ItemReview> = {}): ItemReview {
  return {
    item_id: ITEM,
    sku: 'RT11042601',
    full_sku: null,
    status: 'appraised',
    release_month: null,
    category: 'apparel',
    brand: 'Carhartt',
    product: 'canvas jacket',
    condition: 'pre_owned',
    appraisal: {
      id: 'a1',
      price_low_cents: 4000,
      price_typical_cents: 5160,
      price_high_cents: 6000,
      confidence: 'high',
      recommendation: 'yes',
    },
    listings: [
      listing(),
      listing({ channel: 'channel_b', category: 'Unisex', net_after_fees_cents: 3978 }),
    ],
    package_weight_oz: null,
    billed_weight_oz: null,
    box_code: null,
    location_code: null,
    submitted_by_name: 'Demo Staff',
    submitted_at: SENT_AT,
    blockers: ['Enter the package weight and box size, which Channel A needs before approval.'],
    ...changes,
  }
}

const QUEUE: ApprovalQueue = {
  awaiting_approval: [
    {
      item_id: ITEM,
      sku: 'RT11042601',
      full_sku: null,
      status: 'appraised',
      brand: 'Carhartt',
      product: 'canvas jacket',
      channels: ['channel_a', 'channel_b'],
      waiting_since: SENT_AT,
    },
  ],
  awaiting_storage: [],
}

const BOXES: BoxSizeOption[] = [
  { code: '10x13', kind: 'mailer', length_in: 13, width_in: 10, height_in: null },
  { code: '12x12x6', kind: 'box', length_in: 12, width_in: 12, height_in: 6 },
]

type Call = { method: string; path: string; body: unknown }
type Handler = (body: unknown) => Response | Promise<Response>

function stubApi({
  role = 'manager',
  overrides = {},
}: { role?: string; overrides?: Record<string, Handler> } = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      const key = `${request.method} ${path}`
      const text = await request.clone().text()
      const body = text ? (JSON.parse(text) as unknown) : undefined
      calls.push({ method: request.method, path, body })
      if (overrides[key]) return overrides[key](body)
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      if (key === 'GET /approvals') return Response.json(QUEUE)
      if (key === `GET /items/${ITEM}/review`) return Response.json(review())
      if (key === 'GET /settings/box-sizes') return Response.json(BOXES)
      throw new Error(`unexpected ${key}`)
    }),
  )
  return calls
}

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

async function panel(name: string) {
  const heading = await screen.findByRole('heading', { level: 2, name })
  return within(heading.closest('section') as HTMLElement)
}

test('the queue lists what staff sent on and what is waiting for a shelf', async () => {
  stubApi()
  renderAt('/app/approvals')
  const waiting = await panel('Waiting for approval')
  expect(waiting.getByRole('link', { name: 'Carhartt canvas jacket' })).toHaveAttribute(
    'href',
    `/app/approvals/${ITEM}`,
  )
  expect(waiting.getByText('RT11042601, for Channel A and Channel B')).toBeInTheDocument()
  const shelf = await panel('Waiting for a shelf')
  expect(shelf.getByText('Every approved item is on a shelf.')).toBeInTheDocument()
})

test('staff are refused without asking the API for the queue', async () => {
  const calls = stubApi({ role: 'staff' })
  renderAt('/app/approvals')
  expect(
    await screen.findByText('Only a manager can approve listings and store items.'),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.path === '/approvals')).toBe(false)
})

test('a queue that fails to load can be tried again', async () => {
  let fail = true
  stubApi({
    overrides: {
      'GET /approvals': () =>
        fail
          ? Response.json({ detail: 'The database is down.' }, { status: 503 })
          : Response.json(QUEUE),
    },
  })
  renderAt('/app/approvals')
  expect(await screen.findByRole('alert')).toHaveTextContent('The database is down.')
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('link', { name: 'Carhartt canvas jacket' })).toBeInTheDocument()
})

test('the review shows each listing with its price and net after fees', async () => {
  stubApi()
  renderAt(`/app/approvals/${ITEM}`)
  expect(
    await screen.findByRole('heading', { level: 1, name: 'Carhartt canvas jacket' }),
  ).toBeInTheDocument()
  const a = await panel('Channel A')
  expect(a.getByText('Left after Channel A fees').nextElementSibling).toHaveTextContent('$42.68')
  const b = await panel('Channel B')
  expect(b.getByText('Left after Channel B fees').nextElementSibling).toHaveTextContent('$39.78')
  const decision = await panel('Approve or reject')
  expect(decision.getByRole('button', { name: 'Approve' })).toBeDisabled()
  expect(
    decision.getByText(
      'Enter the package weight and box size, which Channel A needs before approval.',
    ),
  ).toBeInTheDocument()
})

test('a price override is sent as cents, and an empty one goes back to the typical price', async () => {
  const calls = stubApi({
    overrides: {
      [`PUT /items/${ITEM}/listings/channel_b/price`]: (body) => {
        const cents = (body as { price_override_cents: number | null }).price_override_cents
        return Response.json(
          review({
            listings: [
              listing(),
              listing({
                channel: 'channel_b',
                price_override_cents: cents,
                price_cents: cents ?? 5160,
                net_after_fees_cents: cents === null ? 3978 : cents - 295 - 150,
              }),
            ],
          }),
        )
      },
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  let b = await panel('Channel B')
  fireEvent.change(b.getByLabelText('Price for Channel B'), { target: { value: '12' } })
  fireEvent.click(b.getByRole('button', { name: 'Save the price' }))
  await waitFor(async () =>
    expect(
      (await panel('Channel B')).getByText('Left after Channel B fees').nextElementSibling,
    ).toHaveTextContent('$7.55'),
  )
  b = await panel('Channel B')
  expect(b.getByLabelText('Price for Channel B')).toHaveValue('12.00')
  fireEvent.change(b.getByLabelText('Price for Channel B'), { target: { value: '' } })
  fireEvent.click(b.getByRole('button', { name: 'Save the price' }))
  await waitFor(() =>
    expect(calls.filter((call) => call.method === 'PUT').map((call) => call.body)).toEqual([
      { price_override_cents: 1200 },
      { price_override_cents: null },
    ]),
  )
})

test('a price that is not dollars is caught before the API is called', async () => {
  const calls = stubApi()
  renderAt(`/app/approvals/${ITEM}`)
  const a = await panel('Channel A')
  fireEvent.change(a.getByLabelText('Price for Channel A'), { target: { value: 'ten' } })
  fireEvent.click(a.getByRole('button', { name: 'Save the price' }))
  expect(
    await a.findByText('Enter the price in dollars, such as 45.00, or leave it empty.'),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test('the package unblocks approval, and approval asks for the shelf', async () => {
  const packed = review({
    package_weight_oz: 22.4,
    box_code: '12x12x6',
    full_sku: 'RT11042601 12x12x6',
    billed_weight_oz: 32,
    blockers: [],
  })
  const calls = stubApi({
    overrides: {
      [`PUT /items/${ITEM}/storage`]: () => Response.json(packed),
      [`POST /items/${ITEM}/approve`]: () =>
        Response.json({
          ...packed,
          status: 'approved',
          listings: packed.listings.map((row) => ({ ...row, state: 'approved' })),
        }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const pack = await panel('Package')
  expect(within(pack.getByLabelText('Box size')).getAllByRole('option')).toHaveLength(3)
  expect(pack.queryByLabelText('Shelf or bin')).not.toBeInTheDocument()
  fireEvent.change(pack.getByLabelText('Package weight (oz)'), { target: { value: '22.4' } })
  fireEvent.change(pack.getByLabelText('Box size'), { target: { value: '12x12x6' } })
  fireEvent.click(pack.getByRole('button', { name: 'Save the package' }))
  expect(await screen.findByText('The label is billed at 2 lb.')).toBeInTheDocument()
  expect(screen.getByText('RT11042601 12x12x6')).toBeInTheDocument()
  expect(pack.getByText('Saved.')).toBeInTheDocument()
  fireEvent.change(pack.getByLabelText('Package weight (oz)'), { target: { value: '22.5' } })
  expect(pack.queryByText('Saved.')).not.toBeInTheDocument()
  fireEvent.change(pack.getByLabelText('Package weight (oz)'), { target: { value: '22.4' } })

  fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
  expect(
    await screen.findByText('Approved. Enter its shelf or bin below to store it.'),
  ).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Approve or reject' })).not.toBeInTheDocument()
  const shelf = await panel('Package and shelf')
  expect(shelf.getByLabelText('Shelf or bin')).toBeInTheDocument()
  expect(shelf.queryByText('Saved.')).not.toBeInTheDocument()
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
    package_weight_oz: 22.4,
    box_code: '12x12x6',
    location_code: null,
  })
})

test('storing an approved item sends its shelf', async () => {
  const approved = review({
    status: 'approved',
    package_weight_oz: 22.4,
    box_code: '12x12x6',
    full_sku: 'RT11042601 12x12x6',
    billed_weight_oz: 32,
    blockers: [],
    listings: [listing({ state: 'approved' })],
  })
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(approved),
      [`PUT /items/${ITEM}/storage`]: () => Response.json({ ...approved, location_code: 'B12-2' }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const shelf = await panel('Package and shelf')
  expect((await panel('Channel A')).queryByLabelText('Price for Channel A')).toBeNull()
  fireEvent.click(shelf.getByRole('button', { name: 'Save and store' }))
  expect(await shelf.findByText('Enter the shelf or bin code, such as A3.')).toBeInTheDocument()
  fireEvent.change(shelf.getByLabelText('Shelf or bin'), { target: { value: 'b12 - 2' } })
  fireEvent.click(shelf.getByRole('button', { name: 'Save and store' }))
  expect(await screen.findByText('Stored on B12-2 as RT11042601 12x12x6.')).toBeInTheDocument()
  expect(shelf.getByText('Stored on B12-2.')).toBeInTheDocument()
  expect(shelf.getByLabelText('Shelf or bin')).toHaveValue('B12-2')
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
    package_weight_oz: 22.4,
    box_code: '12x12x6',
    location_code: 'b12 - 2',
  })
})

test('a stored item follows its listings onto the channels', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const stored = (status: 'pending' | 'active') =>
    review({
      status: status === 'pending' ? 'approved' : 'listed',
      package_weight_oz: 22.4,
      box_code: '12x12x6',
      location_code: 'B12',
      full_sku: 'RT11042601 12x12x6',
      blockers: [],
      listings: [
        listing({ state: 'approved', channel_status: status }),
        listing({
          channel: 'channel_b',
          category: 'Unisex',
          state: 'approved',
          channel_status: 'rejected',
          channel_detail: 'Channel B refused it: Channel B needs a brand.',
        }),
      ],
    })
  const reviews = [stored('pending'), stored('active')]
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(reviews.shift() ?? stored('active')),
    },
  })
  try {
    renderAt(`/app/approvals/${ITEM}`)
    const a = await panel('Channel A')
    expect(a.getByText('Being listed on Channel A...')).toBeInTheDocument()
    expect(
      (await panel('Channel B')).getByText('Channel B refused it: Channel B needs a brand.'),
    ).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(2000)
    expect(await a.findByText('Live on Channel A.')).toBeInTheDocument()
    expect(screen.getByText('Stored on B12 as RT11042601 12x12x6.')).toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

test('a listing a channel could not take can be sent again', async () => {
  const listed = (status: 'failed' | 'active') =>
    review({
      status: 'listed',
      location_code: 'B12',
      blockers: [],
      listings: [
        listing({ state: 'approved', channel_status: 'active' }),
        listing({
          channel: 'channel_b',
          category: 'Unisex',
          state: 'approved',
          channel_status: status,
          channel_detail: status === 'failed' ? "Channel B couldn't be reached." : null,
        }),
      ],
    })
  let sent = false
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(listed(sent ? 'active' : 'failed')),
      [`POST /items/${ITEM}/listings`]: () => {
        sent = true
        return Response.json([])
      },
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const b = await panel('Channel B')
  expect(
    b.getByText("Channel B couldn't take it after several tries. Channel B couldn't be reached."),
  ).toBeInTheDocument()
  expect((await panel('Channel A')).queryByRole('button')).toBeNull()
  fireEvent.click(b.getByRole('button', { name: 'Try Channel B again' }))
  expect(await b.findByText('Live on Channel B.')).toBeInTheDocument()
  expect(calls.filter((call) => call.method === 'POST')).toHaveLength(1)
})

test('a listing that cannot be sent again says why', async () => {
  const failed = review({
    status: 'listed',
    location_code: 'B12',
    blockers: [],
    listings: [listing({ state: 'approved', channel_status: 'failed', channel_detail: null })],
  })
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(failed),
      [`POST /items/${ITEM}/listings`]: () =>
        Response.json({ detail: 'Channel A has no price.' }, { status: 409 }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const a = await panel('Channel A')
  fireEvent.click(a.getByRole('button', { name: 'Try Channel A again' }))
  expect(await a.findByRole('alert')).toHaveTextContent('Channel A has no price.')
  expect(a.getByRole('button', { name: 'Try Channel A again' })).toBeEnabled()
})

test('a rejection needs a reason and then skips the package', async () => {
  const calls = stubApi({
    overrides: {
      [`POST /items/${ITEM}/reject`]: () =>
        Response.json(
          review({
            status: 'declined',
            blockers: [],
            listings: review().listings.map((row) => ({ ...row, state: 'rejected' })),
          }),
        ),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const decision = await panel('Approve or reject')
  fireEvent.click(decision.getByRole('button', { name: 'Reject' }))
  expect(await decision.findByText('Enter why you are rejecting it.')).toBeInTheDocument()
  fireEvent.change(decision.getByLabelText('Why you are rejecting it'), {
    target: { value: 'Too worn' },
  })
  fireEvent.click(decision.getByRole('button', { name: 'Reject' }))
  expect(
    await screen.findByText(
      'Rejected. Staff can say yes again to fix the listing and send it back.',
    ),
  ).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Package' })).not.toBeInTheDocument()
  expect(calls.find((call) => call.method === 'POST')?.body).toEqual({
    reason: 'Too worn',
    note: null,
  })
})

test("the API's reason for refusing approval is shown", async () => {
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(review({ blockers: [] })),
      [`POST /items/${ITEM}/approve`]: () =>
        Response.json({ detail: 'Only a manager can do this.' }, { status: 403 }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Only a manager can do this.')
})

test('a held item shows its release month', async () => {
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () =>
        Response.json(review({ status: 'held_for_season', release_month: '2027-09-01' })),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  expect(await screen.findByText('Approved and held for its season')).toBeInTheDocument()
  expect(screen.getByText('September 2027')).toBeInTheDocument()
})

test('staff are refused the review without asking the API', async () => {
  const calls = stubApi({ role: 'staff' })
  renderAt(`/app/approvals/${ITEM}`)
  expect(
    await screen.findByText('Only a manager can approve listings and store items.'),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.path.startsWith('/items'))).toBe(false)
  expect(screen.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/app')
})
