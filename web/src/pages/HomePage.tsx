import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { loadApprovals, loadPickList } from '@/api/approval'
import { loadAttention } from '@/api/attention'
import { signedInName } from '@/auth/accounts'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { PageHeading } from '@/components/site/AuthLayout'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

// A count still loading is undefined, and one the API couldn't give is null, which shows no number.
type Count = number | null | undefined

function useCount(load: (() => Promise<number>) | null): Count {
  const [count, setCount] = useState<Count>(undefined)
  useEffect(() => {
    if (!load) return
    let current = true
    load()
      .then((n) => current && setCount(n))
      .catch(() => current && setCount(null))
    return () => {
      current = false
    }
  }, [load])
  return count
}

const countApprovals = () => loadApprovals().then((queue) => queue.awaiting_approval.length)
const countPickList = () => loadPickList().then((entries) => entries.length)
const countAttention = () => loadAttention().then((attention) => attention.open.length)

// Where people land after signing in: the next thing to do, and how much is waiting on each list.
export function HomePage() {
  usePageTitle('Home')
  const { session, me } = useAuth()
  const isManager = me?.role === 'manager'
  const approvals = useCount(isManager ? countApprovals : null)
  const pickList = useCount(countPickList)
  const attention = useCount(countAttention)
  const name = me?.display_name || signedInName(session?.user.email)

  return (
    <AppLayout>
      <PageHeading>{name ? `Welcome, ${name}` : 'Welcome'}</PageHeading>
      <p className="mb-6 text-muted-foreground">
        Start with a new item, or pick up what's waiting.
      </p>
      <Button asChild size="lg" className="mb-10 max-sm:w-full">
        <Link to="/app/appraise">Appraise an item</Link>
      </Button>
      <h2 className="mb-4 text-xl font-bold">Waiting on you</h2>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {isManager && (
          <CountCard
            to="/app/approvals"
            title="Approvals"
            count={approvals}
            unit={['item to approve', 'items to approve']}
          />
        )}
        <CountCard
          to="/app/pick-list"
          title="Pick list"
          count={pickList}
          unit={['sold item to pick', 'sold items to pick']}
        />
        <CountCard
          to="/app/attention"
          title="Needs attention"
          count={attention}
          unit={['problem to look at', 'problems to look at']}
        />
      </ul>
    </AppLayout>
  )
}

function CountCard({
  to,
  title,
  count,
  unit,
}: {
  to: string
  title: string
  count: Count
  unit: [string, string]
}) {
  let detail = 'Loading...'
  if (count === null) detail = 'Open the list'
  else if (count !== undefined)
    detail = `${count === 0 ? 'No' : count} ${unit[count === 1 ? 0 : 1]}`

  return (
    <li>
      <Link
        to={to}
        className="block h-full rounded-xl bg-card p-5 text-card-foreground no-underline shadow-[0_1px_2px_rgb(0_0_0/0.06),0_4px_12px_rgb(0_0_0/0.05)] ring-1 ring-foreground/10 transition-shadow hover:text-card-foreground hover:no-underline hover:ring-primary"
      >
        <span className="block text-lg font-bold">{title}</span>
        <span className="mt-1 block text-muted-foreground" aria-live="polite">
          {detail}
        </span>
      </Link>
    </li>
  )
}
