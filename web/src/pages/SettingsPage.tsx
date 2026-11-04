import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'

import { loadSettings, type SectionKey, type SettingsPage as Settings } from '@/api/settings'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { SignOutButton } from '@/components/site/SignOutButton'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import {
  AskToSaleSection,
  BoxSizesSection,
  FeesSection,
  SeasonalCalendarSection,
  ShippingWeightSection,
  WorthListingSection,
} from '@/pages/settings/sections'

type Load =
  | { state: 'loading' }
  | { state: 'failed'; message: string }
  | { state: 'ready'; settings: Settings }

// The values a manager can change without a code change. Staff are refused here, and by the API as well.
export function SettingsPage() {
  usePageTitle('Settings')
  const { me } = useAuth()
  // When the API couldn't say who this is, its own refusal speaks instead.
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [saved, setSaved] = useState<SectionKey | null>(null)
  // A reload remounts every section, so each form starts again from what the API holds now.
  const [loads, setLoads] = useState(0)

  const fetchSettings = useCallback(
    () =>
      loadSettings()
        .then((settings) => {
          setLoad({ state: 'ready', settings })
          setLoads((count) => count + 1)
        })
        .catch((error: Error) => setLoad({ state: 'failed', message: error.message })),
    [],
  )

  useEffect(() => {
    if (!refused) void fetchSettings()
  }, [refused, fetchSettings])

  function reload() {
    setLoad({ state: 'loading' })
    setSaved(null)
    void fetchSettings()
  }

  function onSaved(key: SectionKey) {
    return (settings: Settings) => {
      setLoad({ state: 'ready', settings })
      setSaved(key)
    }
  }

  // The save time changes on every save, so the saved section starts again from the API's copy, such as words in lowercase.
  const keyOf = (key: SectionKey, settings: Settings) =>
    `${key}-${loads}-${settings[key].updated_at ?? 'start'}`

  function section<K extends SectionKey>(key: K, settings: Settings) {
    return {
      read: settings[key],
      saved: saved === key,
      onSaved: onSaved(key),
      onReload: reload,
    }
  }

  return (
    <AuthLayout end={<SignOutButton />}>
      <p className="mb-4">
        <Link to="/app">Back to home</Link>
      </p>
      <PageHeading>Settings</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can see and change the settings.</p>
      ) : (
        <>
          <Lead>
            The values the price, the worth-listing rule and the shipping checks use. Each section
            is saved on its own.
          </Lead>
          <div aria-live="polite">
            {load.state === 'loading' && <p className="mb-7 font-bold">Loading the settings...</p>}
          </div>
          {load.state === 'failed' && (
            <div role="alert" className="mb-7 border-4 border-destructive px-5 py-4">
              <p className="mb-3 font-bold">{load.message}</p>
              <Button variant="outline" size="lg" className="max-sm:w-full" onClick={reload}>
                Try again
              </Button>
            </div>
          )}
          {load.state === 'ready' && (
            <>
              <WorthListingSection
                key={keyOf('worth_listing', load.settings)}
                {...section('worth_listing', load.settings)}
              />
              <FeesSection key={keyOf('fees', load.settings)} {...section('fees', load.settings)} />
              <AskToSaleSection
                key={keyOf('ask_to_sale', load.settings)}
                {...section('ask_to_sale', load.settings)}
              />
              <SeasonalCalendarSection
                key={keyOf('seasonal_calendar', load.settings)}
                {...section('seasonal_calendar', load.settings)}
              />
              <BoxSizesSection
                key={keyOf('box_sizes', load.settings)}
                {...section('box_sizes', load.settings)}
              />
              <ShippingWeightSection
                key={keyOf('shipping_weight', load.settings)}
                {...section('shipping_weight', load.settings)}
              />
            </>
          )}
        </>
      )}
    </AuthLayout>
  )
}
