import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import App from '@/App'
import type { Person } from '@/api/team'
import { fake, fakeSession } from '@/test/fakeSupabase'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

// The signed-in manager is user-1, the id the fake Supabase session carries.
const kim: Person = {
  auth_user_id: 'user-1',
  created_at: '2026-11-01T00:00:00Z',
  username: 'kim.lee',
  display_name: 'Kim Lee',
  email: 'kim@store.example',
  role: 'manager',
  status: 'active',
}
const sam: Person = {
  auth_user_id: 'user-2',
  created_at: '2026-11-01T00:00:00Z',
  username: 'sam.ortiz',
  display_name: 'Sam Ortiz',
  email: null,
  role: 'staff',
  status: 'temporary_password',
}
const dana: Person = {
  auth_user_id: 'user-3',
  created_at: '2026-11-01T00:00:00Z',
  username: 'dana.fox',
  display_name: 'Dana Fox',
  email: 'dana@store.example',
  role: 'manager',
  status: 'deactivated',
}

type Call = { method: string; path: string; body: unknown }

// A stand-in for the API that records each call, with any route overridable by a test.
function stubApi({
  role = 'manager',
  people = [kim, sam, dana],
  overrides = {},
}: {
  role?: string
  people?: Person[]
  overrides?: Record<string, () => Response | Promise<Response>>
} = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      const key = `${request.method} ${path}`
      const text = request.method === 'GET' ? '' : await request.clone().text()
      calls.push({ method: request.method, path, body: text ? JSON.parse(text) : undefined })
      if (overrides[key]) return overrides[key]()
      if (key === 'GET /me') return Response.json({ ...kim, role })
      if (key === 'GET /health') return Response.json({ status: 'ok' })
      if (key === 'GET /team/people') return Response.json(people)
      throw new Error(`unexpected ${key}`)
    }),
  )
  return calls
}

beforeEach(() => fake.reset(fakeSession()))

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderAt(path = '/app/team') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

// The list item whose name line starts with this name.
async function rowFor(name: string) {
  const item = await waitFor(() => {
    const found = screen
      .getAllByRole('listitem')
      .find((li) => li.querySelector('p')?.textContent?.startsWith(name))
    if (!found) throw new Error(`no row for ${name}`)
    return found
  })
  return within(item)
}

async function manage(name: string) {
  const row = await rowFor(name)
  fireEvent.click(row.getByRole('button', { name: `Manage ${name}` }))
  return row
}

test('a manager sees everyone with their username, email, role and status', async () => {
  stubApi()
  renderAt()
  expect(await screen.findByRole('heading', { level: 2, name: 'People (3)' })).toBeInTheDocument()
  const sams = await rowFor('Sam Ortiz')
  expect(sams.getByText(/sam\.ortiz/)).toHaveTextContent('sam.ortiz · , no email')
  expect(sams.getByText('Staff')).toBeInTheDocument()
  expect(sams.getByText('Temporary password')).toBeInTheDocument()
  const kims = await rowFor('Kim Lee')
  expect(kims.getByText('(you)')).toBeInTheDocument()
  expect(kims.getByText(/kim@store\.example/)).toBeInTheDocument()
  expect((await rowFor('Dana Fox')).getByText('Deactivated')).toBeInTheDocument()
})

test('staff are refused without asking the API for the team', async () => {
  const calls = stubApi({ role: 'staff' })
  renderAt()
  expect(await screen.findByText('Only a manager can see and change the team.')).toBeInTheDocument()
  expect(calls.some((call) => call.path.startsWith('/team'))).toBe(false)
})

test('the home page links to Team for a manager', async () => {
  stubApi()
  renderAt('/app')
  expect(await screen.findByRole('link', { name: 'Team' })).toHaveAttribute('href', '/app/team')
})

test('the home page has no Team link for staff', async () => {
  stubApi({ role: 'staff' })
  renderAt('/app')
  await screen.findByRole('link', { name: 'Appraise an item' })
  expect(screen.queryByRole('link', { name: 'Team' })).not.toBeInTheDocument()
})

test('shows loading, then an error that can be tried again', async () => {
  // The first load waits for the test, so the loading state is seen before the failure.
  let release: () => void = () => {}
  const held = new Promise<void>((resolve) => (release = resolve))
  let loads = 0
  stubApi({
    overrides: {
      'GET /team/people': async () => {
        loads += 1
        if (loads > 1) return Response.json([kim])
        await held
        throw new TypeError('Failed to fetch')
      },
    },
  })
  renderAt()
  expect(await screen.findByText('Loading the team...')).toBeInTheDocument()
  release()
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent("We couldn't reach the API.")
  fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('heading', { name: 'People (1)' })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a missing field is caught before the API is called', async () => {
  const calls = stubApi()
  renderAt()
  fireEvent.click(await screen.findByRole('button', { name: 'Add a person' }))
  fireEvent.click(screen.getByLabelText('Email them an invite'))
  fireEvent.click(screen.getByRole('button', { name: 'Send the invite' }))
  const summary = await screen.findByRole('alert')
  expect(summary).toHaveTextContent('Enter their name')
  expect(summary).toHaveTextContent('Enter a username')
  expect(summary).toHaveTextContent('Enter their email address')
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
})

test('inviting someone sends their details and lists them as invited', async () => {
  const priya: Person = {
    auth_user_id: 'user-4',
    created_at: '2026-11-01T00:00:00Z',
    username: 'priya.shah',
    display_name: 'Priya Shah',
    email: 'priya@store.example',
    role: 'staff',
    status: 'invited',
  }
  const calls = stubApi({
    overrides: { 'POST /team/people/invite': () => Response.json(priya, { status: 201 }) },
  })
  renderAt()
  fireEvent.click(await screen.findByRole('button', { name: 'Add a person' }))
  fireEvent.click(screen.getByLabelText('Email them an invite'))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Priya Shah ' } })
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'priya.shah' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'priya@store.example' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send the invite' }))
  const row = await rowFor('Priya Shah')
  expect(row.getByText('Invited')).toBeInTheDocument()
  expect(row.getByRole('status')).toHaveTextContent(
    "We've emailed an invite to priya@store.example.",
  )
  expect(calls.find((call) => call.path === '/team/people/invite')?.body).toEqual({
    display_name: 'Priya Shah',
    username: 'priya.shah',
    email: 'priya@store.example',
    role: 'staff',
  })
})

test('a username with a temporary password shows the password once', async () => {
  const lee: Person = {
    auth_user_id: 'user-5',
    created_at: '2026-11-01T00:00:00Z',
    username: 'lee.park',
    display_name: 'Lee Park',
    email: null,
    role: 'manager',
    status: 'temporary_password',
  }
  const calls = stubApi({
    overrides: {
      'POST /team/people/temporary-password': () =>
        Response.json({ person: lee, temporary_password: 'hBii-yokG-7hGn-PZ2z' }, { status: 201 }),
    },
  })
  renderAt()
  fireEvent.click(await screen.findByRole('button', { name: 'Add a person' }))
  fireEvent.click(screen.getByLabelText('Make a username with a temporary password'))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Lee Park' } })
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'lee.park' } })
  fireEvent.click(screen.getByLabelText('Manager'))
  fireEvent.click(screen.getByRole('button', { name: 'Create the username' }))
  const shown = await screen.findByRole('region', { name: 'Temporary password for Lee Park' })
  expect(shown).toHaveFocus()
  expect(shown).toHaveTextContent('hBii-yokG-7hGn-PZ2z')
  expect(calls.find((call) => call.path === '/team/people/temporary-password')?.body).toEqual({
    display_name: 'Lee Park',
    username: 'lee.park',
    email: null,
    role: 'manager',
  })
  fireEvent.click(within(shown).getByRole('button', { name: 'Done, hide it' }))
  expect(screen.queryByText('hBii-yokG-7hGn-PZ2z')).not.toBeInTheDocument()
  expect((await rowFor('Lee Park')).getByText('Temporary password')).toBeInTheDocument()
})

test("the API's reason for refusing a new person is shown in the summary", async () => {
  stubApi({
    overrides: {
      'POST /team/people/temporary-password': () =>
        Response.json({ detail: 'That username is taken.' }, { status: 409 }),
    },
  })
  renderAt()
  fireEvent.click(await screen.findByRole('button', { name: 'Add a person' }))
  fireEvent.click(screen.getByLabelText('Make a username with a temporary password'))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Sam Again' } })
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'sam.ortiz' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create the username' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('That username is taken.')
  expect(screen.getByRole('heading', { name: 'Add a person' })).toBeInTheDocument()
})

test("changing someone's role saves it and says so", async () => {
  const calls = stubApi({
    overrides: {
      'PATCH /team/people/user-2': () => Response.json({ ...sam, role: 'manager' }),
    },
  })
  renderAt()
  const row = await manage('Sam Ortiz')
  fireEvent.click(row.getByRole('button', { name: 'Save the role' }))
  expect(row.getByText('Sam Ortiz is already staff. Choose the other role.')).toBeInTheDocument()
  fireEvent.click(row.getByLabelText('Manager'))
  fireEvent.click(row.getByRole('button', { name: 'Save the role' }))
  await waitFor(() =>
    expect(row.getByRole('status')).toHaveTextContent('Sam Ortiz is now manager.'),
  )
  expect(calls.find((call) => call.method === 'PATCH')?.body).toEqual({ role: 'manager' })
})

test('a new temporary password is asked about first and then shown once', async () => {
  const calls = stubApi({
    overrides: {
      'POST /team/people/user-2/temporary-password': () =>
        Response.json({ person: sam, temporary_password: 'aaaa-bbbb-cccc-dddd' }),
    },
  })
  renderAt()
  const row = await manage('Sam Ortiz')
  fireEvent.click(row.getByRole('button', { name: 'Give a new temporary password' }))
  expect(row.getByText("Replace Sam Ortiz's password with a new temporary one?")).toHaveFocus()
  fireEvent.click(row.getByRole('button', { name: 'Cancel' }))
  expect(calls.some((call) => call.method === 'POST')).toBe(false)
  fireEvent.click(row.getByRole('button', { name: 'Give a new temporary password' }))
  fireEvent.click(row.getByRole('button', { name: 'Yes, replace it' }))
  const shown = await screen.findByRole('region', { name: 'Temporary password for Sam Ortiz' })
  expect(shown).toHaveTextContent('aaaa-bbbb-cccc-dddd')
})

test('deactivating asks first, and a deactivated person can be reactivated', async () => {
  stubApi({
    overrides: {
      'POST /team/people/user-2/deactivate': () => Response.json({ ...sam, status: 'deactivated' }),
      'POST /team/people/user-3/reactivate': () => Response.json({ ...dana, status: 'active' }),
    },
  })
  renderAt()
  const sams = await manage('Sam Ortiz')
  fireEvent.click(sams.getByRole('button', { name: 'Deactivate Sam Ortiz' }))
  fireEvent.click(sams.getByRole('button', { name: 'Yes, deactivate' }))
  await waitFor(() =>
    expect(sams.getByRole('status')).toHaveTextContent('Sam Ortiz is deactivated.'),
  )
  expect(sams.getByText('Deactivated', { selector: 'p' })).toBeInTheDocument()

  const danas = await manage('Dana Fox')
  fireEvent.click(danas.getByRole('button', { name: 'Reactivate Dana Fox' }))
  await waitFor(() =>
    expect(danas.getByRole('status')).toHaveTextContent('Dana Fox can sign in again.'),
  )
  expect(danas.getByText('Active')).toBeInTheDocument()
})

test('a manager is told plainly they cannot deactivate themselves or the last manager', async () => {
  stubApi()
  renderAt()
  const row = await manage('Kim Lee')
  expect(
    row.getByText("You can't deactivate yourself. Another manager can do it for you."),
  ).toBeInTheDocument()
  expect(
    row.getByText(/You're the last active manager, so this account stays a manager/),
  ).toBeInTheDocument()
  expect(row.queryByRole('button', { name: /Deactivate/ })).not.toBeInTheDocument()
  expect(row.queryByRole('button', { name: 'Save the role' })).not.toBeInTheDocument()
  expect(
    row.queryByRole('button', { name: 'Give a new temporary password' }),
  ).not.toBeInTheDocument()
})

test("the API's refusal of a change is shown in the person's panel", async () => {
  stubApi({
    people: [kim, { ...sam, role: 'manager', status: 'active' }],
    overrides: {
      'POST /team/people/user-2/deactivate': () =>
        Response.json(
          { detail: 'This is the last active manager, so it has to stay.' },
          { status: 409 },
        ),
    },
  })
  renderAt()
  const row = await manage('Sam Ortiz')
  fireEvent.click(row.getByRole('button', { name: 'Deactivate Sam Ortiz' }))
  fireEvent.click(row.getByRole('button', { name: 'Yes, deactivate' }))
  const alert = await row.findByRole('alert')
  expect(alert).toHaveTextContent('This is the last active manager, so it has to stay.')
  expect(alert).toHaveFocus()
})
