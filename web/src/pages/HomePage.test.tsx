import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router'

import App from '@/App'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderHome() {
  render(
    <MemoryRouter initialEntries={['/app']}>
      <App />
    </MemoryRouter>,
  )
}

// Answers the lists the home page counts, and anything else with an empty answer.
function answer(lists: Record<string, unknown>, role = 'manager') {
  return vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    if (path === '/me') return Response.json({ status: 'active', role, display_name: 'Hallee' })
    if (path in lists) {
      const body = lists[path]
      return body instanceof Response ? body : Response.json(body)
    }
    return Response.json({ status: 'ok' })
  })
}

const NONE = {
  '/approvals': {
    awaiting_approval: [],
    awaiting_storage: [],
    held_for_season: [],
    not_listed_online: [],
  },
  '/pick-list': [],
  '/attention': { open: [], resolved: [] },
}

test('welcomes the person by name and counts what is waiting on each list', async () => {
  vi.stubGlobal(
    'fetch',
    answer({
      '/approvals': { ...NONE['/approvals'], awaiting_approval: [{}, {}] },
      '/pick-list': [{}],
      '/attention': { open: [], resolved: [{}] },
    }),
  )
  renderHome()
  expect(
    await screen.findByRole('heading', { level: 1, name: 'Welcome, Hallee' }),
  ).toBeInTheDocument()
  expect(await screen.findByText('2 items to approve')).toBeInTheDocument()
  expect(await screen.findByText('1 sold item to pick')).toBeInTheDocument()
  expect(await screen.findByText('No problems to look at')).toBeInTheDocument()
})

test('shows only the username for an account with a hidden placeholder address', async () => {
  const session = fakeSession()
  session.user.email = 'demo.staff@accounts.turnstone.invalid'
  fake.reset(session)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok', commit: null })),
  )
  renderHome()
  expect(
    await screen.findByRole('heading', { level: 1, name: 'Welcome, demo.staff' }),
  ).toBeInTheDocument()
})

test('the navigation bar keeps the whole name on hover, because a long one is cut short', async () => {
  vi.stubGlobal('fetch', answer(NONE))
  renderHome()
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  const bar = nav.parentElement as HTMLElement
  expect(await within(bar).findByText('Hallee')).toHaveAttribute('title', 'Hallee')
})

test('a list the API cannot count still links to it, and the page says the API is down', async () => {
  vi.stubGlobal(
    'fetch',
    answer({ ...NONE, '/pick-list': new Response(null, { status: 500 }) }, 'staff'),
  )
  renderHome()
  expect(await screen.findByText('Open the list')).toBeInTheDocument()
  expect(screen.getByText(/^Can't reach the API/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Pick list.*Open the list/ })).toHaveAttribute(
    'href',
    '/app/pick-list',
  )
})

test('the API notice stays away while every count loads', async () => {
  vi.stubGlobal('fetch', answer(NONE, 'staff'))
  renderHome()
  expect(await screen.findByText('No sold items to pick')).toBeInTheDocument()
  expect(screen.queryByText(/^Can't reach the API/)).not.toBeInTheDocument()
})

test('staff are not shown the approvals count', async () => {
  vi.stubGlobal('fetch', answer(NONE, 'staff'))
  renderHome()
  expect(await screen.findByText('No sold items to pick')).toBeInTheDocument()
  expect(screen.queryByText(/to approve/)).not.toBeInTheDocument()
})

test('sends people who are not signed in to the sign-in page', async () => {
  fake.reset()
  renderHome()
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
})

test('signing out goes back to the landing page', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  renderHome()
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  expect(
    await screen.findByRole('heading', { level: 1, name: /keep every shop in sync/ }),
  ).toBeInTheDocument()
  await waitFor(() => expect(fake.auth.signOut).toHaveBeenCalled())
})

test('a failed sign-out stays on the page with a visible error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  fake.auth.signOut.mockRejectedValueOnce(new Error('network down'))
  renderHome()
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(/couldn't reach the sign-in service/i)
  expect(screen.getByRole('heading', { level: 1, name: /^Welcome/ })).toBeInTheDocument()
})

test('a sign-out that clears the session but returns an error still lands on the landing page', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  fake.auth.signOut.mockImplementationOnce(async () => {
    await new Promise((resolve) => setTimeout(resolve))
    fake.emit('SIGNED_OUT', null)
    return { error: { code: 'unexpected', message: 'server error', status: 500 } }
  })
  renderHome()
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  expect(
    await screen.findByRole('heading', { level: 1, name: /keep every shop in sync/ }),
  ).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('visiting the app after a successful sign-out reaches sign-in, not a blank page', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  function Revisit() {
    const navigate = useNavigate()
    return (
      <>
        <button onClick={() => navigate('/app')}>revisit app</button>
        <App />
      </>
    )
  }
  render(
    <MemoryRouter initialEntries={['/app']}>
      <Revisit />
    </MemoryRouter>,
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  await screen.findByRole('heading', { level: 1, name: /keep every shop in sync/ })
  fireEvent.click(screen.getByRole('button', { name: 'revisit app' }))
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
})

test.each([
  [
    'manager',
    [
      'Home',
      'Appraise',
      'Approvals',
      'Pick list',
      'Needs attention',
      'Dashboards',
      'Team',
      'Settings',
    ],
  ],
  ['staff', ['Home', 'Appraise', 'Pick list', 'Needs attention']],
])('a %s sees the bar links for their role', async (role, links) => {
  vi.stubGlobal('fetch', answer(NONE, role))
  renderHome()
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  await waitFor(() =>
    expect(
      within(nav)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(links),
  )
})
