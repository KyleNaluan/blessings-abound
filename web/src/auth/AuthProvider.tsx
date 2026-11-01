import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'

import { AuthContext } from './AuthContext'
import { supabase } from './supabase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ loading: boolean; session: Session | null }>({
    loading: supabase !== null,
    session: null,
  })
  const [signingOut, setSigningOut] = useState(false)

  useEffect(() => {
    if (!supabase) return
    // The first event carries the stored session, or null, so it also ends loading.
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setState({ loading: false, session })
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const beginSignOut = useCallback(() => setSigningOut(true), [])
  const endSignOut = useCallback(() => setSigningOut(false), [])

  return (
    <AuthContext value={{ ...state, signingOut, beginSignOut, endSignOut }}>{children}</AuthContext>
  )
}
