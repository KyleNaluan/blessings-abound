import { useState } from 'react'
import { useNavigate } from 'react-router'

import { signOut } from '@/auth/actions'
import { useAuth } from '@/auth/AuthContext'
import { Button } from '@/components/ui/button'

export function SignOutButton() {
  const navigate = useNavigate()
  const { beginSignOut, endSignOut } = useAuth()
  const [error, setError] = useState<string | null>(null)

  // End the session first, then leave. The mark holds RequireAuth's redirect to sign-in while the session clears, so the
  // router's low priority navigation to the landing page still wins. A failed sign-out stays on the page with the message.
  async function onSignOut() {
    setError(null)
    beginSignOut()
    const message = await signOut()
    if (message) {
      endSignOut()
      setError(message)
      return
    }
    navigate('/', { replace: true })
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <Button variant="outline" size="lg" onClick={() => void onSignOut()}>
        Sign out
      </Button>
      {error && (
        <p role="alert" className="font-bold text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
