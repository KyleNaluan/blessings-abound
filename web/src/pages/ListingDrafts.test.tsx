import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { Channel } from '@/api/appraisal'
import { fake, fakeSession } from '@/test/fakeSupabase'

import { ListingDrafts } from './ListingDrafts'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const draftA = {
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
const draftB = {
  ...draftA,
  id: 'draft-b',
  channel: 'channel_b',
  title: 'Carhartt canvas jacket, Brown - Pre-owned',
  category: 'Unisex',
  category_options: ['Menswear', 'Unisex'],
  source: 'template',
  fallback_reason: 'flagged',
  model_flags: [{ rule: 'banned_word', phrase: 'vintage', message: '"vintage" is banned.' }],
}
const rareFlag = {
  rule: 'banned_word',
  phrase: 'rare',
  message: '"rare" is a word listings never use.',
}

type Call = { method: string; path: string; request: Request }

function stubApi(overrides: Record<string, (request: Request) => Promise<Response>> = {}) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname
      const key = `${request.method} ${path}`
      calls.push({ method: request.method, path, request: request.clone() })
      if (overrides[key]) return overrides[key](request)
      switch (key) {
        case 'POST /items/item-1/drafts':
          return Response.json([draftA, draftB])
        case 'PATCH /items/item-1/drafts/channel_a': {
          const edit = await request.json()
          const flags = String(edit.title ?? '').includes('Rare') ? [rareFlag] : []
          return Response.json({ ...draftA, ...edit, flags, staff_edited: true })
        }
        case 'POST /items/item-1/drafts/submit':
          return Response.json(
            [draftA, draftB].map((row) => ({ ...row, state: 'awaiting_approval' })),
          )
        default:
          throw new Error(`unexpected ${key}`)
      }
    }),
  )
  return calls
}

const BOTH = ['channel_a', 'channel_b'] as const satisfies Channel[]

const sendButton = () => screen.getByRole('button', { name: 'Send for manager approval' })

const onSent = vi.fn()

beforeEach(() => {
  fake.reset(fakeSession())
  onSent.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('drafts the channels staff chose', async () => {
  const calls = stubApi({ 'POST /items/item-1/drafts': async () => Response.json([draftB]) })
  render(<ListingDrafts itemId="item-1" channels={['channel_b']} onSent={onSent} />)

  expect(await screen.findByRole('heading', { name: 'Channel B' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Channel A' })).not.toBeInTheDocument()
  expect(await calls[0].request.json()).toEqual({ channels: ['channel_b'] })
})

test('shows a draft per channel and says where each came from', async () => {
  stubApi()
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  expect(screen.getByText('Writing the listing...')).toBeInTheDocument()

  expect(await screen.findByRole('heading', { name: 'Channel A' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Channel B' })).toBeInTheDocument()
  expect(screen.getByText(/The model wrote this from the item card/)).toBeInTheDocument()
  expect(screen.getByText(/made claims the card doesn't support/)).toBeInTheDocument()
  expect(screen.getByText('It said: vintage.')).toBeInTheDocument()
  expect(screen.getAllByText('No changes yet.')).toHaveLength(2)
  expect(sendButton()).toBeEnabled()
})

test('a saved edit shows the checker flags and blocks sending until fixed', async () => {
  const calls = stubApi()
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  const [title] = await screen.findAllByLabelText('Title')

  fireEvent.change(title, { target: { value: 'Rare Carhartt jacket' } })
  expect(screen.getByText('Save your changes before sending.')).toBeInTheDocument()
  expect(sendButton()).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Save and check' }))

  expect(await screen.findByText('"rare" is a word listings never use.')).toBeInTheDocument()
  expect(screen.getByText('Fix the flagged claims before sending.')).toBeInTheDocument()
  expect(sendButton()).toBeDisabled()
  const patch = calls.find((call) => call.method === 'PATCH')
  expect(await patch?.request.json()).toEqual({
    title: 'Rare Carhartt jacket',
    description: draftA.description,
    category: draftA.category,
  })

  fireEvent.change(title, { target: { value: 'Carhartt jacket' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save and check' }))

  await waitFor(() => expect(sendButton()).toBeEnabled())
  expect(screen.getByText('Your changes are saved.')).toBeInTheDocument()
  expect(screen.queryByText('"rare" is a word listings never use.')).not.toBeInTheDocument()
})

test('an empty title is not saved', async () => {
  const calls = stubApi()
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  const [title] = await screen.findAllByLabelText('Title')
  fireEvent.change(title, { target: { value: '  ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save and check' }))

  expect(screen.getByText('Enter a title.')).toBeInTheDocument()
  expect(calls.some((call) => call.method === 'PATCH')).toBe(false)
})

test('a failed save keeps what staff typed', async () => {
  stubApi({
    'PATCH /items/item-1/drafts/channel_a': async () =>
      Response.json({ detail: 'Could not save the draft.' }, { status: 500 }),
  })
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  const [title] = await screen.findAllByLabelText('Title')
  fireEvent.change(title, { target: { value: 'Carhartt jacket' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save and check' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the draft.')
  expect(title).toHaveValue('Carhartt jacket')
})

test('sending locks the drafts', async () => {
  stubApi()
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  await screen.findByRole('heading', { name: 'Channel A' })
  fireEvent.click(sendButton())

  expect(await screen.findByRole('status')).toHaveTextContent('Sent to a manager for approval.')
  expect(onSent).toHaveBeenCalledOnce()
  expect(screen.queryByLabelText('Title')).not.toBeInTheDocument()
  expect(screen.queryByText(/Check it before sending/)).not.toBeInTheDocument()
  expect(screen.getByText('Carhartt canvas jacket - Pre-owned')).toBeInTheDocument()
})

test('a refused send says why and keeps the drafts open', async () => {
  stubApi({
    'POST /items/item-1/drafts/submit': async () =>
      Response.json({ detail: 'Fix the flagged claims on Channel B first.' }, { status: 409 }),
  })
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)
  await screen.findByRole('heading', { name: 'Channel A' })
  fireEvent.click(sendButton())

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Fix the flagged claims on Channel B first.',
  )
  expect(screen.getAllByLabelText('Title')).toHaveLength(2)
  expect(onSent).not.toHaveBeenCalled()
})

test('a failed draft can be tried again', async () => {
  let failing = true
  const calls = stubApi({
    'POST /items/item-1/drafts': async () =>
      failing
        ? Response.json({ detail: 'Decide to list this item first.' }, { status: 409 })
        : Response.json([draftA]),
  })
  render(<ListingDrafts itemId="item-1" channels={BOTH} onSent={onSent} />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Decide to list this item first.')
  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: 'Channel A' })).toBeInTheDocument()
  expect(calls.filter((call) => call.path === '/items/item-1/drafts')).toHaveLength(2)
})
