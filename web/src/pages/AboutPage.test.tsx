import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { AboutPage } from './AboutPage'

function renderAbout() {
  render(
    <MemoryRouter>
      <AboutPage />
    </MemoryRouter>,
  )
}

test('tells the whole story: the problem, who decides, the limits and the project', () => {
  renderAbout()
  expect(screen.getByRole('heading', { level: 1, name: 'About Turnstone' })).toBeInTheDocument()
  expect(
    screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
  ).toEqual([
    'Why “Turnstone”?',
    'Why the store needs it',
    'Who decides what',
    "What it can't tell you yet",
    'About this project',
  ])
})

test('says plainly that the shops are mock and the sales history is synthetic', () => {
  renderAbout()
  expect(screen.getByText('The shops are mock')).toBeInTheDocument()
  expect(screen.getByText('Sales history is synthetic')).toBeInTheDocument()
})

test('sets the page title', () => {
  renderAbout()
  expect(document.title).toBe('About - Turnstone')
})
