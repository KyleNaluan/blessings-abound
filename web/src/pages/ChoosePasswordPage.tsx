import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { hasTemporaryPassword } from '@/auth/accounts'
import { choosePassword } from '@/auth/actions'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { ErrorSummary, Field, SubmitButton, TextInput } from '@/components/site/form'
import { usePageTitle } from '@/lib/usePageTitle'

const MIN_LENGTH = 10
// Supabase Auth ignores anything past 72 bytes, so a longer password would be quietly cut short.
const MAX_LENGTH = 72

type FieldErrors = { password?: string; confirm?: string }

// Reached after signing in with a temporary password, or from a reset link in an email.
export function ChoosePasswordPage() {
  usePageTitle('Choose your password')
  const { loading, session } = useAuth()

  if (loading) return <AuthLayout>{null}</AuthLayout>
  if (!session) {
    return (
      <AuthLayout>
        <PageHeading>Choose your password</PageHeading>
        <Lead>
          This reset link has expired or has already been used. Reset links work once, for 1 hour.
        </Lead>
        <p className="mb-4">
          <Link to="/forgot-password">Send a new reset link</Link>
        </p>
        <p>
          <Link to="/sign-in">Sign in</Link>
        </p>
      </AuthLayout>
    )
  }
  return <ChoosePasswordForm temporary={hasTemporaryPassword(session.user)} />
}

function ChoosePasswordForm({ temporary }: { temporary: boolean }) {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [pending, setPending] = useState(false)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmRef = useRef<HTMLInputElement>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const bytes = new TextEncoder().encode(password).length
    const next: FieldErrors = {
      password:
        password.length < MIN_LENGTH
          ? `Your password must be at least ${MIN_LENGTH} characters`
          : bytes > MAX_LENGTH
            ? `Your password must be ${MAX_LENGTH} characters or fewer`
            : undefined,
    }
    next.confirm = !next.password && password !== confirm ? "The passwords don't match" : undefined
    setErrors(next)
    setProblem(null)
    if (next.password) return passwordRef.current?.focus()
    if (next.confirm) return confirmRef.current?.focus()

    setPending(true)
    const error = await choosePassword(password)
    setPending(false)
    if (error) {
      setProblem(error)
      setFailures(failures + 1)
    } else {
      navigate('/app', { replace: true })
    }
  }

  return (
    <AuthLayout>
      {problem && (
        <ErrorSummary key={failures} errors={[{ fieldId: 'new-password', message: problem }]} />
      )}
      <PageHeading>Choose your password</PageHeading>
      <Lead>
        {temporary
          ? 'You signed in with a temporary password. Choose one only you know before you continue.'
          : 'Choose a new password for your account.'}
      </Lead>
      <form noValidate onSubmit={onSubmit}>
        <Field
          id="new-password"
          label="New password"
          hint="Use at least 10 characters. A few words in a row works well."
          error={errors.password}
        >
          {({ id, describedBy, invalid }) => (
            <TextInput
              ref={passwordRef}
              id={id}
              type="password"
              autoComplete="new-password"
              aria-describedby={describedBy}
              invalid={invalid}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <Field id="confirm-password" label="Type it again" error={errors.confirm}>
          {({ id, describedBy, invalid }) => (
            <TextInput
              ref={confirmRef}
              id={id}
              type="password"
              autoComplete="new-password"
              aria-describedby={describedBy}
              invalid={invalid}
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          )}
        </Field>
        <SubmitButton pending={pending}>
          {pending ? 'Saving' : 'Save password and continue'}
        </SubmitButton>
      </form>
    </AuthLayout>
  )
}
