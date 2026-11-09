import { useCallback, useEffect, useState } from 'react'

import { loadPeople, type Person, type PersonWithTemporaryPassword } from '@/api/team'
import { useAuth } from '@/auth/AuthContext'
import { AppLayout } from '@/components/site/AppLayout'
import { Lead, PageHeading } from '@/components/site/AuthLayout'
import {
  ActionCell,
  Cell,
  DataTable,
  DetailsRow,
  Row,
  TableBody,
  TableSection,
  type Column,
} from '@/components/site/DataTable'
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
            <div
              role="alert"
              className="mb-7 max-w-[36rem] rounded-xl border-4 border-destructive bg-card px-5 py-4"
            >
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

const COLUMNS: Column[] = [
  { label: 'Name' },
  { label: 'Role', width: 'w-[8rem]' },
  { label: 'Status', width: 'w-[11rem]' },
  { label: 'Manage', width: 'w-[8.5rem]', hidden: true },
]

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
  return (
    <TableSection id="people" title="People" count={people.length} unit={['person', 'people']}>
      <DataTable columns={COLUMNS}>
        {people.map((person) => {
          const isMe = person.auth_user_id === meId
          const expanded = open === person.auth_user_id
          const panelId = `person-${person.auth_user_id}`
          return (
            <TableBody key={person.auth_user_id}>
              <Row open={expanded}>
                <Cell>
                  <p className="font-bold break-words">
                    {person.display_name}
                    {isMe && <span className="font-normal text-muted-foreground"> (you)</span>}
                  </p>
                  <p className="text-sm break-all text-muted-foreground">
                    {person.username}
                    <span aria-hidden="true"> · </span>
                    <span className="sr-only">, </span>
                    {person.email ?? 'no email'}
                  </p>
                  {/* Always in the row, so screen readers announce what a change did. */}
                  <div role="status">
                    {notice?.authUserId === person.auth_user_id && (
                      <p className="mt-2 border-l-[5px] border-yes bg-yes-soft px-3 py-2 font-bold">
                        {notice.text}
                      </p>
                    )}
                  </div>
                </Cell>
                <Cell label="Role">
                  <p>{ROLE_NAMES[person.role]}</p>
                </Cell>
                <Cell label="Status">
                  <p className={cn('font-bold', STATUS_CLASSES[person.status])}>
                    {STATUS_NAMES[person.status]}
                  </p>
                </Cell>
                <ActionCell>
                  <Button
                    variant="outline"
                    size="lg"
                    className="wide:w-28"
                    aria-label={`${expanded ? 'Close' : 'Manage'} ${person.display_name}`}
                    aria-expanded={expanded}
                    aria-controls={expanded ? panelId : undefined}
                    onClick={() => onToggle(person.auth_user_id)}
                  >
                    {expanded ? 'Close' : 'Manage'}
                  </Button>
                </ActionCell>
              </Row>
              {expanded && (
                <DetailsRow id={`${panelId}-details`} colSpan={COLUMNS.length}>
                  <PersonPanel
                    id={panelId}
                    person={person}
                    isMe={isMe}
                    lastManager={isLastActiveManager(person, people)}
                    onChanged={onChanged}
                    onIssued={onIssued}
                  />
                </DetailsRow>
              )}
            </TableBody>
          )
        })}
      </DataTable>
    </TableSection>
  )
}
