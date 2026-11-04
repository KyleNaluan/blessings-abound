import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { api } from '@/api/client'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

type ApiState = 'checking' | 'ok' | 'unreachable'

// Where people land after signing in.
// Someone with no email has a hidden address on this domain, see api/app/supabase_auth.py, and only the username means anything.
const PLACEHOLDER_SUFFIX = '@accounts.turnstone.invalid'

function signedInName(email: string | undefined) {
  return email?.endsWith(PLACEHOLDER_SUFFIX) ? email.slice(0, -PLACEHOLDER_SUFFIX.length) : email
}

export function HomePage() {
  usePageTitle('Home')
  const { session, me } = useAuth()
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    api
      .GET('/health')
      .then(({ data }) => setApiState(data?.status === 'ok' ? 'ok' : 'unreachable'))
      .catch(() => setApiState('unreachable'))
  }, [])

  return (
    <AuthLayout end={<SignOutButton />}>
      <PageHeading>You're signed in</PageHeading>
      <Lead>Signed in as {signedInName(session?.user.email)}.</Lead>
      <Button asChild size="lg" className="mb-7 max-sm:w-full">
        <Link to="/app/appraise">Appraise an item</Link>
      </Button>
      {me?.role === 'manager' && (
        <p className="mb-7">
          <Link to="/app/settings">Settings</Link>
        </p>
      )}
      <p className="flex items-center justify-between border-y border-rule py-3.5">
        <span>API status</span>
        <Badge variant={apiState === 'unreachable' ? 'destructive' : 'secondary'}>{apiState}</Badge>
      </p>
    </AuthLayout>
  )
}
