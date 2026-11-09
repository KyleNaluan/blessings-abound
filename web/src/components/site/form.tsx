import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// Form pieces in the GOV.UK pattern the sign-in mockups use: a label, an optional hint, an error above the input, and an
// error summary at the top of the page that takes focus.

export type FieldError = { fieldId: string; message: string }

// Takes focus when it appears. Give it a new key on each failed submit, so a repeat failure takes focus again.
export function ErrorSummary({ errors }: { errors: FieldError[] }) {
  const ref = useRef<HTMLDivElement>(null)

  // Move focus during the commit, before paint, so the focus lands synchronously with the summary appearing.
  useLayoutEffect(() => {
    ref.current?.focus()
  }, [])

  return (
    <div
      ref={ref}
      role="alert"
      tabIndex={-1}
      aria-labelledby="error-summary-title"
      // A ring even after a mouse click, so the move of focus to the summary is always visible, as in GOV.UK.
      className="mb-7 rounded-xl border-4 border-destructive bg-card px-5 py-4 focus:outline-4 focus:outline-offset-0 focus:outline-ring focus:outline-solid"
    >
      <h2 id="error-summary-title" className="mb-2 text-xl font-bold">
        There is a problem
      </h2>
      <ul>
        {errors.map((error) => (
          <li key={error.fieldId + error.message}>
            <a
              href={`#${error.fieldId}`}
              className="font-bold text-destructive hover:text-destructive"
              onClick={(event) => {
                event.preventDefault()
                document.getElementById(error.fieldId)?.focus()
              }}
            >
              {error.message}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

type FieldProps = {
  label: string
  hint?: string
  error?: string
  // Renders the input, given the ids its aria-describedby should list and whether it is in error.
  children: (props: { id: string; describedBy?: string; invalid: boolean }) => ReactNode
  id: string
  // For the wrapper, such as text-sm to make the label, hint and error smaller together.
  className?: string
}

export function Field({ label, hint, error, children, id, className }: FieldProps) {
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cn('mb-6', error && 'border-l-4 border-destructive pl-3.5', className)}>
      <label htmlFor={id} className="mb-1 block font-bold">
        {label}
      </label>
      {hint && (
        <p id={hintId} className="mb-1.5 text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className="mb-1.5 font-bold text-destructive">
          {error}
        </p>
      )}
      {children({ id, describedBy, invalid: Boolean(error) })}
    </div>
  )
}

type InputProps = ComponentProps<'input'> & { invalid?: boolean }

export function TextInput({ invalid = false, className, ...props }: InputProps) {
  return (
    <input
      aria-invalid={invalid}
      className={cn(
        'h-11 w-full min-w-0 rounded-md border-2 border-input bg-background px-2.5 text-foreground',
        invalid && 'border-destructive',
        className,
      )}
      {...props}
    />
  )
}

// A password input with a Show button, so people on a phone can check what they typed.
export function PasswordInput(props: Omit<InputProps, 'type'>) {
  const [shown, setShown] = useState(false)
  const controlsId = useId()
  const id = props.id ?? controlsId

  return (
    <div className="flex gap-2">
      <TextInput {...props} id={id} type={shown ? 'text' : 'password'} className="flex-1" />
      <button
        type="button"
        aria-controls={id}
        aria-pressed={shown}
        onClick={() => setShown(!shown)}
        className="h-11 min-w-18 flex-none cursor-pointer rounded-lg border-2 border-link bg-background text-base leading-none font-bold text-link hover:border-primary-hover hover:text-primary-hover"
      >
        {shown ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <Button
      type="submit"
      size="lg"
      disabled={pending}
      aria-busy={pending}
      className="max-sm:w-full"
    >
      {children}
    </Button>
  )
}

type RadioGroupProps<T extends string> = {
  // The first option's id, which an error summary link focuses.
  id: string
  legend: string
  hint?: string
  error?: string
  options: readonly (readonly [T, string])[]
  // Lets a legend that is also a section's heading take the heading's size.
  legendClassName?: string
  value: T | null
  disabled?: boolean
  onChange: (value: T) => void
}

// A set of radios in a fieldset, with the same hint and error layout as Field.
export function RadioGroup<T extends string>({
  id,
  legend,
  hint,
  error,
  options,
  legendClassName,
  value,
  disabled = false,
  onChange,
}: RadioGroupProps<T>) {
  const hintId = `${id}-hint`
  const errorId = `${id}-error`
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ') || undefined

  // The error bar is on a wrapper, because a fieldset draws its border around the legend's middle.
  return (
    <div className={cn('mb-6', error && 'border-l-4 border-destructive pl-3.5')}>
      <fieldset aria-describedby={describedBy}>
        <legend className={cn('mb-1 font-bold', legendClassName)}>{legend}</legend>
        {hint && (
          <p id={hintId} className="mb-1.5 text-muted-foreground">
            {hint}
          </p>
        )}
        {error && (
          <p id={errorId} className="mb-1.5 font-bold text-destructive">
            {error}
          </p>
        )}
        {options.map(([option, label], index) => (
          <label key={option} className="flex min-h-11 cursor-pointer items-center gap-2">
            <input
              type="radio"
              id={index === 0 ? id : `${id}-${option}`}
              name={id}
              value={option}
              checked={value === option}
              disabled={disabled}
              onChange={() => onChange(option)}
              className="size-5 flex-none accent-primary"
            />
            {label}
          </label>
        ))}
      </fieldset>
    </div>
  )
}
