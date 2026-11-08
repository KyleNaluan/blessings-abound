import { useCallback, useEffect, useState } from 'react'
import { Tabs } from 'radix-ui'

import { loadDashboards, type Dashboards } from '@/api/dashboards'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { PageHeading } from '@/components/site/AuthLayout'
import { pillTab } from '@/components/site/pillTab'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { cn } from '@/lib/utils'
import { Headlines, TILES_OFFSET } from '@/pages/dashboards/Headlines'
import { InsightChat } from '@/pages/dashboards/InsightChat'
import { FunnelView, SeasonalityView, SyncView, TimeToSellView } from '@/pages/dashboards/views'

type Load =
  { state: 'loading' } | { state: 'failed'; message: string } | { state: 'ready'; data: Dashboards }

// The chat's height: shorter below the charts on a narrow screen, taller beside them on a wide one.
const CHAT_HEIGHT = 'h-[32rem] xl:h-[48rem]'

// The four sales views, one tab at a time, each chart labeled with where its numbers come from.
const VIEWS = [
  { value: 'time-to-sell', label: 'Time to sell', View: TimeToSellView },
  { value: 'seasonality', label: 'Seasonality', View: SeasonalityView },
  { value: 'funnel', label: 'Triage funnel', View: FunnelView },
  { value: 'sync', label: 'Sync', View: SyncView },
]

// The dashboards for managers: the headline counts and the views across the screen, with the
// insight chat beside them on a wide screen and below them on a narrow one.
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
    <AppLayout wide>
      <PageHeading>Dashboards</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can see the dashboards.</p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <div className="min-w-0">
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
                  <Headlines data={load.data} />
                  <Tabs.Root defaultValue={VIEWS[0].value}>
                    <Tabs.List aria-label="Dashboard views" className="mb-4 flex flex-wrap gap-2">
                      {VIEWS.map((view) => (
                        <Tabs.Trigger key={view.value} value={view.value} className={pillTab}>
                          {view.label}
                        </Tabs.Trigger>
                      ))}
                    </Tabs.List>
                    {VIEWS.map(({ value, View }) => (
                      <Tabs.Content key={value} value={value}>
                        <View data={load.data} />
                      </Tabs.Content>
                    ))}
                  </Tabs.Root>
                </>
              )}
            </div>
            {/* The chat keeps one height, whatever the open view or the size of the data, and its
                conversation scrolls inside it. Beside the charts it starts level with the tiles. */}
            <InsightChat className={cn(CHAT_HEIGHT, load.state === 'ready' && TILES_OFFSET)} />
          </div>
          <p className="mt-6 border-t border-rule pt-4 text-[0.8125rem] text-muted-foreground">
            Demo data: past sales are made up by a model based on published figures. Live numbers
            are test sales on two practice channels.
          </p>
        </>
      )}
    </AppLayout>
  )
}
