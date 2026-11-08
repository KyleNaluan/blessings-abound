import { useId, useRef, useState, type FormEvent } from 'react'

import { askInsight, type InsightAnswer } from '@/api/dashboards'
import { Field, TextInput } from '@/components/site/form'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { SourceNote } from './charts'
import { SOURCE_LINE } from './format'

const QUESTION_MAX = 300

type Asked = { key: number; answer: InsightAnswer }
type Failure = { question: string; message: string }

function and(items: string[]) {
  if (items.length < 2) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

// Why the answer is the function's own sentence rather than the model's wording, if it is.
function fallbackNote(answer: InsightAnswer) {
  if (answer.fallback_reason === 'flagged') {
    const numbers = and(answer.rejected_numbers)
    return `The model's wording had ${numbers}, which the function didn't return, so this is the function's own sentence instead.`
  }
  if (answer.fallback_reason === 'model_failed') {
    return "The model couldn't word an answer, so this is the function's own sentence."
  }
  return null
}

function Answer({ answer }: { answer: InsightAnswer }) {
  const id = useId()
  const note = fallbackNote(answer)
  return (
    <article
      aria-labelledby={id}
      className={cn(
        'mb-8 max-w-[42rem] border-l-4 pl-4 wide:pl-5',
        answer.source ? SOURCE_LINE[answer.source] : 'border-rule',
      )}
    >
      <h3 id={id} className="font-bold break-words">
        {answer.question}
      </h3>
      {answer.source && <SourceNote source={answer.source} />}
      <p className="mt-3 break-words">{answer.answer}</p>
      {note && <p className="mt-2 text-sm text-muted-foreground">{note}</p>}
      {answer.call && (
        <p className="mt-3 text-sm text-muted-foreground">
          Worked out with{' '}
          <code className="font-mono text-[0.8125rem] break-all text-foreground">
            {answer.call}
          </code>
        </p>
      )}
      {answer.facts.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer font-bold text-link">Show the numbers</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-[0.9375rem]">
              <caption className="sr-only">What the function returned</caption>
              <tbody>
                {answer.facts.map((fact) => (
                  <tr key={fact.label} className="border-b border-rule">
                    <th scope="row" className="py-2 pr-3 align-top font-normal wide:w-2/5">
                      {fact.label}
                    </th>
                    <td className="py-2 text-right align-top">{fact.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </article>
  )
}

// A manager asks a sales question, the model picks one of a fixed set of tested functions, code
// works out the numbers, and each answer shows the call it came from. Newest answer first.
export function InsightChat() {
  const [question, setQuestion] = useState('')
  const [empty, setEmpty] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [asked, setAsked] = useState<Asked[]>([])
  const nextKey = useRef(0)

  function ask(text: string) {
    setPending(text)
    setFailure(null)
    askInsight(text)
      .then((answer) => {
        setAsked((before) => [{ key: nextKey.current++, answer }, ...before])
        setQuestion((current) => (current.trim() === text ? '' : current))
      })
      .catch((error: Error) => setFailure({ question: text, message: error.message }))
      .finally(() => setPending(null))
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const text = question.trim()
    setEmpty(text === '')
    if (text !== '' && pending === null) ask(text)
  }

  return (
    <section aria-labelledby="ask-heading" className="mb-12 border-t border-rule pt-8">
      <h2
        id="ask-heading"
        className="mb-3 text-[clamp(1.5rem,3vw,2rem)] leading-[1.2] font-extrabold tracking-[-0.02em]"
      >
        Ask about sales
      </h2>
      <p className="mb-5 max-w-[42rem]">
        The language model picks one of a few tested functions to answer from, code works out the
        numbers, and each answer shows the function it came from. It can answer about time to sell,
        seasonality, the triage funnel, the live test sales and sync.
      </p>
      <form onSubmit={submit} noValidate className="max-w-[42rem]">
        <Field
          id="insight-question"
          label="Your question"
          hint="For example, which month sells the most electronics, or how fast apparel under $15 sells."
          error={empty ? 'Type a question first.' : undefined}
        >
          {({ id, describedBy, invalid }) => (
            <div className="flex flex-col gap-3 sm:flex-row">
              <TextInput
                id={id}
                value={question}
                maxLength={QUESTION_MAX}
                autoComplete="off"
                aria-describedby={describedBy}
                invalid={invalid}
                onChange={(event) => {
                  setQuestion(event.target.value)
                  if (empty) setEmpty(false)
                }}
                className="flex-1"
              />
              <Button
                type="submit"
                size="lg"
                disabled={pending !== null}
                aria-busy={pending !== null}
                className="max-sm:w-full"
              >
                {pending === null ? 'Ask' : 'Asking...'}
              </Button>
            </div>
          )}
        </Field>
      </form>
      <div aria-live="polite">
        {pending !== null && (
          <p className="mb-7 max-w-[42rem] font-bold break-words">
            Working out the answer to &ldquo;{pending}&rdquo;...
          </p>
        )}
      </div>
      {failure && (
        <div role="alert" className="mb-7 max-w-[42rem] border-4 border-destructive px-5 py-4">
          <p className="mb-1 font-bold break-words">{failure.message}</p>
          <p className="mb-3 break-words text-muted-foreground">
            You asked &ldquo;{failure.question}&rdquo;.
          </p>
          <Button
            variant="outline"
            size="lg"
            className="max-sm:w-full"
            disabled={pending !== null}
            onClick={() => ask(failure.question)}
          >
            Try again
          </Button>
        </div>
      )}
      {asked.length > 0 && (
        <div>
          {asked.map(({ key, answer }) => (
            <Answer key={key} answer={answer} />
          ))}
        </div>
      )}
    </section>
  )
}
