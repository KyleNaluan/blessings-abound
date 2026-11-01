import { useNavigate } from 'react-router'

import { signOut } from '@/auth/actions'
import { Button } from '@/components/ui/button'

export function SignOutButton() {
  const navigate = useNavigate()

  async function onSignOut() {
    await signOut()
    navigate('/', { replace: true })
  }

  return (
    <Button variant="outline" size="lg" onClick={onSignOut}>
      Sign out
    </Button>
  )
}
