import { fireEvent, render, screen } from '@testing-library/react'

import { fake, fakeSession } from '@/test/fakeSupabase'

import { ChannelChoice } from './ChannelChoice'

vi.mock('@/auth/supabase', async () => ({
  supabase: (await import('@/test/fakeSupabase')).fake.client,
}))

const inSeason = {
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
const held = {
  channels: [
    { channel: 'channel_a', takes: true, why_not: null },
    {
      channel: 'channel_b',
      takes: false,
      why_not: 'Channel B needs a brand, and the item card has none.',
    },
  ],
  timing: {
    season: 'Swimwear',
    season_span: 'March to July',
    release_month: '2027-03-01',
  },
  reason:
    'Only Channel A takes it, because Channel B needs a brand and the card has none, and its season, Swimwear, runs from March to July, so hold it until March 2027.',
  reason_source: 'template',
  reason_fallback: 'model_failed',
}

function stubApi(answer: () => Response) {
  const fetch = vi.fn(async (request: Request) => {
    const key = `${request.method} ${new URL(request.url).pathname}`
    if (key !== 'GET /items/item-1/channels') throw new Error(`unexpected ${key}`)
    return answer()
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

const onChoose = vi.fn()
const writeButton = () => screen.getByRole('button', { name: 'Write the listing' })

beforeEach(() => {
  fake.reset(fakeSession())
  onChoose.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('an item in season can go on every channel that takes it now', async () => {
  stubApi(() => Response.json(inSeason))
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)
  expect(screen.getByText('Checking the channels...')).toBeInTheDocument()

  expect(await screen.findByText(inSeason.reason)).toBeInTheDocument()
  expect(screen.getByText('The model worded this reason from the rules.')).toBeInTheDocument()
  expect(screen.getByText('List now')).toBeInTheDocument()
  expect(screen.getByText('Coats and jackets, August to January')).toBeInTheDocument()
  expect(screen.queryByText(/held for its season/)).not.toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: 'Channel A' })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: 'Channel B' })).toBeChecked()

  fireEvent.click(writeButton())
  expect(onChoose).toHaveBeenCalledWith(['channel_a', 'channel_b'])
  expect(screen.getByText('Listing on Channel A and Channel B.')).toBeInTheDocument()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
})

test('an item out of season says how long it is held, and a refused channel says why', async () => {
  stubApi(() => Response.json(held))
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)

  expect(await screen.findByText(held.reason)).toBeInTheDocument()
  expect(
    screen.getByText("The model couldn't word the reason, so this is the fixed wording."),
  ).toBeInTheDocument()
  expect(screen.getByText('Hold until March 2027')).toBeInTheDocument()
  expect(screen.getByText('Swimwear, March to July')).toBeInTheDocument()
  expect(
    screen.getByText(
      "Once a manager approves it, it's held for its season, with March 2027 as its release month.",
    ),
  ).toBeInTheDocument()
  const channelB = screen.getByRole('checkbox', { name: 'Channel B' })
  expect(channelB).toBeDisabled()
  expect(channelB).not.toBeChecked()
  expect(channelB).toHaveAccessibleDescription(
    'Channel B needs a brand, and the item card has none.',
  )

  fireEvent.click(writeButton())
  expect(onChoose).toHaveBeenCalledWith(['channel_a'])
})

test('staff can leave out a channel but must keep at least one', async () => {
  stubApi(() => Response.json(inSeason))
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)

  fireEvent.click(await screen.findByRole('checkbox', { name: 'Channel A' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Channel B' }))
  expect(screen.getByText('Choose at least one channel.')).toBeInTheDocument()
  expect(writeButton()).toBeDisabled()

  // Ticked in the other order, the channels still go in channel order.
  fireEvent.click(screen.getByRole('checkbox', { name: 'Channel B' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Channel A' }))
  fireEvent.click(writeButton())
  expect(onChoose).toHaveBeenCalledWith(['channel_a', 'channel_b'])
})

test.each([
  ['not_configured', 'No model is set up here, so this is the fixed wording.'],
  ['flagged', "The model's wording named something the rules don't, so this is the fixed wording."],
])('a %s reason says it is the fixed wording', async (fallback, note) => {
  stubApi(() =>
    Response.json({ ...inSeason, reason_source: 'template', reason_fallback: fallback }),
  )
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)
  expect(await screen.findByText(note)).toBeInTheDocument()
})

test('an item that matches no season says so', async () => {
  stubApi(() =>
    Response.json({
      ...inSeason,
      timing: { season: null, season_span: null, release_month: null },
    }),
  )
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)
  expect(await screen.findByText('None')).toBeInTheDocument()
  expect(screen.getByText('List now')).toBeInTheDocument()
})

test('a failed check can be tried again', async () => {
  let failing = true
  const fetch = stubApi(() =>
    failing
      ? Response.json({ detail: 'Decide to list this item first.' }, { status: 409 })
      : Response.json(inSeason),
  )
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Decide to list this item first.')
  failing = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByText(inSeason.reason)).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(2)
})

test('an item held for its season can stay off online selling instead', async () => {
  const calls: { key: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const key = `${request.method} ${new URL(request.url).pathname}`
      const text = await request.clone().text()
      calls.push({ key, body: text ? (JSON.parse(text) as unknown) : undefined })
      if (key === 'GET /items/item-1/channels') return Response.json(held)
      if (key === 'POST /items/item-1/not-online')
        return Response.json({
          item_id: 'item-1',
          status: 'not_listed_online',
          note: 'Selling it on the floor.',
          decided_by_name: 'Demo Staff',
          decided_at: '2026-11-06T15:00:00+00:00',
        })
      throw new Error(`unexpected ${key}`)
    }),
  )
  const onKeptOff = vi.fn()
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} onKeptOff={onKeptOff} />)

  fireEvent.click(await screen.findByRole('button', { name: "Don't list online" }))
  expect(screen.queryByRole('button', { name: 'Write the listing' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  fireEvent.click(screen.getByRole('button', { name: "Don't list online" }))
  fireEvent.change(screen.getByLabelText("Why it isn't going online"), {
    target: { value: 'Selling it on the floor.' },
  })
  fireEvent.click(screen.getByRole('button', { name: "Don't list online" }))

  expect(
    await screen.findByText("It won't be listed online. Your note is in its history."),
  ).toBeInTheDocument()
  expect(onKeptOff).toHaveBeenCalled()
  expect(onChoose).not.toHaveBeenCalled()
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(calls.find((call) => call.key === 'POST /items/item-1/not-online')?.body).toEqual({
    note: 'Selling it on the floor.',
  })
})

test('an item in season is not offered the off-online choice', async () => {
  stubApi(() => Response.json(inSeason))
  render(<ChannelChoice itemId="item-1" onChoose={onChoose} />)
  await screen.findByText(inSeason.reason)
  expect(screen.queryByRole('button', { name: "Don't list online" })).not.toBeInTheDocument()
})
