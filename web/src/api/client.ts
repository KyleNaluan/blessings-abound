import createClient from 'openapi-fetch'

import { supabase } from '@/auth/supabase'

import type { paths } from './schema'

// Types come from schema.d.ts, which `npm run gen:api` generates from the API's OpenAPI schema.
export const api = createClient<paths>({
  // An empty VITE_API_URL, as copied from .env.example, also falls back to the local API.
  baseUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  // Look fetch up on every call, so tests can stub it after this module loads.
  fetch: (request) => globalThis.fetch(request),
})

// The API works out who is calling from the Supabase Auth token.
api.use({
  async onRequest({ request }) {
    const { data } = (await supabase?.auth.getSession()) ?? {}
    const token = data?.session?.access_token
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
})
