import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import { authError, fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const COULD_NOT_SIGN_IN = "We couldn't sign in. Check your details or ask your manager."
const ACTIVE = {
  auth_user_id: 'user-1',
  username: 'demo.staff',
  display_name: 'Demo Staff',
  email: null,
  role: 'staff',
  status: 'active',
  created_at: '2026-11-01T00:00:00+00:00',
}
const TEMPORARY = { ...ACTIVE, status: 'temporary_password' }
const INVITED = { ...ACTIVE, status: 'invited' }

beforeEach(() => {
  fake.reset()
  stubApi()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Answers the API routes sign-in uses, where `me` is who the signed-in person is.
function stubApi(
  routes: Record<string, () => Response> = {},
  me: Record<string, unknown> = ACTIVE,
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const { pathname } = new URL(request.url)
      const route = routes[`${request.method} ${pathname}`]
      if (route) return route()
      return Response.json(pathname === '/me' ? me : { status: 'ok' })
    }),
  )
}

function apiCalls(method: string, path: string): Request[] {
  const calls = vi.mocked(fetch).mock.calls.map(([request]) => request as Request)
  return calls.filter(
    (request) => request.method === method && new URL(request.url).pathname === path,
  )
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

async function findLabel(label: string) {
  await screen.findByLabelText(label)
  return label
}

function fillIn(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

function submit(name: string) {
  fireEvent.click(screen.getByRole('button', { name }))
}

// Signs in successfully as a person whose account has this metadata.
function acceptSignIn(userMetadata: Record<string, unknown> = {}) {
  fake.auth.signInWithPassword.mockImplementation(async () => {
    const session = fakeSession(userMetadata)
    fake.emit('SIGNED_IN', session)
    return { data: { user: session.user, session }, error: null }
  })
}

test('the page has no sign-up link and says where accounts come from', async () => {
  renderAt('/sign-in')
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  expect(document.title).toBe('Sign in - Turnstone')
  expect(screen.queryByRole('link', { name: /sign up|register|create/i })).toBeNull()
  expect(screen.getByText(/Accounts come from a store manager/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'reset your password' })).toHaveAttribute(
    'href',
    '/forgot-password',
  )
})

test('asks for both fields before trying to sign in', async () => {
  renderAt('/sign-in')
  submit('Sign in')
  expect(await screen.findByText('Enter your username or email')).toBeInTheDocument()
  expect(screen.getByText('Enter your password')).toBeInTheDocument()
  expect(screen.getByLabelText('Username or email')).toHaveFocus()
  expect(screen.getByLabelText('Username or email')).toHaveAttribute('aria-invalid', 'true')
  expect(fake.auth.signInWithPassword).not.toHaveBeenCalled()
})

test('signs in with an email and goes to the app', async () => {
  acceptSignIn()
  renderAt('/sign-in')
  fillIn('Username or email', ' demo.staff@example.com ')
  fillIn('Password', 'correct horse battery')
  submit('Sign in')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  expect(fake.auth.signInWithPassword).toHaveBeenCalledWith({
    email: 'demo.staff@example.com',
    password: 'correct horse battery',
  })
})

test('shows the error summary for a wrong password, and clears the password', async () => {
  fake.auth.signInWithPassword.mockResolvedValue(authError('invalid_credentials'))
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff@example.com')
  fillIn('Password', 'wrong')
  submit('Sign in')
  const summary = await screen.findByRole('alert')
  expect(summary).toHaveTextContent('There is a problem')
  expect(summary).toHaveTextContent(COULD_NOT_SIGN_IN)
  expect(summary).toHaveFocus()
  expect(screen.getByLabelText('Password')).toHaveValue('')
})

test('a turned-off account signing in by email gets the same message as a wrong password', async () => {
  fake.auth.signInWithPassword.mockResolvedValue(authError('user_banned'))
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff@example.com')
  fillIn('Password', 'correct horse battery')
  submit('Sign in')
  const summary = await screen.findByRole('alert')
  expect(summary).toHaveTextContent(COULD_NOT_SIGN_IN)
  expect(summary).not.toHaveTextContent(/turned off/i)
})

test('signs in with a username through the API and never asks for the address', async () => {
  stubApi({
    'POST /auth/sign-in': () => Response.json({ access_token: 'access', refresh_token: 'refresh' }),
  })
  fake.auth.setSession.mockImplementation(async () => {
    const session = fakeSession()
    fake.emit('SIGNED_IN', session)
    return { data: { user: session.user, session }, error: null }
  })
  renderAt('/sign-in')
  fillIn('Username or email', ' demo.staff ')
  fillIn('Password', 'correct horse battery')
  submit('Sign in')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  const [request] = apiCalls('POST', '/auth/sign-in')
  expect(await request.clone().json()).toEqual({
    username: 'demo.staff',
    password: 'correct horse battery',
  })
  expect(fake.auth.setSession).toHaveBeenCalledWith({
    access_token: 'access',
    refresh_token: 'refresh',
  })
  expect(fake.auth.signInWithPassword).not.toHaveBeenCalled()
})

test('an email never goes through the API, so it works without one', async () => {
  acceptSignIn()
  renderAt('/sign-in')
  fillIn('Username or email', 'teammate@placeholder.example')
  fillIn('Password', 'correct horse battery')
  submit('Sign in')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  expect(apiCalls('POST', '/auth/sign-in')).toEqual([])
})

test.each([
  [401, COULD_NOT_SIGN_IN],
  [429, 'Too many tries. Wait a few minutes and try again.'],
])('shows what the API says for a refused username, status %i', async (status, detail) => {
  stubApi({ 'POST /auth/sign-in': () => Response.json({ detail }, { status }) })
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff')
  fillIn('Password', 'anything at all')
  submit('Sign in')
  expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  expect(fake.auth.setSession).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Password')).toHaveValue('')
})

test('says so when the API cannot be reached for a username', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff')
  fillIn('Password', 'anything at all')
  submit('Sign in')
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "We couldn't reach the sign-in service",
  )
})

test('there is no sign-up page to reach', async () => {
  renderAt('/sign-up')
  expect(
    await screen.findByRole('heading', { level: 1, name: /keep every shop in sync/ }),
  ).toBeInTheDocument()
})

test('says so when the sign-in service cannot be reached', async () => {
  fake.auth.signInWithPassword.mockResolvedValue(authError('unexpected_failure'))
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff@example.com')
  fillIn('Password', 'correct horse battery')
  submit('Sign in')
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "We couldn't reach the sign-in service",
  )
})

test('the Show button reveals the password', async () => {
  renderAt('/sign-in')
  const password = await screen.findByLabelText('Password')
  expect(password).toHaveAttribute('type', 'password')
  fireEvent.click(screen.getByRole('button', { name: 'Show' }))
  expect(password).toHaveAttribute('type', 'text')
  expect(screen.getByRole('button', { name: 'Hide' })).toHaveAttribute('aria-pressed', 'true')
})

test('a temporary password goes to choosing a password before anything else', async () => {
  let me: Record<string, unknown> = TEMPORARY
  stubApi({
    'GET /me': () => Response.json(me),
    'POST /me/password': () => {
      me = ACTIVE
      return Response.json(ACTIVE)
    },
  })
  acceptSignIn()
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff@example.com')
  fillIn('Password', 'temporary-1234')
  submit('Sign in')
  expect(await screen.findByRole('heading', { name: 'Choose your password' })).toBeInTheDocument()
  expect(screen.getByText(/You signed in with a temporary password/)).toBeInTheDocument()

  fillIn('New password', 'short')
  submit('Save password and continue')
  expect(
    await screen.findByText('Your password must be at least 10 characters'),
  ).toBeInTheDocument()

  fillIn('New password', 'a new long password')
  fillIn('Type it again', 'a different password')
  submit('Save password and continue')
  expect(await screen.findByText("The passwords don't match")).toBeInTheDocument()
  expect(apiCalls('POST', '/me/password')).toEqual([])

  fillIn('Type it again', 'a new long password')
  submit('Save password and continue')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  const [request] = apiCalls('POST', '/me/password')
  expect(await request.clone().json()).toEqual({ password: 'a new long password' })
  expect(fake.auth.updateUser).not.toHaveBeenCalled()
})

test('shows why the API refused a first password and stays on the page', async () => {
  const detail = 'Choose a password that is different from your current one'
  stubApi({ 'POST /me/password': () => Response.json({ detail }, { status: 422 }) }, TEMPORARY)
  fake.reset(fakeSession())
  renderAt('/choose-password')
  fillIn(await findLabel('New password'), 'the same password')
  fillIn('Type it again', 'the same password')
  submit('Save password and continue')
  expect(await screen.findByRole('alert')).toHaveTextContent(detail)
  expect(screen.getByRole('heading', { name: 'Choose your password' })).toBeInTheDocument()
})

test('an invite link lands on choosing a password with its own words', async () => {
  stubApi({}, INVITED)
  fake.reset(fakeSession())
  renderAt('/choose-password')
  expect(await screen.findByText(/finish setting up your account/)).toBeInTheDocument()
})

test('someone on a temporary password or an invite cannot skip to the app', async () => {
  stubApi({}, TEMPORARY)
  fake.reset(fakeSession())
  renderAt('/app')
  expect(await screen.findByRole('heading', { name: 'Choose your password' })).toBeInTheDocument()
})

test('a reset link for an ordinary account still goes straight to Supabase', async () => {
  fake.reset(fakeSession())
  fake.auth.updateUser.mockResolvedValue({ data: { user: fakeSession().user }, error: null })
  renderAt('/choose-password')
  expect(await screen.findByText('Choose a new password for your account.')).toBeInTheDocument()
  fillIn('New password', 'a new long password')
  fillIn('Type it again', 'a new long password')
  submit('Save password and continue')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  expect(fake.auth.updateUser).toHaveBeenCalledWith({ password: 'a new long password' })
  expect(apiCalls('POST', '/me/password')).toEqual([])
})

test('someone the API cannot place still reaches the app, where the API refuses them', async () => {
  stubApi({ 'GET /me': () => Response.json({ detail: 'no profile' }, { status: 403 }) })
  fake.reset(fakeSession())
  renderAt('/app')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
})

test('a used or expired reset link says how to get a new one', async () => {
  renderAt('/choose-password')
  expect(await screen.findByText(/This reset link has expired/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Send a new reset link' })).toHaveAttribute(
    'href',
    '/forgot-password',
  )
})

test('forgot password carries over what was typed and sends a reset email', async () => {
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff@example.com')
  fireEvent.click(screen.getByRole('link', { name: 'reset your password' }))
  expect(await screen.findByRole('heading', { name: 'Reset your password' })).toBeInTheDocument()
  expect(screen.getByLabelText('Username or email')).toHaveValue('demo.staff@example.com')

  submit('Send reset link')
  expect(await screen.findByText(/we've sent it a link to reset the password/)).toBeInTheDocument()
  expect(fake.auth.resetPasswordForEmail).toHaveBeenCalledWith('demo.staff@example.com', {
    redirectTo: `${window.location.origin}/choose-password`,
  })
})

test('forgot password with a username tells people without email to ask a manager', async () => {
  renderAt('/forgot-password')
  submit('Send reset link')
  expect(await screen.findByText('Enter your username or email')).toBeInTheDocument()

  fillIn('Username or email', 'demo.staff')
  submit('Send reset link')
  expect(
    await screen.findByText(/Ask a store manager to give you a temporary password/),
  ).toBeInTheDocument()
  expect(fake.auth.resetPasswordForEmail).not.toHaveBeenCalled()
})

test('forgot password shows an error when the email cannot be sent', async () => {
  fake.auth.resetPasswordForEmail.mockResolvedValue(authError('over_email_send_rate_limit'))
  renderAt('/forgot-password')
  fillIn('Username or email', 'demo.staff@example.com')
  submit('Send reset link')
  expect(await screen.findByRole('alert')).toHaveTextContent('Too many reset emails were sent')
})

test('forgot password says when the address cannot get email', async () => {
  fake.auth.resetPasswordForEmail.mockResolvedValue(authError('email_address_not_authorized'))
  renderAt('/forgot-password')
  fillIn('Username or email', 'demo.staff@example.com')
  submit('Send reset link')
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "We couldn't send an email to that address",
  )
})
