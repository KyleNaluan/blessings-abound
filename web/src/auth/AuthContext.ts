import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'

import type { Me } from '@/api/accounts'

export type AuthState = {
  // True until the stored session, or one from a reset link in the URL, has been read.
  loading: boolean
  session: Session | null
  // True while the sign-out button is ending the session before it leaves the page, so RequireAuth holds its redirect.
  signingOut: boolean
  beginSignOut: () => void
  endSignOut: () => void
  // Who the API says this is, or null when signed out or the API can't say.
  me: Me | null
  setMe: (me: Me) => void
}

export const AuthContext = createContext<AuthState>({
  loading: true,
  session: null,
  signingOut: false,
  beginSignOut: () => {},
  endSignOut: () => {},
  me: null,
  setMe: () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}
