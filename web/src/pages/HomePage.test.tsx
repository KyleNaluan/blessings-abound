import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

test('shows the API health reported by /health', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  renderHome()
  expect(await screen.findByText('Working')).toBeInTheDocument()
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
  expect(await screen.findByText('Signed in as demo.staff.')).toBeInTheDocument()
})

test('shows the API as unreachable when the request fails', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  renderHome()
  expect(await screen.findByText("Can't reach it")).toBeInTheDocument()
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
  expect(screen.getByRole('heading', { level: 1, name: "You're signed in" })).toBeInTheDocument()
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
  ['manager', ['Approvals', 'Pick list', 'Needs attention', 'Dashboards', 'Settings', 'Team']],
  ['staff', ['Pick list', 'Needs attention']],
])('a %s sees the links for their role', async (role, links) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) =>
      new URL(request.url).pathname === '/me'
        ? Response.json({ status: 'active', role })
        : Response.json({ status: 'ok' }),
    ),
  )
  renderHome()
  await screen.findByRole('link', { name: 'Pick list' })
  await waitFor(() =>
    expect(
      screen
        .getAllByRole('link')
        .map((link) => link.textContent)
        .filter((name) =>
          ['Approvals', 'Pick list', 'Needs attention', 'Dashboards', 'Settings', 'Team'].includes(
            name ?? '',
          ),
        ),
    ).toEqual(links),
  )
})
