import { useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'

import {
  changeRole,
  deactivatePerson,
  issueTemporaryPassword,
  reactivatePerson,
  type Person,
  type PersonWithTemporaryPassword,
  type Role,
} from '@/api/team'
import { RadioGroup, SubmitButton } from '@/components/site/form'
import { Button } from '@/components/ui/button'

import { ROLE_NAMES } from './format'

const ROLES = [
  ['staff', 'Staff'],
  ['manager', 'Manager'],
] as const

type Busy = 'role' | 'password' | 'deactivate' | 'reactivate' | null
type Confirming = 'password' | 'deactivate' | null

// Takes focus when it appears, and again on each failure, so a screen reader hears why it didn't work.
function Problem({ message, attempt }: { message: string; attempt: number }) {
  const ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    ref.current?.focus()
  }, [attempt])

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      className="mb-5 rounded-xl border-4 border-destructive bg-card px-5 py-4 font-bold focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid"
    >
      {message}
    </div>
  )
}

// One thing a manager can do, under its own heading. The role form's legend is its heading instead.
function Part({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="border-t border-rule pt-4 pb-5 first:border-t-0 first:pt-0">
      {title && <h3 className="mb-1 text-lg font-bold">{title}</h3>}
      {children}
    </div>
  )
}

function Confirm({
  question,
  yes,
  busy,
  onYes,
  onNo,
}: {
  question: string
  yes: string
  busy: boolean
  onYes: () => void
  onNo: () => void
}) {
  const ref = useRef<HTMLParagraphElement>(null)

  useLayoutEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <div className="border-l-[5px] border-destructive py-1 pl-4">
      <p ref={ref} tabIndex={-1} className="mb-3 font-bold focus:outline-none">
        {question}
      </p>
      <div className="flex flex-wrap gap-3">
        <Button
          size="lg"
          className="max-sm:w-full"
          disabled={busy}
          aria-busy={busy}
          onClick={onYes}
        >
          {yes}
        </Button>
        <Button
          variant="outline"
          size="lg"
          className="max-sm:w-full"
          disabled={busy}
          onClick={onNo}
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}

// What a manager can do to one person, shown under their row. The API refuses the same things this hides, and its reasons
// show here when it does.
export function PersonPanel({
  id,
  person,
  isMe,
  lastManager,
  onChanged,
  onIssued,
}: {
  id: string
  person: Person
  isMe: boolean
  lastManager: boolean
  onChanged: (person: Person, done: string) => void
  onIssued: (issued: PersonWithTemporaryPassword) => void
}) {
  const [role, setRole] = useState<Role>(person.role)
  const [busy, setBusy] = useState<Busy>(null)
  const [confirming, setConfirming] = useState<Confirming>(null)
  const [problem, setProblem] = useState<{ message: string; attempt: number } | null>(null)
  const [roleError, setRoleError] = useState<string>()
  const name = person.display_name
  const deactivated = person.status === 'deactivated'

  async function run<T>(
    what: Exclude<Busy, null>,
    call: () => Promise<T>,
    then: (result: T) => void,
  ) {
    setBusy(what)
    setProblem(null)
    try {
      const result = await call()
      setConfirming(null)
      then(result)
    } catch (error) {
      setProblem({ message: (error as Error).message, attempt: (problem?.attempt ?? 0) + 1 })
    } finally {
      setBusy(null)
    }
  }

  function onRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    if (role === person.role) {
      setRoleError(`${name} is already ${ROLE_NAMES[role].toLowerCase()}. Choose the other role.`)
      return
    }
    setRoleError(undefined)
    void run(
      'role',
      () => changeRole(person.auth_user_id, role),
      (changed) => onChanged(changed, `${name} is now ${ROLE_NAMES[changed.role].toLowerCase()}.`),
    )
  }

  return (
    <div id={id} className="mt-4 border-l-[5px] border-border py-1 pl-4">
      {problem && <Problem message={problem.message} attempt={problem.attempt} />}
      {deactivated ? (
        <Part title="Deactivated">
          <p className="mb-4">
            {name} can't sign in. Everything they did stays on record. Reactivate them to let them
            sign in again with their old password.
          </p>
          <Button
            size="lg"
            className="max-sm:w-full"
            disabled={busy !== null}
            aria-busy={busy === 'reactivate'}
            onClick={() =>
              void run(
                'reactivate',
                () => reactivatePerson(person.auth_user_id),
                (changed) => onChanged(changed, `${name} can sign in again.`),
              )
            }
          >
            {busy === 'reactivate' ? 'Reactivating' : `Reactivate ${name}`}
          </Button>
        </Part>
      ) : (
        <>
          <Part title={lastManager ? 'Role' : undefined}>
            {lastManager ? (
              <p>
                {isMe ? "You're" : `${name} is`} the last active manager, so this account stays a
                manager. Make someone else a manager first.
              </p>
            ) : (
              <form noValidate onSubmit={onRole}>
                <RadioGroup
                  id={`${id}-role`}
                  legend="Role"
                  legendClassName="text-lg"
                  hint="Managers also approve listings, change the settings and manage the team."
                  error={roleError}
                  options={ROLES}
                  value={role}
                  disabled={busy !== null}
                  onChange={(next) => {
                    setRole(next)
                    setRoleError(undefined)
                  }}
                />
                <SubmitButton pending={busy === 'role'}>
                  {busy === 'role' ? 'Saving' : 'Save the role'}
                </SubmitButton>
              </form>
            )}
          </Part>
          {!isMe && (
            <Part title="Temporary password">
              <p className="mb-4">
                For when {name} can't get in. It replaces their password now, and they choose their
                own the next time they sign in.
              </p>
              {confirming === 'password' ? (
                <Confirm
                  question={`Replace ${name}'s password with a new temporary one?`}
                  yes={busy === 'password' ? 'Replacing' : 'Yes, replace it'}
                  busy={busy === 'password'}
                  onYes={() =>
                    void run(
                      'password',
                      () => issueTemporaryPassword(person.auth_user_id),
                      onIssued,
                    )
                  }
                  onNo={() => setConfirming(null)}
                />
              ) : (
                <Button
                  variant="outline"
                  size="lg"
                  className="max-sm:w-full"
                  disabled={busy !== null}
                  onClick={() => setConfirming('password')}
                >
                  Give a new temporary password
                </Button>
              )}
            </Part>
          )}
          <Part title="Deactivate">
            {isMe ? (
              <p>You can't deactivate yourself. Another manager can do it for you.</p>
            ) : lastManager ? (
              <p>
                {name} is the last active manager, so they can't be deactivated. Make someone else a
                manager first.
              </p>
            ) : (
              <>
                <p className="mb-4">
                  Stops {name} signing in. Everything they did stays on record, and you can
                  reactivate them later.
                </p>
                {confirming === 'deactivate' ? (
                  <Confirm
                    question={`Deactivate ${name}? They won't be able to sign in.`}
                    yes={busy === 'deactivate' ? 'Deactivating' : 'Yes, deactivate'}
                    busy={busy === 'deactivate'}
                    onYes={() =>
                      void run(
                        'deactivate',
                        () => deactivatePerson(person.auth_user_id),
                        (changed) => onChanged(changed, `${name} is deactivated.`),
                      )
                    }
                    onNo={() => setConfirming(null)}
                  />
                ) : (
                  <Button
                    variant="outline"
                    size="lg"
                    className="max-sm:w-full"
                    disabled={busy !== null}
                    onClick={() => setConfirming('deactivate')}
                  >
                    Deactivate {name}
                  </Button>
                )}
              </>
            )}
          </Part>
        </>
      )}
    </div>
  )
}
