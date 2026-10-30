import { createContext, useContext } from 'react'
import type { Session } from '@supabase/supabase-js'

export type AuthState = {
  // True until the stored session, or one from a reset link in the URL, has been read.
  loading: boolean
  session: Session | null
}

export const AuthContext = createContext<AuthState>({ loading: true, session: null })

export function useAuth() {
  return useContext(AuthContext)
}
