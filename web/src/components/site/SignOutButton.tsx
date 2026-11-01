import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router'

import { signOut } from '@/auth/actions'
import { Button } from '@/components/ui/button'

export function SignOutButton() {
  const navigate = useNavigate()
  const leaving = useRef(false)

  // The session ends only once this page is gone. The router applies a navigation as a low priority transition, so ending
  // it first would let RequireAuth, still on this page, redirect to sign-in after the navigation to the landing page.
  useEffect(
    () => () => {
      if (leaving.current) void signOut()
    },
    [],
  )

  function onSignOut() {
    leaving.current = true
    navigate('/', { replace: true })
  }

  return (
    <Button variant="outline" size="lg" onClick={onSignOut}>
      Sign out
    </Button>
  )
}
