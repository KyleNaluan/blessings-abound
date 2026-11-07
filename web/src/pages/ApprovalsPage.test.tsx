import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type {
  ApprovalQueue,
  BoxSizeOption,
  ItemReview,
  KeptOffItem,
  ListingReview,
  QueueItem,
} from '@/api/approval'
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
    approved_by_name: null,
    approved_at: null,
    back_for_review: false,
    put_back: false,
    fresh_appraisal: null,
    history: [
      {
        decision: 'yes',
        reason: null,
        note: null,
        decided_by_name: 'Demo Staff',
        decided_at: SENT_AT,
      },
    ],
    ...changes,
  }
}

const APPROVED_AT = '2026-11-05T16:00:00+00:00'

// An item approved in November and held for March, with its listings approved and its shelf.
function heldReview(changes: Partial<ItemReview> = {}): ItemReview {
  return review({
    status: 'held_for_season',
    release_month: '2027-03-01',
    full_sku: 'RT11042601-12x12x6',
    package_weight_oz: 22.4,
    box_code: '12x12x6',
    location_code: 'C1',
    blockers: [],
    approved_by_name: 'Demo Manager',
    approved_at: APPROVED_AT,
    listings: [
      listing({ state: 'approved' }),
      listing({
        channel: 'channel_b',
        state: 'approved',
        category: 'Unisex',
        net_after_fees_cents: 3978,
      }),
    ],
    history: [
      {
        decision: 'yes',
        reason: 'wrong_comps',
        note: null,
        decided_by_name: 'Demo Staff',
        decided_at: SENT_AT,
      },
      {
        decision: 'yes',
        reason: 'Approved and held for its season until March 2027',
        note: null,
        decided_by_name: 'Demo Manager',
        decided_at: APPROVED_AT,
      },
    ],
    ...changes,
  })
}

const FRESH = {
  id: 'a2',
  item_id: ITEM,
  price_low_cents: 3800,
  price_typical_cents: 4700,
  price_high_cents: 5600,
  net_after_fees_cents: 3890,
  comps_count: 2,
  confidence: 'medium',
  recommendation: 'yes',
  rules_config: {
    pricing: { ask_to_sale_factor: 0.645 },
    search: { outcome: 'priced', queries: ['carhartt canvas jacket'] },
  },
  explanation: 'The expected sale price is $47.00.',
  comps: [
    {
      title: 'Carhartt canvas jacket, brown',
      asking_cents: 6900,
      condition: 'Pre-Owned',
      url: 'https://www.ebay.com/itm/1',
      outlier: false,
    },
    {
      title: 'Carhartt duck jacket',
      asking_cents: 7600,
      condition: 'Pre-Owned',
      url: 'https://www.ebay.com/itm/2',
      outlier: false,
    },
  ],
  created_at: '2027-03-02T15:00:00+00:00',
} satisfies ItemReview['fresh_appraisal']

const HELD: QueueItem = {
  item_id: ITEM,
  sku: 'RT11042601',
  full_sku: 'RT11042601-12x12x6',
  status: 'held_for_season',
  brand: 'Carhartt',
  product: 'canvas jacket',
  channels: ['channel_a', 'channel_b'],
  waiting_since: APPROVED_AT,
  release_month: '2027-03-01',
  location_code: 'C1',
  back_for_review: false,
  put_back: false,
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
      release_month: null,
      location_code: null,
      back_for_review: false,
      put_back: false,
    },
  ],
  awaiting_storage: [],
  held_for_season: [],
  not_listed_online: [],
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

test('the held list says when each item comes back and where it is', async () => {
  stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], held_for_season: [HELD] }),
    },
  })
  renderAt('/app/approvals')
  const held = await panel('Held for season')
  expect(held.getByRole('link', { name: 'Carhartt canvas jacket' })).toHaveAttribute(
    'href',
    `/app/approvals/${ITEM}`,
  )
  expect(held.getByText('Held until March 2027, stored on C1')).toBeInTheDocument()
  expect(
    (await panel('Waiting for approval')).getByText('Nothing is waiting for approval.'),
  ).toBeInTheDocument()
})

test('the held list says when nothing is held', async () => {
  stubApi()
  renderAt('/app/approvals')
  expect(
    (await panel('Held for season')).getByText('No item is held for its season.'),
  ).toBeInTheDocument()
})

test('List now sends a held item into its review', async () => {
  const calls = stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], held_for_season: [HELD] }),
      [`POST /items/${ITEM}/list-now`]: () =>
        Response.json(heldReview({ back_for_review: true, release_month: '2026-11-01' })),
      [`GET /items/${ITEM}/review`]: () =>
        Response.json(heldReview({ back_for_review: true, release_month: '2026-11-01' })),
      [`POST /items/${ITEM}/fresh-comps`]: () =>
        Response.json(
          heldReview({
            back_for_review: true,
            release_month: '2026-11-01',
            fresh_appraisal: FRESH,
          }),
        ),
    },
  })
  renderAt('/app/approvals')
  fireEvent.click((await panel('Held for season')).getByRole('button', { name: 'List now' }))

  expect(await screen.findByText('Back for review in its season')).toBeInTheDocument()
  expect(calls.filter((call) => call.path.endsWith('/list-now'))).toHaveLength(1)
})

test('a held item can be taken out of online selling with a note', async () => {
  const calls = stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], held_for_season: [HELD] }),
      [`POST /items/${ITEM}/not-online`]: (body) =>
        Response.json({
          item_id: ITEM,
          status: 'not_listed_online',
          note: (body as { note: string }).note,
          decided_by_name: 'Demo Manager',
          decided_at: '2026-11-06T15:00:00+00:00',
        }),
    },
  })
  renderAt('/app/approvals')
  const held = await panel('Held for season')
  fireEvent.click(held.getByRole('button', { name: "Don't list online" }))
  fireEvent.click(held.getByRole('button', { name: "Don't list online" }))
  expect(
    held.getByText("Enter why it isn't going online, such as to sell it on the store floor."),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/not-online'))).toBe(false)

  fireEvent.change(held.getByLabelText("Why it isn't going online"), {
    target: { value: ' Selling it on the floor this winter. ' },
  })
  fireEvent.click(held.getByRole('button', { name: "Don't list online" }))

  expect(
    await screen.findByText(
      "Carhartt canvas jacket won't be listed online, and it's under Not listed online if it needs to go back.",
    ),
  ).toBeInTheDocument()
  expect(held.getByText('No item is held for its season.')).toBeInTheDocument()
  expect(calls.find((call) => call.path.endsWith('/not-online'))?.body).toEqual({
    note: 'Selling it on the floor this winter.',
  })
  // It can be put back straight away from the list it moved to.
  const kept = await panel('Not listed online')
  expect(kept.getByText('Selling it on the floor this winter.')).toBeInTheDocument()
  expect(kept.getByRole('button', { name: 'Put back for review' })).toBeInTheDocument()
})

test('a held item not yet due can be sent to review from its own page', async () => {
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(heldReview()),
      [`POST /items/${ITEM}/list-now`]: () =>
        Response.json(heldReview({ back_for_review: true, release_month: '2026-11-01' })),
      [`POST /items/${ITEM}/fresh-comps`]: () =>
        Response.json(
          heldReview({
            back_for_review: true,
            release_month: '2026-11-01',
            fresh_appraisal: FRESH,
          }),
        ),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const held = await panel('Held until March 2027')
  expect(screen.queryByRole('heading', { name: 'Approve or reject' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Price for Channel A')).not.toBeInTheDocument()
  expect(await panel("Don't list online")).toBeTruthy()

  fireEvent.click(held.getByRole('button', { name: 'List now' }))

  expect(await panel('What it sells for now')).toBeTruthy()
  expect(calls.filter((call) => call.path.endsWith('/fresh-comps'))).toHaveLength(1)
})

test('a held item back for review shows fresh sales beside the approved prices', async () => {
  let answer = () => {}
  const looked = new Promise<void>((resolve) => (answer = resolve))
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(heldReview({ back_for_review: true })),
      // Held until the test has seen the page looking it up.
      [`POST /items/${ITEM}/fresh-comps`]: async () => {
        await looked
        return Response.json(heldReview({ back_for_review: true, fresh_appraisal: FRESH }))
      },
      [`POST /items/${ITEM}/approve`]: () =>
        Response.json(
          heldReview({
            status: 'approved',
            listings: [
              listing({ state: 'approved', channel_status: 'active' }),
              listing({ channel: 'channel_b', state: 'approved', channel_status: 'active' }),
            ],
          }),
        ),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  expect(
    await screen.findByText('Looking up what similar items sell for now...'),
  ).toBeInTheDocument()
  answer()

  // The panel is drawn again once the lookup answers, so it's found after that.
  await screen.findByText('Typical sale price now')
  const fresh = await panel('What it sells for now')
  expect(fresh.getByText('Typical sale price when approved').nextElementSibling).toHaveTextContent(
    '$51.60',
  )
  expect(fresh.getByText('Typical sale price now').nextElementSibling).toHaveTextContent('$47.00')
  expect(fresh.getByRole('link', { name: 'Carhartt duck jacket' })).toBeInTheDocument()
  expect(screen.getByText('Approved by').nextElementSibling).toHaveTextContent('Demo Manager')
  // The approved price can still change before it is approved again.
  expect((await panel('Channel A')).getByLabelText('Price for Channel A')).toBeInTheDocument()
  const history = await panel('History')
  expect(history.getByText(". The listings aren't the same item")).toBeInTheDocument()
  expect(
    history.getByText('. Approved and held for its season until March 2027'),
  ).toBeInTheDocument()

  fireEvent.click((await panel('Approve or reject')).getByRole('button', { name: 'Approve' }))
  expect(await screen.findByText('Live on Channel A.')).toBeInTheDocument()
  expect(calls.filter((call) => call.path.endsWith('/fresh-comps'))).toHaveLength(1)
})

test('a fresh lookup that fails can be tried again', async () => {
  let failing = true
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(heldReview({ back_for_review: true })),
      [`POST /items/${ITEM}/fresh-comps`]: () =>
        failing
          ? Response.json({ detail: "We couldn't search eBay. Try again." }, { status: 502 })
          : Response.json(heldReview({ back_for_review: true, fresh_appraisal: FRESH })),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const fresh = await panel('What it sells for now')
  expect(await fresh.findByRole('alert')).toHaveTextContent("We couldn't search eBay. Try again.")

  failing = false
  fireEvent.click(fresh.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('Typical sale price now')).toBeInTheDocument()
  expect(calls.filter((call) => call.path.endsWith('/fresh-comps'))).toHaveLength(2)
})

test('a listing staff sent with a release month can stay off online selling', async () => {
  let kept = false
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () =>
        Response.json(
          kept
            ? review({
                status: 'not_listed_online',
                release_month: '2027-03-01',
                listings: [],
                history: [
                  {
                    decision: 'no',
                    reason: 'Not listed online',
                    note: 'Too bulky to hold.',
                    decided_by_name: 'Demo Manager',
                    decided_at: '2026-11-06T15:00:00+00:00',
                  },
                ],
              })
            : review({ release_month: '2027-03-01' }),
        ),
      [`POST /items/${ITEM}/not-online`]: () => {
        kept = true
        return Response.json({
          item_id: ITEM,
          status: 'not_listed_online',
          note: 'Too bulky to hold.',
          decided_by_name: 'Demo Manager',
          decided_at: '2026-11-06T15:00:00+00:00',
        })
      },
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const offline = await panel("Don't list online")
  fireEvent.change(offline.getByLabelText("Why it isn't going online"), {
    target: { value: 'Too bulky to hold.' },
  })
  fireEvent.click(offline.getByRole('button', { name: "Don't list online" }))

  expect(
    await screen.findByText(
      'Not listed online. It stays off every channel until a manager puts it back for review, and the note is in its history.',
    ),
  ).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Approve or reject' })).not.toBeInTheDocument()
  expect((await panel('History')).getByText('Too bulky to hold.')).toBeInTheDocument()
})

const KEPT_AT = '2026-11-06T15:00:00+00:00'

const KEPT: KeptOffItem = {
  item_id: ITEM,
  sku: 'RT11042601',
  brand: 'Carhartt',
  product: 'canvas jacket',
  note: 'Selling it on the floor this winter.',
  decided_by_name: 'Demo Manager',
  decided_at: KEPT_AT,
}

const KEPT_HISTORY = {
  decision: 'no' as const,
  reason: 'Not listed online',
  note: 'Selling it on the floor this winter.',
  decided_by_name: 'Demo Manager',
  decided_at: KEPT_AT,
}

const PUT_BACK_HISTORY = {
  decision: 'yes' as const,
  reason: 'Put back for review',
  note: 'A customer asked for it online.',
  decided_by_name: 'Demo Manager',
  decided_at: '2026-11-06T16:00:00+00:00',
}

test('the not listed online list says who kept each item off, when and why', async () => {
  stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], not_listed_online: [KEPT] }),
    },
  })
  renderAt('/app/approvals')
  const kept = await panel('Not listed online')
  expect(kept.getByRole('link', { name: 'Carhartt canvas jacket' })).toHaveAttribute(
    'href',
    `/app/approvals/${ITEM}`,
  )
  expect(kept.getByText(/^RT11042601, kept off online by Demo Manager on /)).toBeInTheDocument()
  expect(kept.getByText('Selling it on the floor this winter.')).toBeInTheDocument()
})

test('the not listed online list says when nothing is kept off', async () => {
  stubApi()
  renderAt('/app/approvals')
  expect(
    (await panel('Not listed online')).getByText('No item is kept off online.'),
  ).toBeInTheDocument()
})

test('putting an item back from the list needs a note, then opens its review', async () => {
  const back = heldReview({
    back_for_review: true,
    put_back: true,
    release_month: '2026-11-01',
    history: [...heldReview().history, KEPT_HISTORY, PUT_BACK_HISTORY],
  })
  const calls = stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], not_listed_online: [KEPT] }),
      [`POST /items/${ITEM}/put-back`]: () => Response.json(back),
      [`GET /items/${ITEM}/review`]: () => Response.json(back),
      [`POST /items/${ITEM}/fresh-comps`]: () => Response.json({ ...back, fresh_appraisal: FRESH }),
    },
  })
  renderAt('/app/approvals')
  const kept = await panel('Not listed online')
  fireEvent.click(kept.getByRole('button', { name: 'Put back for review' }))
  fireEvent.click(kept.getByRole('button', { name: 'Put back for review' }))
  expect(
    kept.getByText("Enter why it's going back for review, such as a customer asked for it online."),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/put-back'))).toBe(false)

  fireEvent.change(kept.getByLabelText("Why it's going back for review"), {
    target: { value: ' A customer asked for it online. ' },
  })
  fireEvent.click(kept.getByRole('button', { name: 'Put back for review' }))

  expect(await screen.findByText('Put back for review', { selector: 'dd' })).toBeInTheDocument()
  expect(calls.find((call) => call.path.endsWith('/put-back'))?.body).toEqual({
    note: 'A customer asked for it online.',
  })
  expect(
    screen.getByText(/^It was put back for review, so nothing is listed until you look again\./),
  ).toBeInTheDocument()
  expect(await screen.findByText('Typical sale price now')).toBeInTheDocument()
  const history = await panel('History')
  expect(history.getByText('. Put back for review')).toBeInTheDocument()
  expect(history.getByText('A customer asked for it online.')).toBeInTheDocument()
})

test('putting an item back can be cancelled', async () => {
  const calls = stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({ ...QUEUE, awaiting_approval: [], not_listed_online: [KEPT] }),
    },
  })
  renderAt('/app/approvals')
  const kept = await panel('Not listed online')
  fireEvent.click(kept.getByRole('button', { name: 'Put back for review' }))
  fireEvent.click(kept.getByRole('button', { name: 'Cancel' }))
  expect(kept.queryByLabelText("Why it's going back for review")).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/put-back'))).toBe(false)
})

test('an item put back shows so in Waiting for approval', async () => {
  stubApi({
    overrides: {
      'GET /approvals': () =>
        Response.json({
          ...QUEUE,
          awaiting_approval: [
            { ...QUEUE.awaiting_approval[0], put_back: true, waiting_since: KEPT_AT },
          ],
        }),
    },
  })
  renderAt('/app/approvals')
  const waiting = await panel('Waiting for approval')
  expect(
    waiting.getByText('RT11042601, for Channel A and Channel B, put back for review'),
  ).toBeInTheDocument()
  expect(waiting.getByText(/^Put back on /)).toBeInTheDocument()
})

test('an item kept off online can be put back from its own page', async () => {
  let back = false
  const kept = review({
    status: 'not_listed_online',
    listings: [listing()],
    blockers: [],
    history: [...review().history, KEPT_HISTORY],
  })
  const calls = stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () => Response.json(kept),
      [`POST /items/${ITEM}/put-back`]: () => {
        back = true
        return Response.json(
          review({ put_back: true, history: [...kept.history, PUT_BACK_HISTORY] }),
        )
      },
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const panelBack = await panel('Put back for review')
  expect(screen.queryByRole('heading', { name: "Don't list online" })).not.toBeInTheDocument()
  expect(
    (await panel('Channel A')).getByText(
      "Kept off online, so it won't be listed unless a manager puts it back for review.",
    ),
  ).toBeInTheDocument()
  fireEvent.click(panelBack.getByRole('button', { name: 'Put back for review' }))
  expect(
    panelBack.getByText(
      "Enter why it's going back for review, such as a customer asked for it online.",
    ),
  ).toBeInTheDocument()
  fireEvent.change(panelBack.getByLabelText("Why it's going back for review"), {
    target: { value: 'A customer asked for it online.' },
  })
  fireEvent.click(panelBack.getByRole('button', { name: 'Put back for review' }))

  expect(await panel('Approve or reject')).toBeTruthy()
  expect(back).toBe(true)
  expect((await panel('Channel A')).getByText('Waiting for your approval.')).toBeInTheDocument()
  expect(screen.getByText('Put back for review', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Put back for review' })).not.toBeInTheDocument()
  expect((await panel('History')).getByText('. Put back for review')).toBeInTheDocument()
  expect(calls.filter((call) => call.path.endsWith('/put-back'))).toHaveLength(1)
})

test('a failed put back says why and keeps the note', async () => {
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () =>
        Response.json(review({ status: 'not_listed_online', listings: [], blockers: [] })),
      [`POST /items/${ITEM}/put-back`]: () =>
        Response.json({ detail: 'Only a manager can put an item back.' }, { status: 403 }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  const panelBack = await panel('Put back for review')
  fireEvent.change(panelBack.getByLabelText("Why it's going back for review"), {
    target: { value: 'A customer asked for it online.' },
  })
  fireEvent.click(panelBack.getByRole('button', { name: 'Put back for review' }))
  expect(await panelBack.findByRole('alert')).toHaveTextContent(
    'Only a manager can put an item back.',
  )
  expect(panelBack.getByLabelText("Why it's going back for review")).toHaveValue(
    'A customer asked for it online.',
  )
})

test('an item put back before its listing was written gets its listing written on the review', async () => {
  stubApi({
    overrides: {
      [`GET /items/${ITEM}/review`]: () =>
        Response.json(
          review({
            put_back: true,
            listings: [],
            blockers: ["Staff haven't sent this listing for approval yet."],
          }),
        ),
      [`GET /items/${ITEM}/channels`]: () =>
        Response.json({
          channels: [
            { channel: 'channel_a', takes: true, why_not: null },
            { channel: 'channel_b', takes: true, why_not: null },
          ],
          timing: { season: null, season_span: null, release_month: null },
          reason: 'Both channels take this jacket, so list it now.',
          reason_source: 'rules',
          reason_fallback: null,
        }),
    },
  })
  renderAt(`/app/approvals/${ITEM}`)
  expect(
    await screen.findByText(/^It was kept off online before its listing was written/),
  ).toBeInTheDocument()
  const channels = await panel('Where and when to list it')
  expect(channels.getByRole('button', { name: 'Write the listing' })).toBeEnabled()
  expect(screen.queryByRole('heading', { name: 'Approve or reject' })).not.toBeInTheDocument()
})

test('a listing with no release month is not offered the off-online choice', async () => {
  stubApi()
  renderAt(`/app/approvals/${ITEM}`)
  await panel('Approve or reject')
  expect(screen.queryByRole('heading', { name: "Don't list online" })).not.toBeInTheDocument()
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
