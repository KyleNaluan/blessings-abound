import { useEffect, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { mustChoosePassword } from './accounts'
import { useAuth } from './AuthContext'

// Lets signed-in people through, sends everyone else to sign in, and sends anyone on a temporary password or a new invite to
// choose their own before anything else.
export function RequireAuth({ children }: { children: ReactNode }) {
  const { loading, session, me, signingOut, endSignOut } = useAuth()
  const location = useLocation()

  // Clear the sign-out mark once this protected page is gone, so a later visit while signed out still redirects.
  useEffect(() => endSignOut, [endSignOut])

  if (loading) return null
  if (!session) {
    if (signingOut) return null
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }
  if (mustChoosePassword(me)) return <Navigate to="/choose-password" replace />
  return children
}
