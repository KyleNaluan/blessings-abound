import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'

import { loadDashboards, type Dashboards } from '@/api/dashboards'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { count, onDay } from '@/pages/dashboards/format'
import { InsightChat } from '@/pages/dashboards/InsightChat'
import { FunnelView, SeasonalityView, SyncView, TimeToSellView } from '@/pages/dashboards/views'

type Load =
  { state: 'loading' } | { state: 'failed'; message: string } | { state: 'ready'; data: Dashboards }

// The insight chat and the four sales views for managers, each labeled with where its numbers
// come from.
export function DashboardsPage() {
  usePageTitle('Dashboards')
  const { me } = useAuth()
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchDashboards = useCallback(() => {
    return loadDashboards()
      .then((data) => setLoad({ state: 'ready', data }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    if (!refused) void fetchDashboards()
  }, [refused, fetchDashboards])

  const history = load.state === 'ready' ? load.data.history : null

  return (
    <AuthLayout end={<SignOutButton />} wide>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Dashboards</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can see the dashboards.</p>
      ) : (
        <>
          <div className="mb-8 max-w-[42rem]">
            <p className="mb-3">
              The store has no sales history yet, so time to sell, seasonality and the triage funnel
              are drawn from a synthetic one, and any pattern in them was put there by the model
              that made it. The live numbers come from test sales on the two mock channels, and the
              two are always kept on separate charts.
            </p>
            {history && (
              <p className="text-muted-foreground">
                The synthetic history has {count(history.items, 'item')} forwarded from{' '}
                {onDay(history.first_forwarded_on)} to {onDay(history.last_forwarded_on)}, with{' '}
                {count(history.listings, 'listing')} and {count(history.sales, 'sale')}.
              </p>
            )}
          </div>
          <InsightChat />
          <div aria-live="polite">
            {load.state === 'loading' && (
              <p className="mb-7 font-bold">Loading the dashboards...</p>
            )}
          </div>
          {load.state === 'failed' && (
            <div role="alert" className="mb-7 max-w-[42rem] border-4 border-destructive px-5 py-4">
              <p className="mb-3 font-bold">{load.message}</p>
              <Button
                variant="outline"
                size="lg"
                className="max-sm:w-full"
                onClick={() => {
                  setLoad({ state: 'loading' })
                  void fetchDashboards()
                }}
              >
                Try again
              </Button>
            </div>
          )}
          {load.state === 'ready' && (
            <>
              <TimeToSellView data={load.data} />
              <SeasonalityView data={load.data} />
              <FunnelView data={load.data} />
              <SyncView data={load.data} />
            </>
          )}
        </>
      )}
    </AuthLayout>
  )
}
