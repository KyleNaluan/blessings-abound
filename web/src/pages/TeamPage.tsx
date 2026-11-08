import { useCallback, useEffect, useState } from 'react'

import { loadPeople, type Person, type PersonWithTemporaryPassword } from '@/api/team'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { Lead, PageHeading } from '@/components/site/AuthLayout'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'
import { cn } from '@/lib/utils'
import { AddPersonForm, type Added } from '@/pages/team/AddPersonForm'
import {
  ROLE_NAMES,
  STATUS_CLASSES,
  STATUS_NAMES,
  byUsername,
  isLastActiveManager,
} from '@/pages/team/format'
import { PersonPanel } from '@/pages/team/PersonPanel'
import { TemporaryPassword } from '@/pages/team/TemporaryPassword'

type Load =
  { state: 'loading' } | { state: 'failed'; message: string } | { state: 'ready'; people: Person[] }

// The people who can sign in, for managers to add, change and turn off. Staff are refused here, and by the API as well.
export function TeamPage() {
  usePageTitle('Team')
  const { me } = useAuth()
  // When the API couldn't say who this is, its own refusal speaks instead.
  const refused = me !== null && me.role !== 'manager'
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [issued, setIssued] = useState<PersonWithTemporaryPassword | null>(null)
  // What the last change did, said once beside the person it was about.
  const [notice, setNotice] = useState<{ authUserId: string; text: string } | null>(null)

  // Sets state only once the API answers, so the effect doesn't render twice.
  const fetchPeople = useCallback(() => {
    return loadPeople()
      .then((people) => setLoad({ state: 'ready', people }))
      .catch((error: Error) => setLoad({ state: 'failed', message: error.message }))
  }, [])

  useEffect(() => {
    if (!refused) void fetchPeople()
  }, [refused, fetchPeople])

  function put(person: Person) {
    setLoad((current) => {
      if (current.state !== 'ready') return current
      const others = current.people.filter((other) => other.auth_user_id !== person.auth_user_id)
      return { state: 'ready', people: [...others, person].sort(byUsername) }
    })
  }

  function onAdded(added: Added) {
    setAdding(false)
    if (added.kind === 'invited') {
      put(added.person)
      setNotice({
        authUserId: added.person.auth_user_id,
        text: `We've emailed an invite to ${added.person.email}. ${added.person.display_name} shows as invited until they choose a password.`,
      })
    } else {
      put(added.issued.person)
      setNotice(null)
      setIssued(added.issued)
    }
  }

  function onIssued(result: PersonWithTemporaryPassword) {
    put(result.person)
    setNotice(null)
    setIssued(result)
  }

  return (
    <AppLayout>
      <PageHeading>Team</PageHeading>
      {refused ? (
        <p className="mb-7">Only a manager can see and change the team.</p>
      ) : (
        <>
          <Lead>
            Everyone who can sign in to Turnstone. Add people, change what they can do, give a new
            temporary password, or deactivate an account when someone leaves.
          </Lead>
          {issued && <TemporaryPassword issued={issued} onDone={() => setIssued(null)} />}
          <div aria-live="polite">
            {load.state === 'loading' && <p className="mb-7 font-bold">Loading the team...</p>}
          </div>
          {load.state === 'failed' && (
            <div role="alert" className="mb-7 max-w-[36rem] border-4 border-destructive px-5 py-4">
              <p className="mb-3 font-bold">{load.message}</p>
              <Button
                variant="outline"
                size="lg"
                className="max-sm:w-full"
                onClick={() => {
                  setLoad({ state: 'loading' })
                  void fetchPeople()
                }}
              >
                Try again
              </Button>
            </div>
          )}
          {load.state === 'ready' && (
            <>
              {adding ? (
                <AddPersonForm onAdded={onAdded} onCancel={() => setAdding(false)} />
              ) : (
                <Button
                  size="lg"
                  className="mb-9 max-sm:w-full"
                  onClick={() => {
                    setAdding(true)
                    setNotice(null)
                  }}
                >
                  Add a person
                </Button>
              )}
              <People
                people={load.people}
                meId={me?.auth_user_id ?? null}
                open={open}
                notice={notice}
                onToggle={(authUserId) => {
                  setOpen(open === authUserId ? null : authUserId)
                  setNotice(null)
                }}
                onChanged={(person, text) => {
                  put(person)
                  setNotice({ authUserId: person.auth_user_id, text })
                }}
                onIssued={onIssued}
              />
            </>
          )}
        </>
      )}
    </AppLayout>
  )
}

function People({
  people,
  meId,
  open,
  notice,
  onToggle,
  onChanged,
  onIssued,
}: {
  people: Person[]
  meId: string | null
  open: string | null
  notice: { authUserId: string; text: string } | null
  onToggle: (authUserId: string) => void
  onChanged: (person: Person, text: string) => void
  onIssued: (issued: PersonWithTemporaryPassword) => void
}) {
  const columns = 'wide:grid wide:grid-cols-[minmax(0,1fr)_8rem_11rem_8.5rem] wide:gap-x-6'

  return (
    <section aria-labelledby="people-heading">
      <h2 id="people-heading" className="mb-3 text-xl font-bold">
        People ({people.length})
      </h2>
      {/* Column names for a wide screen. Each row says the same in its own words, so this is hidden from screen readers. */}
      <div
        aria-hidden="true"
        className={cn(
          'hidden border-b-2 border-foreground pb-2 text-sm font-bold text-muted-foreground',
          columns,
        )}
      >
        <span>Name</span>
        <span>Role</span>
        <span>Status</span>
        <span />
      </div>
      <ul className="border-t border-rule wide:border-t-0">
        {people.map((person) => {
          const isMe = person.auth_user_id === meId
          const expanded = open === person.auth_user_id
          const panelId = `person-${person.auth_user_id}`
          return (
            <li key={person.auth_user_id} className="border-b border-rule py-4">
              <div className={cn('wide:items-start', columns)}>
                <div className="mb-1 min-w-0 wide:mb-0">
                  <p className="font-bold break-words">
                    {person.display_name}
                    {isMe && <span className="font-normal text-muted-foreground"> (you)</span>}
                  </p>
                  <p className="break-all text-muted-foreground">
                    {person.username}
                    <span aria-hidden="true"> · </span>
                    <span className="sr-only">, </span>
                    {person.email ?? 'no email'}
                  </p>
                </div>
                <p className="inline wide:block">
                  <span className="sr-only">Role: </span>
                  {ROLE_NAMES[person.role]}
                </p>
                <span aria-hidden="true" className="wide:hidden">
                  {' · '}
                </span>
                <p className={cn('inline font-bold wide:block', STATUS_CLASSES[person.status])}>
                  <span className="sr-only">Status: </span>
                  {STATUS_NAMES[person.status]}
                </p>
                <div className="mt-3 wide:mt-0 wide:text-right">
                  <Button
                    variant="outline"
                    size="lg"
                    className="max-sm:w-full wide:w-28"
                    aria-label={`${expanded ? 'Close' : 'Manage'} ${person.display_name}`}
                    aria-expanded={expanded}
                    aria-controls={expanded ? panelId : undefined}
                    onClick={() => onToggle(person.auth_user_id)}
                  >
                    {expanded ? 'Close' : 'Manage'}
                  </Button>
                </div>
              </div>
              <div role="status">
                {notice?.authUserId === person.auth_user_id && (
                  <p className="mt-3 border-l-[5px] border-yes bg-yes-soft px-4 py-2.5 font-bold wide:max-w-[36rem]">
                    {notice.text}
                  </p>
                )}
              </div>
              {expanded && (
                <div className="wide:max-w-[36rem]">
                  <PersonPanel
                    id={panelId}
                    person={person}
                    isMe={isMe}
                    lastManager={isLastActiveManager(person, people)}
                    onChanged={onChanged}
                    onIssued={onIssued}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
