import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

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

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const file = path.join(directory, name)
    return statSync(file).isDirectory() ? sourceFiles(file) : [file]
  })
}

test('no web code reads the service role key or calls Supabase sign-up', () => {
  for (const file of sourceFiles(path.resolve(import.meta.dirname, 'src'))) {
    const text = readFileSync(file, 'utf8')
    expect(text, file).not.toMatch(/SERVICE_ROLE/i)
    expect(text, file).not.toMatch(/auth\.signUp\b/)
  }
})
