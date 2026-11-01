import { useCallback, useEffect, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'

import { fetchMe, type Me } from '@/api/accounts'

import { AuthContext } from './AuthContext'
import { supabase } from './supabase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<{ loading: boolean; session: Session | null }>({
    loading: supabase !== null,
    session: null,
  })
  const [loaded, setLoaded] = useState<{ userId: string; me: Me | null } | null>(null)
  const [signingOut, setSigningOut] = useState(false)
  const userId = auth.session?.user.id

  useEffect(() => {
    if (!supabase) return
    // The first event carries the stored session, or null, so it also ends loading.
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      setAuth({ loading: false, session })
    })
    return () => data.subscription.unsubscribe()
  }, [])

  // In an effect and not in the listener above, because a Supabase call made inside that listener
  // waits forever on the lock the listener is holding.
  useEffect(() => {
    if (!userId) return
    let current = true
    void fetchMe().then((me) => {
      if (current) setLoaded({ userId, me })
    })
    return () => {
      current = false
    }
  }, [userId])

  const setMe = useCallback((me: Me) => {
    setLoaded({ userId: me.auth_user_id, me })
  }, [])

  const beginSignOut = useCallback(() => setSigningOut(true), [])
  const endSignOut = useCallback(() => setSigningOut(false), [])

  const known = userId !== undefined && loaded?.userId === userId
  return (
    <AuthContext
      value={{
        loading: auth.loading || (userId !== undefined && !known),
        session: auth.session,
        signingOut,
        beginSignOut,
        endSignOut,
        me: known ? (loaded?.me ?? null) : null,
        setMe,
      }}
    >
      {children}
    </AuthContext>
  )
}
