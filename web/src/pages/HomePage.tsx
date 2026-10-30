import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { api } from '@/api/client'
import { signOut } from '@/auth/actions'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

type ApiState = 'checking' | 'ok' | 'unreachable'

// Where people land after signing in, until the item screens exist.
export function HomePage() {
  usePageTitle('Home')
  const { session } = useAuth()
  const navigate = useNavigate()
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    api
      .GET('/health')
      .then(({ data }) => setApiState(data?.status === 'ok' ? 'ok' : 'unreachable'))
      .catch(() => setApiState('unreachable'))
  }, [])

  async function onSignOut() {
    await signOut()
    navigate('/', { replace: true })
  }

  return (
    <AuthLayout
      end={
        <Button variant="outline" size="lg" onClick={onSignOut}>
          Sign out
        </Button>
      }
    >
      <PageHeading>You're signed in</PageHeading>
      <Lead>
        Signed in as {session?.user.email}. The item screens aren't built yet, so this page only
        checks that the app can reach its API.
      </Lead>
      <p className="flex items-center justify-between border-y border-rule py-3.5">
        <span>API status</span>
        <Badge variant={apiState === 'unreachable' ? 'destructive' : 'secondary'}>{apiState}</Badge>
      </p>
    </AuthLayout>
  )
}
