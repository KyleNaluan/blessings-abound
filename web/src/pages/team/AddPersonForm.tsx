import { useState, type FormEvent } from 'react'

import {
  createWithTemporaryPassword,
  invitePerson,
  type Person,
  type PersonWithTemporaryPassword,
  type Role,
} from '@/api/team'
import {
  ErrorSummary,
  Field,
  RadioGroup,
  SubmitButton,
  TextInput,
  type FieldError,
} from '@/components/site/form'
import { SectionCard } from '@/components/site/SectionCard'
import { Button } from '@/components/ui/button'

type Way = 'invite' | 'temporary'

const WAYS = [
  ['invite', 'Email them an invite'],
  ['temporary', 'Make a username with a temporary password'],
] as const

const ROLES = [
  ['staff', 'Staff'],
  ['manager', 'Manager'],
] as const

const WAY_HINTS: Record<Way, string> = {
  invite: 'They get a link to choose their own password.',
  temporary: "For someone with no email. You'll see the password once, to give to them.",
}

type FieldKey = 'way' | 'display_name' | 'username' | 'email'
type FieldErrors = Partial<Record<FieldKey, string>>

const FIELD_IDS: Record<FieldKey, string> = {
  way: 'add-way',
  display_name: 'add-name',
  username: 'add-username',
  email: 'add-email',
}

export type Added =
  { kind: 'invited'; person: Person } | { kind: 'temporary'; issued: PersonWithTemporaryPassword }

export function AddPersonForm({
  onAdded,
  onCancel,
}: {
  onAdded: (added: Added) => void
  onCancel: () => void
}) {
  const [way, setWay] = useState<Way | null>(null)
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('staff')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [pending, setPending] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending) return
    const next: FieldErrors = {
      way: way ? undefined : 'Choose how they will sign in',
      display_name: name.trim() ? undefined : 'Enter their name',
      username: username.trim() ? undefined : 'Enter a username',
      email: way === 'invite' && !email.trim() ? 'Enter their email address' : undefined,
    }
    setErrors(next)
    setProblem(null)
    if (Object.values(next).some(Boolean)) {
      setFailures(failures + 1)
      return
    }

    setPending(true)
    const body = {
      display_name: name.trim(),
      username: username.trim(),
      email: email.trim() || null,
      role,
    }
    try {
      if (way === 'invite') {
        onAdded({ kind: 'invited', person: await invitePerson({ ...body, email: email.trim() }) })
      } else {
        onAdded({ kind: 'temporary', issued: await createWithTemporaryPassword(body) })
      }
    } catch (error) {
      setProblem((error as Error).message)
      setFailures(failures + 1)
      setPending(false)
    }
  }

  const summary: FieldError[] = [
    ...(Object.keys(FIELD_IDS) as FieldKey[])
      .filter((key) => errors[key])
      .map((key) => ({ fieldId: FIELD_IDS[key], message: errors[key] as string })),
    ...(problem ? [{ fieldId: FIELD_IDS.display_name, message: problem }] : []),
  ]

  return (
    <SectionCard id="add" title="Add a person" className="max-w-[30rem]">
      {summary.length > 0 && <ErrorSummary key={failures} errors={summary} />}
      <form noValidate onSubmit={onSubmit}>
        <RadioGroup
          id={FIELD_IDS.way}
          legend="How will they sign in?"
          hint={way ? WAY_HINTS[way] : undefined}
          error={errors.way}
          options={WAYS}
          value={way}
          disabled={pending}
          onChange={setWay}
        />
        <Field id={FIELD_IDS.display_name} label="Name" error={errors.display_name}>
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              autoComplete="off"
              aria-describedby={describedBy}
              invalid={invalid}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          )}
        </Field>
        <Field
          id={FIELD_IDS.username}
          label="Username"
          hint="What they type to sign in. Lowercase letters and digits, with dots, dashes or underscores between, such as jo.smith."
          error={errors.username}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-describedby={describedBy}
              invalid={invalid}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          )}
        </Field>
        <Field
          id={FIELD_IDS.email}
          label={way === 'invite' ? 'Email' : 'Email (optional)'}
          hint={
            way === 'invite'
              ? undefined
              : 'With an email they can reset a forgotten password themselves.'
          }
          error={errors.email}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              id={id}
              type="email"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              aria-describedby={describedBy}
              invalid={invalid}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          )}
        </Field>
        <RadioGroup
          id="add-role"
          legend="Role"
          hint="Managers also approve listings, change the settings and manage the team."
          options={ROLES}
          value={role}
          disabled={pending}
          onChange={setRole}
        />
        <div className="flex flex-wrap items-center gap-3">
          <SubmitButton pending={pending}>
            {pending
              ? 'Adding'
              : way === 'temporary'
                ? 'Create the username'
                : way === 'invite'
                  ? 'Send the invite'
                  : 'Add them'}
          </SubmitButton>
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="max-sm:w-full"
            disabled={pending}
            onClick={onCancel}
          >
            Cancel
          </Button>
        </div>
      </form>
    </SectionCard>
  )
}
