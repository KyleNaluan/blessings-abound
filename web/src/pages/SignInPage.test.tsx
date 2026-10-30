import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import { authError, fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

beforeEach(() => {
  fake.reset()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
})

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
  expect(summary).toHaveTextContent('Your username, email or password is wrong')
  expect(summary).toHaveFocus()
  expect(screen.getByLabelText('Password')).toHaveValue('')
})

test('a username matches no account until usernames exist', async () => {
  renderAt('/sign-in')
  fillIn('Username or email', 'demo.staff')
  fillIn('Password', 'anything at all')
  submit('Sign in')
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Your username, email or password is wrong',
  )
  expect(fake.auth.signInWithPassword).not.toHaveBeenCalled()
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
  acceptSignIn({ temporary_password: true })
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
  expect(fake.auth.updateUser).not.toHaveBeenCalled()

  fake.auth.updateUser.mockImplementation(async () => {
    const session = fakeSession({ temporary_password: false })
    fake.emit('USER_UPDATED', session)
    return { data: { user: session.user }, error: null }
  })
  fillIn('Type it again', 'a new long password')
  submit('Save password and continue')
  expect(await screen.findByRole('heading', { name: "You're signed in" })).toBeInTheDocument()
  expect(fake.auth.updateUser).toHaveBeenCalledWith({
    password: 'a new long password',
    data: { temporary_password: false },
  })
})

test('someone on a temporary password cannot skip to the app', async () => {
  fake.reset(fakeSession({ temporary_password: true }))
  renderAt('/app')
  expect(await screen.findByRole('heading', { name: 'Choose your password' })).toBeInTheDocument()
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
