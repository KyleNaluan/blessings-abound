import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { SettingsPage } from '@/api/settings'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const seeded = { updated_at: null, updated_by_name: null }
const settings: SettingsPage = {
  box_sizes: {
    ...seeded,
    value: {
      boxes: [
        { kind: 'mailer', length_in: 13, width_in: 10, height_in: null },
        { kind: 'box', length_in: 10, width_in: 8, height_in: 6 },
      ],
    },
  },
  seasonal_calendar: {
    ...seeded,
    value: {
      seasons: [
        {
          name: 'Coats and jackets',
          category: 'apparel',
          match_words: ['coat', 'jacket'],
          months: [8, 9, 10, 11, 12, 1],
        },
      ],
    },
  },
  worth_listing: { ...seeded, value: { threshold_cents: 3000 } },
  fees: { ...seeded, value: { fee_rate: 0.136, per_order_fee_cents: 40, supplies_cents: 150 } },
  ask_to_sale: { ...seeded, value: { apparel: 0.645, electronics_games: 0.94 } },
  shipping_weight: {
    ...seeded,
    value: {
      ounce_tiers_oz: [4, 8, 12, 15.999],
      max_weight_oz: 1120,
      max_length_plus_girth_in: 130,
      dim_weight_min_cubic_in: 1728,
      dim_weight_divisor: 139,
    },
  },
}
const SAVED_AT = '2026-11-03T15:00:00+00:00'

type Call = { method: string; path: string; body: unknown }

// A stand-in for the API that records each call, with any route overridable by a test.
function stubApi({
  role = 'manager',
  overrides = {},
}: {
  role?: string
  overrides?: Record<string, () => Response | Promise<Response>>
} = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      const key = `${request.method} ${path}`
      const body = request.method === 'PUT' ? await request.clone().json() : undefined
      calls.push({ method: request.method, path, body })
      if (overrides[key]) return overrides[key]()
      if (key === 'GET /me') return Response.json({ status: 'active', role })
      if (key === 'GET /health') return Response.json({ status: 'ok' })
      if (key === 'GET /settings') return Response.json(settings)
      if (request.method === 'PUT' && path.startsWith('/settings/')) {
        const section = path.slice('/settings/'.length).replaceAll('-', '_') as keyof SettingsPage
        const { value } = body as { value: unknown }
        return Response.json({
          ...settings,
          [section]: { value, updated_at: SAVED_AT, updated_by_name: 'Demo Manager' },
        })
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

function renderAt(path = '/app/settings') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

async function sectionNamed(name: string) {
  const heading = await screen.findByRole('heading', { level: 2, name })
  return within(heading.closest('section') as HTMLElement)
}

test('a manager sees each section with its current values', async () => {
  stubApi()
  renderAt()
  const worth = await sectionNamed('Worth listing')
  expect(worth.getByLabelText('Worth-listing price')).toHaveValue('30.00')
  const fees = await sectionNamed('Fees')
  expect(fees.getByLabelText('Fee rate')).toHaveValue('13.6')
  expect(fees.getByLabelText('Per-order fee')).toHaveValue('0.40')
  expect(fees.getByLabelText('Supplies')).toHaveValue('1.50')
  const seasons = await sectionNamed('Seasonal calendar')
  expect(seasons.getByLabelText('Words to match')).toHaveValue('coat, jacket')
  expect(seasons.getByRole('checkbox', { name: 'January' })).toBeChecked()
  expect(seasons.getByRole('checkbox', { name: 'July' })).not.toBeChecked()
  const boxes = await sectionNamed('Box sizes')
  expect(boxes.getAllByRole('group', { name: /^Size/ })).toHaveLength(2)
  const shipping = await sectionNamed('Shipping weight rules')
  expect(shipping.getByLabelText('Ounce tiers (oz)')).toHaveValue('4, 8, 12, 15.999')
  expect(screen.getAllByText('No one has changed these since setup.')).toHaveLength(6)
})

test('staff are refused without asking the API for the settings', async () => {
  const calls = stubApi({ role: 'staff' })
  renderAt()
  expect(
    await screen.findByText('Only a manager can see and change the settings.'),
  ).toBeInTheDocument()
  expect(calls.some((call) => call.path.startsWith('/settings'))).toBe(false)
})

test('the home page links to Settings for a manager only', async () => {
  stubApi()
  renderAt('/app')
  expect(await screen.findByRole('link', { name: 'Settings' })).toHaveAttribute(
    'href',
    '/app/settings',
  )
})

test('the home page has no Settings link for staff', async () => {
  stubApi({ role: 'staff' })
  renderAt('/app')
  await screen.findByRole('link', { name: 'Appraise an item' })
  expect(screen.queryByRole('link', { name: 'Settings' })).not.toBeInTheDocument()
})

test('shows loading, then an error that can be tried again', async () => {
  // The first load waits for the test, so the loading state is seen before the failure.
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => (release = resolve))
  let loads = 0
  stubApi({
    overrides: {
      'GET /settings': async () => {
        loads += 1
        if (loads > 1) return Response.json(settings)
        await held
        throw new TypeError('Failed to fetch')
      },
    },
  })
  renderAt()
  expect(await screen.findByText('Loading the settings...')).toBeInTheDocument()
  release()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent("We couldn't reach the API.")
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await sectionNamed('Fees')).toBeTruthy()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('saving a section sends its value with the time it was loaded', async () => {
  const calls = stubApi()
  renderAt()
  const worth = await sectionNamed('Worth listing')
  fireEvent.change(worth.getByLabelText('Worth-listing price'), { target: { value: '45.5' } })
  fireEvent.click(worth.getByRole('button', { name: 'Save the worth-listing price' }))

  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  expect(screen.getByText(/Last changed by Demo Manager/)).toBeInTheDocument()
  // Each section shows once after a save, with the saved one rebuilt from the API's copy.
  expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(6)
  expect(screen.getByLabelText('Worth-listing price')).toHaveValue('45.50')
  expect(calls.find((call) => call.method === 'PUT')).toEqual({
    method: 'PUT',
    path: '/settings/worth-listing',
    body: { value: { threshold_cents: 4550 }, expected_updated_at: null },
  })
})

test('the fee rate is sent as a fraction and the money as cents', async () => {
  const calls = stubApi()
  renderAt()
  const fees = await sectionNamed('Fees')
  fireEvent.change(fees.getByLabelText('Fee rate'), { target: { value: '12.9' } })
  fireEvent.change(fees.getByLabelText('Per-order fee'), { target: { value: '0.3' } })
  fireEvent.click(fees.getByRole('button', { name: 'Save the fees' }))
  await screen.findByText('Saved.')
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
    value: { fee_rate: 0.129, per_order_fee_cents: 30, supplies_cents: 150 },
    expected_updated_at: null,
  })
})

test('a value that is not a number is caught before the API is called', async () => {
  const calls = stubApi()
  renderAt()
  const worth = await sectionNamed('Worth listing')
  fireEvent.change(worth.getByLabelText('Worth-listing price'), { target: { value: 'thirty' } })
  fireEvent.click(worth.getByRole('button', { name: 'Save the worth-listing price' }))

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Enter the worth-listing price in dollars, such as 30.00.')
  expect(alert).toHaveFocus()
  expect(worth.getByLabelText('Worth-listing price')).toHaveAttribute('aria-invalid', 'true')
  expect(calls.some((call) => call.method === 'PUT')).toBe(false)
})

test("the API's reasons are shown plainly, with the row they are about", async () => {
  stubApi({
    overrides: {
      'PUT /settings/box-sizes': () =>
        Response.json(
          {
            detail: [
              {
                loc: ['body', 'value', 'boxes', 1],
                msg: 'Value error, A box needs a height.',
                type: 'value_error',
              },
              {
                loc: ['body', 'value'],
                msg: 'Value error, 10x8x6 is in the list twice.',
                type: 'value_error',
              },
            ],
          },
          { status: 422 },
        ),
    },
  })
  renderAt()
  const boxes = await sectionNamed('Box sizes')
  fireEvent.click(boxes.getByRole('button', { name: 'Save the box sizes' }))
  const alert = await screen.findByRole('alert')
  expect(
    within(alert)
      .getAllByRole('listitem')
      .map((item) => item.textContent),
  ).toEqual(['Size 2: A box needs a height.', '10x8x6 is in the list twice.'])
})

test('a save from a stale page says so and reloads the settings', async () => {
  const stale =
    'Another manager changed these settings after you opened the page. Reload the page to see their change, then make yours again.'
  const calls = stubApi({
    overrides: { 'PUT /settings/fees': () => Response.json({ detail: stale }, { status: 409 }) },
  })
  renderAt()
  const fees = await sectionNamed('Fees')
  fireEvent.change(fees.getByLabelText('Fee rate'), { target: { value: '20' } })
  fireEvent.click(fees.getByRole('button', { name: 'Save the fees' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(stale)

  fireEvent.click(within(alert).getByRole('button', { name: 'Reload the settings' }))
  const reloaded = await sectionNamed('Fees')
  await waitFor(() => expect(reloaded.getByLabelText('Fee rate')).toHaveValue('13.6'))
  expect(calls.filter((call) => call.path === '/settings')).toHaveLength(2)
})

test('a season can be added with its words and months', async () => {
  const calls = stubApi()
  renderAt()
  const seasons = await sectionNamed('Seasonal calendar')
  fireEvent.click(seasons.getByRole('button', { name: 'Add a season' }))
  const added = within(seasons.getByRole('group', { name: 'Season 2' }))
  fireEvent.change(added.getByLabelText('Name'), { target: { value: 'Swimwear' } })
  fireEvent.change(added.getByLabelText('Words to match'), {
    target: { value: 'swimsuit, , bikini ' },
  })
  fireEvent.click(added.getByRole('checkbox', { name: 'July' }))
  fireEvent.click(added.getByRole('checkbox', { name: 'June' }))
  fireEvent.click(seasons.getByRole('button', { name: 'Save the calendar' }))
  await screen.findByText('Saved.')

  const body = calls.find((call) => call.method === 'PUT')?.body as {
    value: { seasons: unknown[] }
  }
  expect(body.value.seasons[1]).toEqual({
    name: 'Swimwear',
    category: 'apparel',
    match_words: ['swimsuit', 'bikini'],
    months: [6, 7],
  })
})

test('a box size can be removed, and a mailer is sent with no height', async () => {
  const calls = stubApi()
  renderAt()
  const boxes = await sectionNamed('Box sizes')
  fireEvent.click(boxes.getByRole('button', { name: 'Remove size 2' }))
  fireEvent.click(boxes.getByRole('button', { name: 'Save the box sizes' }))
  await screen.findByText('Saved.')
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({
    value: { boxes: [{ kind: 'mailer', length_in: 13, width_in: 10, height_in: null }] },
    expected_updated_at: null,
  })
})
