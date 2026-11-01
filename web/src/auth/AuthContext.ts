import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'

export type AuthState = {
  // True until the stored session, or one from a reset link in the URL, has been read.
  loading: boolean
  session: Session | null
  // True while the sign-out button is ending the session before it leaves the page, so RequireAuth holds its redirect.
  signingOut: boolean
  beginSignOut: () => void
  endSignOut: () => void
}

export const AuthContext = createContext<AuthState>({
  loading: true,
  session: null,
  signingOut: false,
  beginSignOut: () => {},
  endSignOut: () => {},
})

export function useAuth() {
  return useContext(AuthContext)
}
