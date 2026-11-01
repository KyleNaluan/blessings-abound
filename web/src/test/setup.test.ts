import { screen } from '@testing-library/react'

// Blocks the event loop, as the runner freezing this process does.
function freeze(ms: number) {
  const until = performance.now() + ms
  while (performance.now() < until);
}

test('a wait outlasts a freeze that uses up its deadline', async () => {
  const late = document.createElement('p')
  late.textContent = 'arrived'
  // Due after the deadline whatever the load, so the first try always fails, and due at once after the freeze.
  setTimeout(() => document.body.append(late), 150)
  const wait = screen.findByText('arrived', undefined, { timeout: 100 })
  freeze(400)
  expect(await wait).toBe(late)
  late.remove()
})

test('a wait for something that never comes still fails', async () => {
  await expect(screen.findByText('never', undefined, { timeout: 100 })).rejects.toThrow(
    'Unable to find an element with the text: never',
  )
})
