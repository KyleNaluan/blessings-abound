import type { AuthChangeEvent, Session } from '@supabase/supabase-js'

// A stand-in for the Supabase client, so tests drive sign-in without a network.
// Use it with vi.mock('@/auth/supabase', async () => ({ supabase: (await import('@/test/fakeSupabase')).fake.client })).

type Listener = (event: AuthChangeEvent, session: Session | null) => void

const listeners = new Set<Listener>()
let current: Session | null = null

function emit(event: AuthChangeEvent, session: Session | null) {
  current = session
  listeners.forEach((listener) => listener(event, session))
}

const auth = {
  onAuthStateChange: vi.fn((listener: Listener) => {
    listeners.add(listener)
    queueMicrotask(() => listener('INITIAL_SESSION', current))
    return { data: { subscription: { unsubscribe: () => listeners.delete(listener) } } }
  }),
  getSession: vi.fn(async () => ({ data: { session: current }, error: null })),
  signInWithPassword: vi.fn(),
  resetPasswordForEmail: vi.fn(),
  updateUser: vi.fn(),
  signOut: vi.fn(async () => {
    // The real client makes a network call first, so the event never lands inside the click that asked for it.
    await new Promise((resolve) => setTimeout(resolve))
    emit('SIGNED_OUT', null)
    return { error: null }
  }),
}

export const fake = {
  client: { auth },
  auth,
  emit,
  // Starts each test signed out, with every call succeeding unless the test says otherwise.
  reset(session: Session | null = null) {
    current = session
    listeners.clear()
    auth.signInWithPassword.mockReset()
    auth.resetPasswordForEmail.mockReset().mockResolvedValue({ data: {}, error: null })
    auth.updateUser.mockReset()
    auth.signOut.mockClear()
  },
}

export function fakeSession(userMetadata: Record<string, unknown> = {}): Session {
  return {
    access_token: 'access',
    refresh_token: 'refresh',
    expires_in: 3600,
    token_type: 'bearer',
    user: {
      id: 'user-1',
      email: 'demo.staff@example.com',
      aud: 'authenticated',
      created_at: '2026-10-30T00:00:00Z',
      app_metadata: {},
      user_metadata: userMetadata,
    },
  }
}

// What Supabase Auth returns for a failed call, enough for the app to read its code.
export function authError(code: string) {
  return { data: { user: null, session: null }, error: { code, message: code, status: 400 } }
}
