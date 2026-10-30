import { useEffect, useState, type ReactNode } from 'react'

import { AuthContext, type AuthState } from './AuthContext'
import { supabase } from './supabase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ loading: supabase !== null, session: null })

  useEffect(() => {
    if (!supabase) return
    // The first event carries the stored session, or null, so it also ends loading.
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setState({ loading: false, session })
    })
    return () => data.subscription.unsubscribe()
  }, [])

  return <AuthContext value={state}>{children}</AuthContext>
}
