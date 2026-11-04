import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { PickListEntry } from '@/api/approval'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

function entry(id: string, box: string | null, shelf: string | null): PickListEntry {
  return {
    item_id: id,
    sku: `RT1104260${id}`,
    full_sku: box ? `RT1104260${id} ${box}` : null,
    title: `Item ${id}`,
    box_code: box,
    location_code: shelf,
    package_weight_oz: box ? 22.4 : null,
  }
}

// In the order the API sends them, which is the order to walk the shelves.
const ENTRIES = [
  entry('1', '10x13', 'B1'),
  entry('2', '12x12x6', 'A2'),
  entry('3', '12x12x6', 'A10'),
  entry('4', null, null),
]

function stubApi(role: string, overrides: Record<string, () => Response> = {}) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const key = `${request.method} ${new URL(request.url).pathname}`
      calls.push(key)
      if (overrides[key]) return overrides[key]()
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      if (key === 'GET /pick-list') return Response.json(ENTRIES)
      if (key.startsWith('POST /items/') && key.endsWith('/picked')) {
        return new Response(null, { status: 204 })
      }
      throw new Error(`unexpected ${key}`)
    }),
  )
  return calls
}

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPickList() {
  render(
    <MemoryRouter initialEntries={['/app/pick-list']}>
      <App />
    </MemoryRouter>,
  )
}

test.each(['staff', 'manager'])('%s see sold items by box section, then shelf', async (role) => {
  stubApi(role)
  renderPickList()
  const headings = await screen.findAllByRole('heading', { level: 2 })
  expect(headings.map((heading) => heading.textContent)).toEqual([
    '10x13 mailer',
    '12x12x6 box',
    'No box recorded',
  ])
  const box = within(headings[1].closest('section') as HTMLElement)
  expect(box.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    expect.stringContaining('A2RT11042602 12x12x6Item 2'),
    expect.stringContaining('A10RT11042603 12x12x6Item 3'),
  ])
  expect(screen.getByText('No shelf recorded')).toBeInTheDocument()
})

test('a picked item leaves the list', async () => {
  const calls = stubApi('staff')
  renderPickList()
  fireEvent.click(await screen.findByRole('button', { name: 'Picked RT11042601 10x13' }))
  await waitFor(() =>
    expect(screen.queryByRole('heading', { name: '10x13 mailer' })).not.toBeInTheDocument(),
  )
  expect(calls).toContain('POST /items/1/picked')
})

test('a pick the API refuses stays on the list with the reason', async () => {
  stubApi('staff', {
    'POST /items/2/picked': () =>
      Response.json({ detail: "This item is picked, so it can't be picked." }, { status: 409 }),
  })
  renderPickList()
  fireEvent.click(await screen.findByRole('button', { name: 'Picked RT11042602 12x12x6' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "This item is picked, so it can't be picked.",
  )
  expect(screen.getByText('Item 2')).toBeInTheDocument()
})

test('an empty list says nothing is waiting', async () => {
  stubApi('staff', { 'GET /pick-list': () => Response.json([]) })
  renderPickList()
  expect(await screen.findByText('Nothing sold is waiting to be picked.')).toBeInTheDocument()
})

test('a list that fails to load can be tried again', async () => {
  let fail = true
  stubApi('staff', {
    'GET /pick-list': () =>
      fail
        ? Response.json({ detail: 'The database is down.' }, { status: 503 })
        : Response.json([]),
  })
  renderPickList()
  expect(await screen.findByRole('alert')).toHaveTextContent('The database is down.')
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByText('Nothing sold is waiting to be picked.')).toBeInTheDocument()
})
