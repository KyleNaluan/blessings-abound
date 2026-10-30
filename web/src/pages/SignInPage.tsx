import { useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation } from 'react-router'

import { signIn } from '@/auth/actions'
import { useAuth } from '@/auth/AuthContext'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { ErrorSummary, Field, PasswordInput, SubmitButton, TextInput } from '@/components/site/form'
import { usePageTitle } from '@/lib/usePageTitle'

type FieldErrors = { identifier?: string; password?: string }

export function SignInPage() {
  usePageTitle('Sign in')
  const { session } = useAuth()
  const location = useLocation()
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [pending, setPending] = useState(false)
  const identifierRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  // Signed in, by this form or a stored session, so go where the person was headed.
  // RequireAuth there sends anyone on a temporary password to choose their own first.
  if (session) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/app'} replace />
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next: FieldErrors = {
      identifier: identifier.trim() ? undefined : 'Enter your username or email',
      password: password ? undefined : 'Enter your password',
    }
    setErrors(next)
    setProblem(null)
    if (next.identifier) return identifierRef.current?.focus()
    if (next.password) return passwordRef.current?.focus()

    setPending(true)
    const error = await signIn(identifier.trim(), password)
    setPending(false)
    if (error) {
      setProblem(error)
      setFailures(failures + 1)
      setPassword('')
    }
  }

  return (
    <AuthLayout>
      {problem && (
        <ErrorSummary key={failures} errors={[{ fieldId: 'identifier', message: problem }]} />
      )}
      <PageHeading>Sign in</PageHeading>
      <Lead>
        Use the username a store manager set up for you, or the email address on your account.
      </Lead>
      <form noValidate onSubmit={onSubmit}>
        <Field id="identifier" label="Username or email" error={errors.identifier}>
          {({ id, describedBy, invalid }) => (
            <TextInput
              ref={identifierRef}
              id={id}
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              aria-describedby={describedBy}
              invalid={invalid}
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
            />
          )}
        </Field>
        <Field id="password" label="Password" error={errors.password}>
          {({ id, describedBy, invalid }) => (
            <PasswordInput
              ref={passwordRef}
              id={id}
              name="password"
              autoComplete="current-password"
              aria-describedby={describedBy}
              invalid={invalid}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        <SubmitButton pending={pending}>{pending ? 'Signing in' : 'Sign in'}</SubmitButton>
      </form>
      <details className="mt-8">
        <summary className="inline-block cursor-pointer text-link underline underline-offset-[0.15em] hover:text-primary-hover">
          Problems signing in?
        </summary>
        <div className="mt-2.5 border-l-[5px] border-border pt-3 pb-px pl-4">
          <p className="mb-4">
            If you've forgotten your password, you can{' '}
            <Link to="/forgot-password" state={{ identifier: identifier.trim() }}>
              reset your password
            </Link>
            .
          </p>
          <p className="mb-4">
            Accounts come from a store manager. There's no public sign-up, so ask a manager if you
            need an account.
          </p>
        </div>
      </details>
    </AuthLayout>
  )
}
