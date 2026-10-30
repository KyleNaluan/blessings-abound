import { useRef, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'

import { sendPasswordReset } from '@/auth/actions'
import { AuthLayout, Lead, PageHeading } from '@/components/site/AuthLayout'
import { ErrorSummary, Field, SubmitButton, TextInput } from '@/components/site/form'
import { usePageTitle } from '@/lib/usePageTitle'

export function ForgotPasswordPage() {
  usePageTitle('Reset your password')
  const location = useLocation()
  // Carries over whatever was typed on the sign-in page.
  const typed = (location.state as { identifier?: string } | null)?.identifier ?? ''
  const [identifier, setIdentifier] = useState(typed)
  const [error, setError] = useState<string>()
  const [problem, setProblem] = useState<string | null>(null)
  const [failures, setFailures] = useState(0)
  const [pending, setPending] = useState(false)
  const [sent, setSent] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setProblem(null)
    setSent(false)
    if (!identifier.trim()) {
      setError('Enter your username or email')
      return inputRef.current?.focus()
    }
    setError(undefined)

    setPending(true)
    const failure = await sendPasswordReset(identifier.trim())
    setPending(false)
    if (failure) {
      setProblem(failure)
      setFailures(failures + 1)
    } else {
      setSent(true)
    }
  }

  return (
    <AuthLayout>
      <Link
        to="/sign-in"
        className="mb-6 inline-flex items-center gap-1.5 text-base text-foreground before:size-[0.45rem] before:rotate-45 before:border-b-2 before:border-l-2 before:border-current before:content-[''] hover:text-foreground"
      >
        Back
      </Link>
      {problem && (
        <ErrorSummary key={failures} errors={[{ fieldId: 'reset-identifier', message: problem }]} />
      )}
      <PageHeading>Reset your password</PageHeading>
      {/* Always in the page, so screen readers announce the message when it fills in. */}
      <div role="status">
        {sent && (
          <div className="mb-6 border-l-[5px] border-yes bg-yes-soft px-4 py-3.5">
            <p className="mb-4">
              If that account has an email address, we've sent it a link to reset the password. The
              link works for 1 hour.
            </p>
            <p>No email on your account? Ask a store manager to give you a temporary password.</p>
          </div>
        )}
      </div>
      <Lead>
        Enter your username or email. If your account has an email address, we'll send a link to it.
        If it doesn't, a store manager can give you a temporary password.
      </Lead>
      <form noValidate onSubmit={onSubmit}>
        <Field id="reset-identifier" label="Username or email" error={error}>
          {({ id, describedBy, invalid }) => (
            <TextInput
              ref={inputRef}
              id={id}
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
        <SubmitButton pending={pending}>{pending ? 'Sending' : 'Send reset link'}</SubmitButton>
      </form>
    </AuthLayout>
  )
}
