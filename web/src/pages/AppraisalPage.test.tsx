import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const item = {
  id: 'item-1',
  sku: 'ST11042601',
  status: 'intake',
  photo_keys: ['k'],
  store_department: 'clothing',
  notes: null,
}
const card = {
  item_id: 'item-1',
  category: 'apparel',
  brand: 'Carhartt',
  product: 'Canvas jacket',
  visible_text: null,
  search_query: 'carhartt canvas jacket',
  model_confidence: 'high',
  condition: 'pre_owned',
  color: 'Brown',
  material: null,
  exact_model: null,
  platform: null,
  staff_edited: false,
  staff_confirmed: false,
  needs_confirmation: false,
}
// Eight jacket listings from $39 to $72 and one far above them.
const comps = [3900, 4200, 4500, 5000, 5400, 5800, 6500, 7200, 25000].map((asking, index) => ({
  title: `Carhartt canvas jacket ${index + 1}`,
  asking_cents: asking,
  condition: 'Pre-Owned',
  url: `https://www.ebay.com/itm/${index + 1}`,
  outlier: asking === 25000,
}))
const appraisal = {
  id: 'appraisal-1',
  item_id: 'item-1',
  price_low_cents: 2500,
  price_typical_cents: 3500,
  price_high_cents: 4800,
  net_after_fees_cents: 2834,
  comps_count: 8,
  confidence: 'medium',
  recommendation: 'yes',
  rules_config: {
    pricing: { ask_to_sale_factor: 0.645, games_ask_to_sale_factor: 0.94 },
    search: { outcome: 'priced', queries: ['carhartt canvas jacket'] },
  },
  explanation: 'The expected sale price is $35.00.',
  comps,
  created_at: '2026-11-01T15:00:00+00:00',
}
const savedRow = {
  id: 'decision-1',
  item_id: 'item-1',
  sku: 'ST11042601',
  brand: 'Carhartt',
  product: 'Canvas jacket',
  price_typical_cents: 3500,
  decision: 'no',
  destination: 'seasonal_storage',
  decided_by_name: 'Demo Staff',
  decided_at: '2026-11-01T15:00:00+00:00',
}

const draft = {
  id: 'draft-a',
  item_id: 'item-1',
  channel: 'channel_a',
  title: 'Carhartt canvas jacket - Pre-owned',
  description: 'Brown Carhartt canvas jacket, pre-owned.',
  category: 'Unisex Clothing',
  category_options: ["Men's Clothing", 'Unisex Clothing'],
  state: 'draft',
  source: 'model',
  fallback_reason: null,
  model_name: 'api.groq.com/qwen/qwen3.8-27b',
  model_flags: [],
  flags: [],
  staff_edited: false,
  submitted_at: null,
  created_at: '2026-11-03T15:00:00+00:00',
  updated_at: '2026-11-03T15:00:00+00:00',
}

const recommendation = {
  channels: [
    { channel: 'channel_a', takes: true, why_not: null },
    { channel: 'channel_b', takes: true, why_not: null },
  ],
  timing: {
    season: 'Coats and jackets',
    season_span: 'August to January',
    release_month: null,
  },
  reason: 'Both channels take this jacket, and it is in season, so list it now.',
  reason_source: 'model',
  reason_fallback: null,
}

type Call = { method: string; path: string; request: Request }

// A stand-in for the API that records each call, with any route overridable by a test.
function stubApi(overrides: Record<string, () => Response> = {}) {
  const calls: Call[] = []
  let decisions: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      const key = `${request.method} ${path}`
      calls.push({ method: request.method, path, request })
      if (overrides[key]) return overrides[key]()
      switch (key) {
        case 'POST /items':
          return Response.json(item, { status: 201 })
        case 'POST /items/item-1/card':
          return Response.json(card)
        case 'PATCH /items/item-1/card':
          return Response.json({
            ...card,
            ...(await request.clone().json()),
            staff_confirmed: true,
            needs_confirmation: false,
          })
        case 'POST /items/item-1/appraisals':
          return Response.json(appraisal)
        case 'POST /items/item-1/decisions':
          decisions = [savedRow]
          return Response.json({ id: 'decision-1' }, { status: 201 })
        case 'GET /items/item-1/channels':
          return Response.json(recommendation)
        case 'POST /items/item-1/drafts':
          return Response.json([draft])
        case 'POST /items/item-1/drafts/submit':
          return Response.json([
            { ...draft, state: 'awaiting_approval', submitted_at: '2026-11-03T15:05:00+00:00' },
          ])
        case 'GET /me':
          return Response.json({ status: 'active' })
        case 'GET /decisions':
          return Response.json(decisions)
        default:
          throw new Error(`unexpected ${key}`)
      }
    }),
  )
  return calls
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/app/appraise']}>
      <App />
    </MemoryRouter>,
  )
}

const jpeg = (name = 'item.jpg') => new File(['photo'], name, { type: 'image/jpeg' })

async function addPhotos(...files: File[]) {
  const input = await screen.findByLabelText(/^(Take or choose a photo|Add another photo)$/)
  fireEvent.change(input, { target: { files } })
}

// Fills in what intake needs, a photo, the department and the condition, and takes the item in.
async function takeItemIn() {
  await addPhotos(jpeg())
  fireEvent.click(screen.getByLabelText('Clothing and shoes'))
  fireEvent.click(screen.getByLabelText('Pre-owned'))
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))
}

// A no against the fixture's yes, so it needs a reason from the list as well as a destination.
async function sayNo({
  reason = 'worse_condition',
  note = '',
  destination = 'Seasonal storage',
} = {}) {
  fireEvent.click(await screen.findByRole('button', { name: "No, don't list it" }))
  fireEvent.change(screen.getByLabelText('Why you disagree'), { target: { value: reason } })
  if (note) fireEvent.change(screen.getByLabelText(/^Note/), { target: { value: note } })
  fireEvent.click(screen.getByLabelText(destination))
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
}

// A no that agrees with the recommendation, which says why in staff's own words.
async function sayAgreeingNo(reason = 'Too worn to sell online', destination = 'Seasonal storage') {
  fireEvent.click(await screen.findByRole('button', { name: "No, don't list it" }))
  fireEvent.change(screen.getByLabelText("Why it isn't being listed"), {
    target: { value: reason },
  })
  fireEvent.click(screen.getByLabelText(destination))
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
}

const recommending = (recommendation: string, extra: object = {}) => ({
  'POST /items/item-1/appraisals': () => Response.json({ ...appraisal, recommendation, ...extra }),
})

const posted = (calls: Call[], path: string) =>
  calls.filter((call) => call.method === 'POST' && call.path === path)

// The parts of a multipart body in order, read from its text because the test DOM's File doesn't
// survive Request.formData(). A file part reads as 'a file'.
async function formFields(request: Request) {
  const text = await request.clone().text()
  const parts = text.split(/^--.*$/m).slice(1, -1)
  return parts.map((part) => {
    const [head, body] = part.split('\r\n\r\n')
    const name = /name="([^"]+)"/.exec(head)?.[1]
    return [name, /filename=/.test(head) ? 'a file' : body.replace(/\r\n$/, '')]
  })
}

async function confirmTheCard() {
  fireEvent.click(await screen.findByRole('button', { name: 'Confirm and get the price' }))
}

beforeEach(() => {
  fake.reset(fakeSession())
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('takes a photo through the card and the price to a saved decision in the list', async () => {
  const calls = stubApi()
  renderPage()
  expect(await screen.findByText('No decisions yet.')).toBeInTheDocument()

  await takeItemIn()
  await confirmTheCard()

  expect(await screen.findByRole('heading', { name: 'Price' })).toBeInTheDocument()
  expect(screen.getAllByText('Canvas jacket')).toHaveLength(1)
  expect(screen.getByText('The expected sale price is $35.00.')).toBeInTheDocument()
  expect(screen.getByText('$35.00')).toBeInTheDocument()

  await sayNo()

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Saved your decision: no. It goes to seasonal storage.',
  )
  const recent = screen.getByRole('region', { name: 'Recent decisions' })
  const row = await within(recent).findByRole('listitem')
  expect(row).toHaveTextContent('Canvas jacket')
  expect(row).toHaveTextContent('Seasonal storage')
  expect(row).toHaveTextContent('$35.00 typical, Demo Staff,')

  const [decision] = posted(calls, '/items/item-1/decisions')
  expect(await decision.request.json()).toEqual({
    appraisal_id: 'appraisal-1',
    decision: 'no',
    override_reason: 'worse_condition',
    note: null,
    rejection_reason: "It's in worse shape than the listings",
    destination: 'seasonal_storage',
  })
})

test('a decision on an item with no price says so in the list', async () => {
  stubApi({
    'GET /decisions': () => Response.json([{ ...savedRow, price_typical_cents: null }]),
  })
  renderPage()

  const recent = await screen.findByRole('region', { name: 'Recent decisions' })
  const row = await within(recent).findByRole('listitem')
  expect(row).toHaveTextContent('No price, Demo Staff,')
  expect(row).not.toHaveTextContent('None')
})

test('sends the sign-in token and the photos as file parts', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await screen.findByRole('heading', { name: 'Item card' })

  const upload = calls.find((call) => call.path === '/items')
  expect(upload?.request.headers.get('Authorization')).toBe('Bearer access')
  expect(upload?.request.headers.get('Content-Type')).toMatch(/^multipart\/form-data/)
})

test('a failed step shows the error and retrying does not upload again', async () => {
  let failing = true
  const calls = stubApi({
    'POST /items/item-1/appraisals': () =>
      failing
        ? Response.json({ detail: 'This item has no card yet.' }, { status: 409 })
        : Response.json(appraisal),
  })
  renderPage()
  await takeItemIn()
  await confirmTheCard()

  expect(await screen.findByRole('alert')).toHaveTextContent('This item has no card yet.')

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: 'Price' })).toBeInTheDocument()
  expect(calls.filter((call) => call.path === '/items')).toHaveLength(1)
  expect(
    calls.filter((call) => call.path.endsWith('/card') && call.method === 'POST'),
  ).toHaveLength(1)
})

test('a failed save keeps the card and lets the person decide again', async () => {
  let failing = true
  stubApi({
    'POST /items/item-1/decisions': () =>
      failing
        ? Response.json({ detail: 'Could not save.' }, { status: 500 })
        : Response.json({ id: 'decision-1' }, { status: 201 }),
  })
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save.')

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Saved your decision: yes.')
})

test('stops at the card, with no search until staff confirm it', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()

  expect(await screen.findByLabelText('Brand')).toHaveValue('Carhartt')
  expect(screen.getByLabelText('Color')).toHaveValue('Brown')
  expect(screen.getByText('High')).toBeInTheDocument()
  expect(screen.queryByText(/isn't sure/)).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/appraisals'))).toBe(false)
})

test('sends what staff changed and shows the confirmed card', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()

  fireEvent.change(await screen.findByLabelText('Brand'), { target: { value: 'Dickies' } })
  fireEvent.change(screen.getByLabelText('Exact model'), { target: { value: 'Eisenhower' } })
  fireEvent.change(screen.getByLabelText('Category'), {
    target: { value: 'electronics_games' },
  })
  await confirmTheCard()

  await screen.findByRole('heading', { name: 'Price' })
  const patch = calls.find((call) => call.method === 'PATCH')
  expect(await patch?.request.json()).toMatchObject({
    brand: 'Dickies',
    exact_model: 'Eisenhower',
    category: 'electronics_games',
    color: 'Brown',
    search_query: 'carhartt canvas jacket',
  })
  expect(screen.getByText('Dickies')).toBeInTheDocument()
  expect(screen.getByText('Electronics and games')).toBeInTheDocument()
  expect(screen.queryByLabelText('Brand')).not.toBeInTheDocument()
})

test('warns about a low confidence card and needs search words', async () => {
  const calls = stubApi({
    'POST /items/item-1/card': () =>
      Response.json({ ...card, model_confidence: 'low', needs_confirmation: true }),
  })
  renderPage()
  await takeItemIn()

  expect(await screen.findByText(/The model isn't sure/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/^Search/), { target: { value: '  ' } })
  await confirmTheCard()

  expect(screen.getByText('Enter the words to search for.')).toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PATCH')).toBe(false)
})

test('a failed confirm keeps what staff typed', async () => {
  let failing = true
  stubApi({
    'PATCH /items/item-1/card': () =>
      failing
        ? Response.json({ detail: 'Could not save the card.' }, { status: 500 })
        : Response.json({ ...card, brand: 'Dickies', staff_confirmed: true }),
  })
  renderPage()
  await takeItemIn()
  fireEvent.change(await screen.findByLabelText('Brand'), { target: { value: 'Dickies' } })
  await confirmTheCard()

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the card.')
  expect(screen.getByLabelText('Brand')).toHaveValue('Dickies')

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await confirmTheCard()

  expect(await screen.findByRole('heading', { name: 'Price' })).toBeInTheDocument()
})

test('an unreachable API says so', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  renderPage()
  expect(await screen.findByRole('alert')).toHaveTextContent("We couldn't reach the API.")
})

test('appraising another item clears the last one', async () => {
  stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Appraise another item' }))

  await waitFor(() =>
    expect(screen.queryByRole('heading', { name: 'Item card' })).not.toBeInTheDocument(),
  )
  expect(screen.getByLabelText('Take or choose a photo')).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Pre-owned')).not.toBeChecked()
})

test('sends people who are not signed in to the sign-in page', async () => {
  fake.reset()
  renderPage()
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
})

test('a yes decision shows the channels and timing, then drafts the chosen channels', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))

  expect(await screen.findByText(recommendation.reason)).toBeInTheDocument()
  expect(screen.getByText('List now')).toBeInTheDocument()
  expect(screen.getByText('Coats and jackets, August to January')).toBeInTheDocument()
  expect(calls.some((call) => call.path.includes('/drafts'))).toBe(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Channel B' }))
  fireEvent.click(screen.getByRole('button', { name: 'Write the listing' }))

  expect(await screen.findByRole('heading', { name: 'Channel A' })).toBeInTheDocument()
  expect(screen.getByText('Listing on Channel A.')).toBeInTheDocument()
  const drafting = calls.find((call) => call.path === '/items/item-1/drafts')
  expect(await drafting?.request.clone().json()).toEqual({ channels: ['channel_a'] })
  expect(screen.getByLabelText('Title')).toHaveValue('Carhartt canvas jacket - Pre-owned')
  expect(screen.getByLabelText('Category')).toHaveValue('Unisex Clothing')
  fireEvent.click(screen.getByRole('button', { name: 'Send for manager approval' }))

  expect(await screen.findByText('Sent to a manager for approval.')).toBeInTheDocument()
  expect(screen.queryByLabelText('Title')).not.toBeInTheDocument()
  expect(calls.filter((call) => call.path === '/items/item-1/drafts')).toHaveLength(1)
})

test('a no decision writes no listing', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  await sayNo()

  expect(await screen.findByRole('status')).toHaveTextContent('Saved your decision: no.')
  expect(screen.queryByRole('heading', { name: 'Listing drafts' })).not.toBeInTheDocument()
  expect(
    screen.queryByRole('heading', { name: 'Where and when to list it' }),
  ).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.includes('/drafts'))).toBe(false)
  expect(calls.some((call) => call.path.includes('/channels'))).toBe(false)
})

test('intake sends the photos and notes, then the clothing entries for the card', async () => {
  const calls = stubApi()
  renderPage()
  await addPhotos(jpeg('front.jpg'), jpeg('tag.jpg'))
  expect(screen.getAllByRole('img')).toHaveLength(2)
  fireEvent.click(screen.getByLabelText('Clothing and shoes'))
  fireEvent.click(screen.getByLabelText('New with tags'))
  fireEvent.click(screen.getByLabelText('Stains'))
  fireEvent.click(screen.getByLabelText("Women's"))
  fireEvent.change(screen.getByLabelText('Size (optional)'), { target: { value: 'M' } })
  fireEvent.change(screen.getByLabelText('Size type (optional)'), { target: { value: 'Petite' } })
  fireEvent.change(screen.getByLabelText('Notes (optional)'), {
    target: { value: 'Missing one button' },
  })
  expect(screen.queryByText('Tested and working')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))

  expect(await screen.findByRole('heading', { name: 'Taken in as ST11042601' })).toBeInTheDocument()
  expect(await formFields(posted(calls, '/items')[0].request)).toEqual([
    ['photos', 'a file'],
    ['photos', 'a file'],
    ['store_department', 'clothing'],
    ['notes', 'Missing one button'],
    ['keep_photos', 'false'],
    ['allow_repeat', 'false'],
  ])
  const [cardCall] = posted(calls, '/items/item-1/card')
  expect(await cardCall.request.json()).toEqual({
    condition: 'new_with_tags',
    flaws: ['stains'],
    department: 'womens',
    size: 'M',
    size_type: 'Petite',
  })
  expect(screen.queryByRole('button', { name: 'Take it in' })).not.toBeInTheDocument()
})

test('an electronics item asks whether it works, is boxed and what comes with it', async () => {
  const calls = stubApi()
  renderPage()
  await addPhotos(jpeg())
  fireEvent.click(screen.getByLabelText('Electronics and games'))
  fireEvent.click(screen.getByLabelText('Pre-owned'))
  fireEvent.click(screen.getByLabelText("No, it doesn't work"))
  fireEvent.click(screen.getByRole('radio', { name: 'Yes' }))
  fireEvent.change(screen.getByLabelText('Accessories included (optional)'), {
    target: { value: 'Charger' },
  })
  expect(screen.queryByLabelText('Size (optional)')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))

  await screen.findByRole('heading', { name: 'Item card' })
  const [cardCall] = posted(calls, '/items/item-1/card')
  expect(await cardCall.request.json()).toEqual({
    condition: 'pre_owned',
    flaws: [],
    tested_working: false,
    complete_in_box: true,
    accessories_included: 'Charger',
  })
})

test('intake needs a photo, the department and the condition before it uploads', async () => {
  const calls = stubApi()
  renderPage()
  fireEvent.click(await screen.findByRole('button', { name: 'Take it in' }))

  const summary = screen.getByRole('alert')
  expect(summary).toHaveTextContent('There is a problem')
  expect(summary).toHaveTextContent('Add at least one photo of the item.')
  expect(summary).toHaveTextContent('Choose the department it came from.')
  expect(summary).toHaveTextContent('Choose its condition.')
  expect(posted(calls, '/items')).toHaveLength(0)
})

test.each([
  ['an empty file', new File([], 'item.jpg', { type: 'image/jpeg' }), 'Photo 1 is empty.'],
  [
    'a file that is not a photo',
    new File(['%PDF'], 'item.pdf', { type: 'application/pdf' }),
    "Photo 1 isn't a JPEG, PNG or WebP image.",
  ],
  [
    'a photo over the size limit',
    Object.defineProperty(jpeg(), 'size', { value: 15 * 1024 * 1024 + 1 }),
    'Photo 1 is over 15 MB, so choose a smaller copy.',
  ],
])('%s is refused when it is chosen', async (_, file, message) => {
  stubApi()
  renderPage()
  await addPhotos(file)

  expect(await screen.findByRole('alert')).toHaveTextContent(message)
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

test('an item takes at most four photos, and a photo can be removed', async () => {
  stubApi()
  renderPage()
  await addPhotos(...['1', '2', '3', '4', '5'].map((n) => jpeg(`${n}.jpg`)))

  expect(screen.getAllByRole('img')).toHaveLength(4)
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Add at most 4 photos, so only the first 4 were added.',
  )
  expect(screen.queryByLabelText('Add another photo')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Remove photo 2' }))
  expect(screen.getAllByRole('img')).toHaveLength(3)
  expect(screen.getByLabelText('Add another photo')).toBeInTheDocument()
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
})

test('a photo the API refuses shows its reason and keeps the form', async () => {
  stubApi({
    'POST /items': () =>
      Response.json({ detail: "Photo 1 isn't a JPEG, PNG or WebP image." }, { status: 422 }),
  })
  renderPage()
  await takeItemIn()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Photo 1 isn't a JPEG, PNG or WebP image.",
  )
  expect(screen.getByLabelText('Pre-owned')).toBeChecked()
})

const repeat = {
  detail: {
    message: 'A photo matches an item that was rejected before.',
    matches: [
      {
        item_id: 'item-0',
        sku: 'RT10272601',
        brand: 'Carhartt',
        product: 'Canvas jacket',
        rejection_reason: 'Too worn to sell online',
        destination: 'store_floor',
        rejected_at: '2026-10-27T16:00:00+00:00',
      },
    ],
  },
}

test('a photo of a rejected item is flagged, and staff can take it in anyway', async () => {
  const calls = stubApi({
    'POST /items': () =>
      posted(calls, '/items').length === 1
        ? Response.json(repeat, { status: 409 })
        : Response.json(item, { status: 201 }),
  })
  renderPage()
  await takeItemIn()

  const warning = await screen.findByRole('alert')
  expect(warning).toHaveTextContent('This may have been rejected before')
  expect(warning).toHaveFocus()
  expect(warning).toHaveTextContent('Carhartt Canvas jacket')
  expect(warning).toHaveTextContent('SKU RT10272601')
  expect(warning).toHaveTextContent('Why: Too worn to sell online')
  expect(warning).toHaveTextContent('Where it went: Back to the store floor')
  expect(posted(calls, '/items/item-1/card')).toHaveLength(0)

  fireEvent.click(screen.getByRole('button', { name: 'Take it in anyway' }))

  expect(await screen.findByRole('heading', { name: 'Item card' })).toBeInTheDocument()
  const [, again] = posted(calls, '/items')
  expect(await formFields(again.request)).toContainEqual(['allow_repeat', 'true'])
})

test('staff can stop when a photo is flagged', async () => {
  const calls = stubApi({ 'POST /items': () => Response.json(repeat, { status: 409 }) })
  renderPage()
  await takeItemIn()
  fireEvent.click(await screen.findByRole('button', { name: "Don't take it in" }))

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Take or choose a photo')).toHaveFocus()
  expect(posted(calls, '/items')).toHaveLength(1)
})

test('a no needs a reason and where the item goes, and Back returns to the choice', async () => {
  const calls = stubApi(recommending('no'))
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: "No, don't list it" }))
  expect(screen.queryByRole('button', { name: 'Yes, list it' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))

  expect(screen.getByText("Say why it isn't being listed.")).toBeInTheDocument()
  expect(screen.getByText('Choose where the item goes instead.')).toBeInTheDocument()
  expect(screen.getByLabelText('Back to the store floor')).toBeInTheDocument()
  expect(screen.getByLabelText('Discard or donate onward')).toBeInTheDocument()
  expect(posted(calls, '/items/item-1/decisions')).toHaveLength(0)

  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  expect(screen.getByRole('button', { name: 'Yes, list it' })).toBeInTheDocument()
  expect(screen.queryByLabelText("Why it isn't being listed")).not.toBeInTheDocument()
})

test('a no that fails to save keeps the reason staff typed', async () => {
  let failing = true
  const calls = stubApi({
    ...recommending('no'),
    'POST /items/item-1/decisions': () =>
      failing
        ? Response.json({ detail: 'Could not save.' }, { status: 500 })
        : Response.json({ id: 'decision-1' }, { status: 201 }),
  })
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  await sayAgreeingNo('Stained', 'Discard or donate onward')

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save.')
  expect(screen.getByLabelText("Why it isn't being listed")).toHaveValue('Stained')
  expect(screen.getByLabelText('Discard or donate onward')).toBeChecked()

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Saved your decision: no. It gets discarded or donated onward.',
  )
  const [, saved] = posted(calls, '/items/item-1/decisions')
  expect(await saved.request.json()).toMatchObject({
    rejection_reason: 'Stained',
    destination: 'discard_or_donate',
  })
})

test('the price shows its range, the verdict and the listings it came from', async () => {
  stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()

  const price = await screen.findByRole('region', { name: 'Price' })
  expect(within(price).getByText('Low').nextSibling).toHaveTextContent('$25.00')
  expect(within(price).getByText('Typical').nextSibling).toHaveTextContent('$35.00')
  expect(within(price).getByText('High').nextSibling).toHaveTextContent('$48.00')
  expect(price).toHaveTextContent('Left after eBay fees and supplies$28.34')
  expect(price).toHaveTextContent('Worth listing, medium confidence')
  expect(price).toHaveTextContent('Searched eBay for "carhartt canvas jacket".')
  expect(price).toHaveTextContent('times 0.645')
  expect(price).toHaveTextContent('1 listing was left out for being far from the rest.')

  // Six listings spread from the cheapest to the dearest of those the price used.
  const table = within(price).getByRole('table')
  expect(table).toHaveTextContent('6 of 9 similar eBay listings, cheapest to dearest')
  const links = within(table).getAllByRole('link')
  expect(links).toHaveLength(6)
  expect(links[0]).toHaveTextContent('Carhartt canvas jacket 1')
  expect(links[0]).toHaveAttribute('href', 'https://www.ebay.com/itm/1')
  expect(links[5]).toHaveTextContent('Carhartt canvas jacket 8')
  expect(table).not.toHaveTextContent('$250.00')

  fireEvent.click(within(price).getByRole('button', { name: 'Show all 9 listings' }))
  expect(within(table).getAllByRole('link')).toHaveLength(9)
  const outlier = within(table).getByRole('link', { name: 'Carhartt canvas jacket 9' })
  expect(outlier.closest('tr')).toHaveTextContent('Left out, far from the other prices$250.00')
  expect(within(price).getByRole('button', { name: 'Show fewer listings' })).toHaveAttribute(
    'aria-expanded',
    'true',
  )
})

test('an appraisal with no price says why and shows no listings', async () => {
  stubApi(
    recommending('check', {
      price_low_cents: null,
      price_typical_cents: null,
      price_high_cents: null,
      net_after_fees_cents: null,
      comps_count: 0,
      confidence: 'low',
      comps: [],
      explanation: 'The eBay search failed just now, so this item has no price.',
    }),
  )
  renderPage()
  await takeItemIn()
  await confirmTheCard()

  const price = await screen.findByRole('region', { name: 'Price' })
  expect(price).toHaveTextContent('No price')
  expect(price).toHaveTextContent('The eBay search failed just now')
  expect(within(price).queryByText('Typical')).not.toBeInTheDocument()
  expect(within(price).queryByRole('table')).not.toBeInTheDocument()
  // A check has no side to go against, so a no only needs staff's own words.
  fireEvent.click(screen.getByRole('button', { name: "No, don't list it" }))
  expect(screen.queryByLabelText('Why you disagree')).not.toBeInTheDocument()
  expect(screen.getByLabelText("Why it isn't being listed")).toBeInTheDocument()
})

test('a no against the recommendation needs a reason from the list', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: "No, don't list it" }))

  const reasons = screen.getByLabelText('Why you disagree')
  expect(
    within(reasons)
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual([
    'Choose a reason',
    "The listings aren't the same item",
    "It's in worse shape than the listings",
    'We know it sells for less',
    'Too big or heavy to ship for the price',
    'It may not be genuine',
    'Something else',
  ])
  expect(screen.queryByLabelText("Why it isn't being listed")).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Seasonal storage'))
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
  expect(screen.getByText('Choose why you disagree.')).toBeInTheDocument()

  // Something else needs a note to say what it is.
  fireEvent.change(reasons, { target: { value: 'other' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
  expect(screen.getByText('Add a note to say what the reason is.')).toBeInTheDocument()
  expect(posted(calls, '/items/item-1/decisions')).toHaveLength(0)

  fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'Smells of smoke' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save the no' }))
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Saved your decision: no. It goes to seasonal storage.',
  )
  const [decision] = posted(calls, '/items/item-1/decisions')
  expect(await decision.request.json()).toMatchObject({
    decision: 'no',
    override_reason: 'other',
    note: 'Smells of smoke',
    rejection_reason: 'Smells of smoke',
    destination: 'seasonal_storage',
  })
})

test('a no against the recommendation can carry a note', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  await sayNo({ reason: 'hard_to_ship', note: 'Weighs about 30 lb' })

  await screen.findByRole('status')
  const [decision] = posted(calls, '/items/item-1/decisions')
  expect(await decision.request.json()).toMatchObject({
    override_reason: 'hard_to_ship',
    note: 'Weighs about 30 lb',
    rejection_reason: 'Too big or heavy to ship for the price',
  })
})

test('a yes against a no asks why, then goes on to the channels', async () => {
  const calls = stubApi(recommending('no'))
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))

  expect(posted(calls, '/items/item-1/decisions')).toHaveLength(0)
  expect(screen.getByRole('heading', { name: 'Listing it' })).toBeInTheDocument()
  expect(screen.queryByText('Where it goes instead')).not.toBeInTheDocument()
  const reasons = screen.getByLabelText('Why you disagree')
  expect(
    within(reasons)
      .getAllByRole('option')
      .map((option) => option.textContent),
  ).toEqual([
    'Choose a reason',
    "The listings aren't the same item",
    "It's in better shape than the listings",
    'We know it sells for more',
    'Something else',
  ])
  fireEvent.change(reasons, { target: { value: 'sells_for_more' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save the yes' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Saved your decision: yes.')
  expect(
    await screen.findByRole('heading', { name: 'Where and when to list it' }),
  ).toBeInTheDocument()
  const [decision] = posted(calls, '/items/item-1/decisions')
  expect(await decision.request.json()).toEqual({
    appraisal_id: 'appraisal-1',
    decision: 'yes',
    override_reason: 'sells_for_more',
    note: null,
  })
})

test('a yes that agrees saves at once with no reason', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Saved your decision: yes.')
  const [decision] = posted(calls, '/items/item-1/decisions')
  expect(await decision.request.json()).toEqual({ appraisal_id: 'appraisal-1', decision: 'yes' })
})

test('the card can be edited after the price, which prices it again', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Edit the card' }))

  expect(screen.getByRole('button', { name: 'Yes, list it' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Search'), {
    target: { value: 'carhartt detroit jacket' },
  })
  fireEvent.change(screen.getByLabelText('Condition'), { target: { value: 'new_without_tags' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm and get the price' }))

  expect(await screen.findByRole('button', { name: 'Edit the card' })).toBeInTheDocument()
  const card = screen.getByRole('region', { name: 'Item card' })
  expect(card).toHaveTextContent('carhartt detroit jacket')
  expect(card).toHaveTextContent('New without tags')
  expect(posted(calls, '/items/item-1/appraisals')).toHaveLength(2)
  const edits = calls.filter((call) => call.method === 'PATCH')
  expect(await edits[1].request.json()).toMatchObject({
    search_query: 'carhartt detroit jacket',
    condition: 'new_without_tags',
  })
})

test('editing the card can be cancelled, keeping the price', async () => {
  const calls = stubApi()
  renderPage()
  await takeItemIn()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Edit the card' }))
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.getByRole('button', { name: 'Yes, list it' })).toBeEnabled()
  expect(screen.getByRole('region', { name: 'Price' })).toBeInTheDocument()
  expect(posted(calls, '/items/item-1/appraisals')).toHaveLength(1)
})

const retake = (...numbers: number[]) => ({
  detail: {
    kind: 'retake',
    message: 'A photo may be hard to price from.',
    photos: numbers.map((number) => ({
      number,
      reason: "It's too dark to see the item well. Take it again with more light.",
    })),
  },
})

test('a photo to retake is a prompt, and staff can use it anyway', async () => {
  const calls = stubApi({
    'POST /items': () =>
      posted(calls, '/items').length === 1
        ? Response.json(retake(2), { status: 409 })
        : Response.json(item, { status: 201 }),
  })
  renderPage()
  await addPhotos(jpeg('front.jpg'), jpeg('back.jpg'))
  fireEvent.click(screen.getByLabelText('Clothing and shoes'))
  fireEvent.click(screen.getByLabelText('Pre-owned'))
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))

  const prompt = await screen.findByRole('alert')
  expect(prompt).toHaveTextContent('Take this photo again?')
  expect(prompt).toHaveTextContent(
    "Photo 2: It's too dark to see the item well. Take it again with more light.",
  )
  expect(prompt).toHaveFocus()
  expect(
    screen.getByText(
      (_, node) => node?.tagName === 'P' && node.textContent === 'Photo 2: Take again',
    ),
  ).toBeInTheDocument()
  expect(
    screen.queryByText(
      (_, node) => node?.tagName === 'P' && node.textContent === 'Photo 1: Take again',
    ),
  ).not.toBeInTheDocument()
  expect(posted(calls, '/items/item-1/card')).toHaveLength(0)

  fireEvent.click(screen.getByRole('button', { name: 'Use it anyway' }))

  expect(await screen.findByRole('heading', { name: 'Item card' })).toBeInTheDocument()
  const [, again] = posted(calls, '/items')
  expect(await formFields(again.request)).toContainEqual(['keep_photos', 'true'])
  expect(await formFields(again.request)).toContainEqual(['allow_repeat', 'false'])
})

test('taking a photo again removes it and goes back to the photos', async () => {
  const calls = stubApi({
    'POST /items': () =>
      posted(calls, '/items').length === 1
        ? Response.json(retake(1, 2), { status: 409 })
        : Response.json(item, { status: 201 }),
  })
  renderPage()
  await addPhotos(jpeg('front.jpg'), jpeg('back.jpg'), jpeg('tag.jpg'))
  fireEvent.click(screen.getByLabelText('Clothing and shoes'))
  fireEvent.click(screen.getByLabelText('Pre-owned'))
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Take these photos again?')
  fireEvent.click(screen.getByRole('button', { name: 'Take them again' }))

  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getAllByRole('img')).toHaveLength(1)
  expect(screen.getByLabelText('Add another photo')).toHaveFocus()
  // The rest of the form stays as staff filled it in.
  expect(screen.getByLabelText('Pre-owned')).toBeChecked()

  await addPhotos(jpeg('front-again.jpg'))
  fireEvent.click(screen.getByRole('button', { name: 'Take it in' }))
  expect(await screen.findByRole('heading', { name: 'Item card' })).toBeInTheDocument()
  const [, again] = posted(calls, '/items')
  expect(await formFields(again.request)).toContainEqual(['keep_photos', 'false'])
  expect((await formFields(again.request)).filter(([name]) => name === 'photos')).toHaveLength(2)
})

test('a photo kept after the prompt still gets the repeat photo check', async () => {
  const calls = stubApi({
    'POST /items': () => {
      const count = posted(calls, '/items').length
      if (count === 1) return Response.json(retake(1), { status: 409 })
      if (count === 2) return Response.json(repeat, { status: 409 })
      return Response.json(item, { status: 201 })
    },
  })
  renderPage()
  await takeItemIn()
  fireEvent.click(await screen.findByRole('button', { name: 'Use it anyway' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('This may have been rejected before')
  fireEvent.click(screen.getByRole('button', { name: 'Take it in anyway' }))

  expect(await screen.findByRole('heading', { name: 'Item card' })).toBeInTheDocument()
  const [, , last] = posted(calls, '/items')
  expect(await formFields(last.request)).toContainEqual(['keep_photos', 'true'])
  expect(await formFields(last.request)).toContainEqual(['allow_repeat', 'true'])
})

test('changing the photos while the prompt shows clears it', async () => {
  stubApi({ 'POST /items': () => Response.json(retake(1), { status: 409 }) })
  renderPage()
  await takeItemIn()
  expect(await screen.findByRole('alert')).toHaveTextContent('Take this photo again?')

  fireEvent.click(screen.getByRole('button', { name: 'Remove photo 1' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
