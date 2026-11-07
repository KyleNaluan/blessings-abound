import { useCallback, useEffect, useRef, useState } from 'react'

import { getChannelRecommendation, type Channel, type ChannelRecommendation } from '@/api/appraisal'
import { Button } from '@/components/ui/button'

import { CHANNEL_NAMES, releaseMonth } from './approval/format'
import { NotOnlineForm } from './approval/NotOnlineForm'

// Where the reason came from, so staff know the rules decided the advice either way.
function reasonNote(recommendation: ChannelRecommendation) {
  if (recommendation.reason_source === 'model')
    return 'The model worded this reason from the rules.'
  if (recommendation.reason_fallback === 'flagged')
    return "The model's wording named something the rules don't, so this is the fixed wording."
  if (recommendation.reason_fallback === 'model_failed')
    return "The model couldn't word the reason, so this is the fixed wording."
  return 'No model is set up here, so this is the fixed wording.'
}

const names = (channels: Channel[]) =>
  channels.map((channel) => CHANNEL_NAMES[channel]).join(' and ')

type Status =
  | { step: 'loading' }
  | { step: 'failed'; message: string }
  | { step: 'ready'; recommendation: ChannelRecommendation }

// The channels that can take the item and when to list it, which staff check before the listing is written.
export function ChannelChoice({
  itemId,
  onChoose,
  onKeptOff,
}: {
  itemId: string
  onChoose: (channels: Channel[]) => void
  onKeptOff?: () => void
}) {
  const [status, setStatus] = useState<Status>({ step: 'loading' })
  const [picked, setPicked] = useState<Channel[]>([])
  const [chosen, setChosen] = useState<Channel[] | null>(null)
  // Where the timing says to hold it, staff can keep it off online selling instead.
  const [offline, setOffline] = useState<'no' | 'choosing' | 'done'>('no')
  const started = useRef(false)

  const load = useCallback(() => {
    setStatus({ step: 'loading' })
    getChannelRecommendation(itemId)
      .then((recommendation) => {
        setPicked(recommendation.channels.filter((row) => row.takes).map((row) => row.channel))
        setStatus({ step: 'ready', recommendation })
      })
      .catch((error: Error) => setStatus({ step: 'failed', message: error.message }))
  }, [itemId])

  useEffect(() => {
    // The reason can take a few seconds, so ask once even when React runs this effect twice.
    if (started.current) return
    started.current = true
    load()
  }, [load])

  function toggle(channel: Channel) {
    setPicked((current) =>
      current.includes(channel) ? current.filter((row) => row !== channel) : [...current, channel],
    )
  }

  function choose() {
    if (status.step !== 'ready' || picked.length === 0) return
    // Channel order, whatever order staff ticked them in.
    const channels = status.recommendation.channels
      .map((row) => row.channel)
      .filter((channel) => picked.includes(channel))
    setChosen(channels)
    onChoose(channels)
  }

  const recommendation = status.step === 'ready' ? status.recommendation : null
  const timing = recommendation?.timing

  return (
    <section aria-labelledby="channels-heading" className="mb-7 border border-rule p-4">
      <h2 id="channels-heading" className="mb-3 text-xl font-bold">
        Where and when to list it
      </h2>
      <div aria-live="polite">
        {status.step === 'loading' && <p className="font-bold">Checking the channels...</p>}
      </div>
      {status.step === 'failed' && (
        <div role="alert" className="border-4 border-destructive px-5 py-4">
          <p className="mb-3 font-bold">{status.message}</p>
          <Button variant="outline" size="lg" onClick={load}>
            Try again
          </Button>
        </div>
      )}
      {recommendation && timing && (
        <>
          <p className="mb-1 min-w-0 break-words">{recommendation.reason}</p>
          <p className="mb-4 text-muted-foreground">{reasonNote(recommendation)}</p>
          <dl className="mb-4 grid grid-cols-[8rem_1fr] gap-x-4 gap-y-1">
            <dt className="font-bold">Timing</dt>
            <dd>
              {timing.release_month
                ? `Hold until ${releaseMonth(timing.release_month)}`
                : 'List now'}
            </dd>
            <dt className="font-bold">Season</dt>
            <dd className="min-w-0 break-words">
              {timing.season ? `${timing.season}, ${timing.season_span}` : 'None'}
            </dd>
          </dl>
          {timing.release_month && offline !== 'done' && (
            <p className="mb-4">
              Once a manager approves it, it's held for its season, with{' '}
              {releaseMonth(timing.release_month)} as its release month.
            </p>
          )}
          {offline === 'done' ? (
            <p role="status" className="font-bold">
              It won't be listed online. Your note is in its history.
            </p>
          ) : offline === 'choosing' ? (
            <div className="border-l-4 border-rule pl-3.5">
              <h3 className="mb-1 text-lg font-bold">Don't list online</h3>
              <p className="mb-3">
                It comes off online selling, such as to sell it on the store floor, until a manager
                puts it back for review.
              </p>
              <NotOnlineForm
                itemId={itemId}
                idPrefix="channels-not-online"
                onDone={() => {
                  setOffline('done')
                  onKeptOff?.()
                }}
                onCancel={() => setOffline('no')}
              />
            </div>
          ) : chosen ? (
            <p className="font-bold">Listing on {names(chosen)}.</p>
          ) : (
            <>
              <fieldset className="mb-4">
                <legend className="mb-1.5 font-bold">Channels to list on</legend>
                {recommendation.channels.map((row) => (
                  <div key={row.channel} className="mb-1">
                    <label
                      className={`flex min-h-11 items-center gap-2 ${row.takes ? 'cursor-pointer' : 'text-muted-foreground'}`}
                    >
                      <input
                        type="checkbox"
                        className="size-5 accent-primary"
                        checked={picked.includes(row.channel)}
                        disabled={!row.takes}
                        aria-describedby={row.why_not ? `why-not-${row.channel}` : undefined}
                        onChange={() => toggle(row.channel)}
                      />
                      {CHANNEL_NAMES[row.channel]}
                    </label>
                    {row.why_not && (
                      <p
                        id={`why-not-${row.channel}`}
                        className="pl-7 text-sm text-muted-foreground"
                      >
                        {row.why_not}
                      </p>
                    )}
                  </div>
                ))}
              </fieldset>
              {picked.length === 0 && <p className="mb-3">Choose at least one channel.</p>}
              <div className="flex gap-3 max-sm:flex-col">
                <Button
                  size="lg"
                  className="max-sm:w-full"
                  disabled={picked.length === 0}
                  onClick={choose}
                >
                  Write the listing
                </Button>
                {timing.release_month && (
                  <Button
                    variant="outline"
                    size="lg"
                    className="max-sm:w-full"
                    onClick={() => setOffline('choosing')}
                  >
                    Don't list online
                  </Button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}
