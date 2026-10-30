import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { LandingPage } from './LandingPage'

function renderLanding() {
  render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  )
}

test('sign in is the only call to action, with no sign-up', () => {
  renderLanding()
  const signIns = screen.getAllByRole('link', { name: /sign in/i })
  expect(signIns.length).toBeGreaterThan(0)
  signIns.forEach((link) => expect(link).toHaveAttribute('href', '/sign-in'))
  expect(screen.queryByRole('link', { name: /sign up|register|create an account/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /sign up|register/i })).toBeNull()
})

test('sets the page title', () => {
  renderLanding()
  expect(document.title).toBe('Turnstone')
})

test('the menu button opens the menu, and Escape closes it', () => {
  renderLanding()
  const menu = screen.getByRole('button', { name: 'Menu' })
  const nav = screen.getByRole('navigation', { name: 'Main' })
  expect(menu).toHaveAttribute('aria-expanded', 'false')
  expect(nav).toHaveClass('hidden')

  fireEvent.click(menu)
  expect(menu).toHaveAttribute('aria-expanded', 'true')
  expect(nav).toHaveClass('block')

  fireEvent.keyDown(document, { key: 'Escape' })
  expect(menu).toHaveAttribute('aria-expanded', 'false')
  expect(menu).toHaveFocus()
})

test('choosing a link in the menu closes it', () => {
  renderLanding()
  const menu = screen.getByRole('button', { name: 'Menu' })
  fireEvent.click(menu)
  fireEvent.click(
    within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Limits' }),
  )
  expect(menu).toHaveAttribute('aria-expanded', 'false')
})

test('the walkthrough tabs show one step at a time', () => {
  renderLanding()
  const tabs = within(screen.getByRole('tablist', { name: 'Steps for one item' })).getAllByRole(
    'tab',
  )
  expect(tabs).toHaveLength(7)
  expect(screen.getByRole('heading', { name: 'Log it and give it a SKU' })).toBeInTheDocument()

  fireEvent.mouseDown(screen.getByRole('tab', { name: '3. Price' }), { button: 0 })
  expect(screen.getByRole('heading', { name: 'Price it and decide' })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Log it and give it a SKU' })).toBeNull()
})

test('the sales views are labeled as synthetic data', () => {
  renderLanding()
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'Sales views' }), { button: 0 })
  const panel = screen.getByRole('tabpanel')
  expect(within(panel).getByText('Synthetic data')).toBeInTheDocument()
  expect(within(panel).getByText(/simulated for the demo/)).toBeInTheDocument()
})
