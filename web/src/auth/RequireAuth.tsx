import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { hasTemporaryPassword } from './accounts'
import { useAuth } from './AuthContext'

// Lets signed-in people through, sends everyone else to sign in, and sends anyone still on a temporary password to choose
// their own before anything else.
export function RequireAuth({ children }: { children: ReactNode }) {
  const { loading, session } = useAuth()
  const location = useLocation()

  if (loading) return null
  if (!session) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  if (hasTemporaryPassword(session.user)) return <Navigate to="/choose-password" replace />
  return children
}
