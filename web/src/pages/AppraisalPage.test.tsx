import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const item = { id: 'item-1', sku: 'PLACEHOLDER-1', status: 'intake', photo_keys: ['k'] }
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
const appraisal = {
  id: 'appraisal-1',
  item_id: 'item-1',
  price_low_cents: 2500,
  price_typical_cents: 3500,
  price_high_cents: 4800,
  net_after_fees_cents: 2834,
  recommendation: 'yes',
  explanation: 'Placeholder price.',
}
const savedRow = {
  id: 'decision-1',
  item_id: 'item-1',
  sku: 'PLACEHOLDER-1',
  brand: 'Carhartt',
  product: 'Canvas jacket',
  price_typical_cents: 3500,
  decision: 'no',
  decided_by_name: 'Demo Staff',
  decided_at: '2026-11-01T15:00:00+00:00',
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

async function pickPhoto() {
  const input = await screen.findByLabelText('Take or choose a photo')
  fireEvent.change(input, {
    target: { files: [new File(['photo'], 'item.jpg', { type: 'image/jpeg' })] },
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

  await pickPhoto()
  await confirmTheCard()

  expect(await screen.findByRole('heading', { name: 'Price range' })).toBeInTheDocument()
  expect(screen.getAllByText('Canvas jacket')).toHaveLength(1)
  expect(screen.getAllByText('Placeholder')).toHaveLength(1)
  expect(screen.getByText('$35.00')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: "No, don't list it" }))

  expect(await screen.findByRole('status')).toHaveTextContent('Saved your decision: no.')
  const row = await screen.findByRole('listitem')
  expect(row).toHaveTextContent('Canvas jacket')
  expect(row).toHaveTextContent('Demo Staff')

  const decision = calls.find((call) => call.path.endsWith('/decisions') && call.method === 'POST')
  expect(await decision?.request.json()).toEqual({ appraisal_id: 'appraisal-1', decision: 'no' })
})

test('sends the sign-in token and the photo as a file part', async () => {
  const calls = stubApi()
  renderPage()
  await pickPhoto()
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
  await pickPhoto()
  await confirmTheCard()

  expect(await screen.findByRole('alert')).toHaveTextContent('This item has no card yet.')

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: 'Price range' })).toBeInTheDocument()
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
  await pickPhoto()
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
  await pickPhoto()

  expect(await screen.findByLabelText('Brand')).toHaveValue('Carhartt')
  expect(screen.getByLabelText('Color')).toHaveValue('Brown')
  expect(screen.getByText('High')).toBeInTheDocument()
  expect(screen.queryByText(/isn't sure/)).not.toBeInTheDocument()
  expect(calls.some((call) => call.path.endsWith('/appraisals'))).toBe(false)
})

test('sends what staff changed and shows the confirmed card', async () => {
  const calls = stubApi()
  renderPage()
  await pickPhoto()

  fireEvent.change(await screen.findByLabelText('Brand'), { target: { value: 'Dickies' } })
  fireEvent.change(screen.getByLabelText('Exact model'), { target: { value: 'Eisenhower' } })
  fireEvent.change(screen.getByLabelText('Category'), {
    target: { value: 'electronics_games' },
  })
  await confirmTheCard()

  await screen.findByRole('heading', { name: 'Price range' })
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
  await pickPhoto()

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
  await pickPhoto()
  fireEvent.change(await screen.findByLabelText('Brand'), { target: { value: 'Dickies' } })
  await confirmTheCard()

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the card.')
  expect(screen.getByLabelText('Brand')).toHaveValue('Dickies')

  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await confirmTheCard()

  expect(await screen.findByRole('heading', { name: 'Price range' })).toBeInTheDocument()
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
  await pickPhoto()
  await confirmTheCard()
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, list it' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Appraise another item' }))

  await waitFor(() =>
    expect(screen.queryByRole('heading', { name: 'Item card' })).not.toBeInTheDocument(),
  )
  expect(screen.getByLabelText('Take or choose a photo')).toBeInTheDocument()
})

test('sends people who are not signed in to the sign-in page', async () => {
  fake.reset()
  renderPage()
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
})
