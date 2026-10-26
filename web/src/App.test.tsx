import { render, screen } from '@testing-library/react'

import App from './App'

afterEach(() => {
  vi.unstubAllGlobals()
})

test('shows the API health reported by /health', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  render(<App />)
  expect(await screen.findByText('ok')).toBeInTheDocument()
})

test('shows the API as unreachable when the request fails', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(<App />)
  expect(await screen.findByText('unreachable')).toBeInTheDocument()
})
