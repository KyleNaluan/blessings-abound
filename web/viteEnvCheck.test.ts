import { expect, test } from 'vitest'

import { checkNoServerSecrets } from './viteEnvCheck.ts'

test('a build with the service role key in a VITE_ value stops', () => {
  expect(() =>
    checkNoServerSecrets({ SUPABASE_SERVICE_ROLE_KEY: 'secret', VITE_SUPABASE_ANON_KEY: 'secret' }),
  ).toThrow('VITE_SUPABASE_ANON_KEY')
})

test('a build with a VITE_ variable named for the service role key stops', () => {
  expect(() => checkNoServerSecrets({ VITE_SUPABASE_SERVICE_ROLE_KEY: 'anything' })).toThrow(
    'VITE_SUPABASE_SERVICE_ROLE_KEY',
  )
})

test('a build with only public values goes ahead', () => {
  expect(() =>
    checkNoServerSecrets({
      SUPABASE_SERVICE_ROLE_KEY: 'secret',
      VITE_SUPABASE_ANON_KEY: 'public',
      VITE_API_URL: '',
    }),
  ).not.toThrow()
})
