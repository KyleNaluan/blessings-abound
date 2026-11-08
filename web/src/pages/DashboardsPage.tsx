import { useCallback, useEffect, useState } from 'react'

import { loadDashboards, type Dashboards } from '@/api/dashboards'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { PageHeading } from '@/components/site/AuthLayout'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
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

  return (
    <AppLayout>
      <PageHeading>Dashboards</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can see the dashboards.</p>
      ) : (
        <>
          <InsightChat />
          <div aria-live="polite">
            {load.state === 'loading' && (
              <p className="mb-7 font-bold">Loading the dashboards...</p>
            )}
          </div>
          {load.state === 'failed' && (
            <div
              role="alert"
              className="mb-7 max-w-[42rem] rounded-xl border-4 border-destructive bg-card px-5 py-4"
            >
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
          <p className="mt-10 border-t border-rule pt-4 text-[0.8125rem] text-muted-foreground">
            Demo data: past sales are made up by a model based on published figures. Live numbers
            are test sales on two practice channels.
          </p>
        </>
      )}
    </AppLayout>
  )
}
