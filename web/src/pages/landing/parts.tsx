import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

// Small pieces the landing page's example screens share, so each label and table looks the same everywhere.

// Who does a step. AI, code and a person each get one look on every screen.
export function By({ who, children }: { who: 'ai' | 'code' | 'person'; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-block border px-1.5 py-px text-[0.8125rem] leading-[1.4] font-semibold whitespace-nowrap',
        who === 'ai' && 'border-warn-line bg-warn-soft text-warn-ink',
        who === 'code' && 'border-plain-line bg-plain-soft text-plain-ink',
        who === 'person' && 'border-info-line bg-info-soft text-info-ink',
      )}
    >
      {children}
    </span>
  )
}

export function Tag({ tone, children }: { tone: 'green' | 'red' | 'blue'; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-block flex-none px-2 py-0.5 text-[0.8125rem] leading-normal whitespace-nowrap',
        tone === 'green' && 'bg-yes-soft text-yes-ink',
        tone === 'red' && 'bg-no-soft text-no-ink',
        tone === 'blue' && 'bg-info-soft text-info-ink',
      )}
    >
      {children}
    </span>
  )
}

// A two-column list of labels and values, with the values right-aligned.
export function KeyValues({
  rows,
  className,
}: {
  rows: [string, ReactNode][]
  className?: string
}) {
  return (
    <dl className={cn('grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm', className)}>
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right font-semibold wrap-anywhere">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn('mt-1 text-[0.8125rem] text-muted-foreground', className)}>{children}</p>
}

// Text the language model wrote, always with a line saying so.
export function AiText({
  source,
  children,
  className,
}: {
  source: string
  children: ReactNode
  className?: string
}) {
  return (
    <p
      className={cn(
        'mb-4 border-l-4 border-warn-line bg-warn-soft px-3 py-2.5 text-[0.9375rem]',
        className,
      )}
    >
      {children}
      <span className="mt-1.5 block text-[0.8125rem] text-warn-ink">{source}</span>
    </p>
  )
}

export function Checks({ items, className }: { items: string[]; className?: string }) {
  return (
    <ul className={cn('mb-4 text-sm', className)}>
      {items.map((item) => (
        <li
          key={item}
          className="grid grid-cols-[1.25rem_1fr] gap-1.5 border-b border-rule py-1.5 before:mt-1.5 before:h-1.5 before:w-3 before:-rotate-45 before:border-b-2 before:border-l-2 before:border-yes-ink before:content-['']"
        >
          {item}
        </li>
      ))}
    </ul>
  )
}

// A small table. Cells marked as numbers keep their digits lined up and on one line.
export function MiniTable({
  caption,
  head,
  rows,
  numeric = [],
}: {
  caption: string
  head: string[]
  rows: ReactNode[][]
  numeric?: number[]
}) {
  const cell = (column: number) =>
    cn(
      'border-b border-rule py-[0.45rem] pr-3 text-left align-top',
      numeric.includes(column) && 'whitespace-nowrap tabular-nums',
    )
  return (
    <table className="w-full border-collapse text-sm">
      <caption className="pb-1.5 text-left text-[0.9375rem] font-bold">{caption}</caption>
      <thead>
        <tr>
          {head.map((label, column) => (
            <th key={label} className={cn(cell(column), 'border-b-2 border-foreground font-bold')}>
              {label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {row.map((value, column) => (
              <td key={column} className={cell(column)}>
                {value}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function Heading4({ children }: { children: ReactNode }) {
  return <h4 className="mb-2.5 text-[0.9375rem] font-bold">{children}</h4>
}

// A look-alike form field from an example screen. It isn't an input, because nothing here can be edited.
export function ShownField({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-3">
      <span className="mb-1 block text-[0.8125rem] font-semibold">{label}</span>
      <div className="border border-input bg-background px-2 py-1.5 text-[0.9375rem] wrap-anywhere">
        {value}
      </div>
    </div>
  )
}

// A look-alike button from an example screen, hidden from assistive technology because it does nothing.
export function ShownButton({
  outline = false,
  className,
  children,
}: {
  outline?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex min-h-9 items-center rounded-lg px-3.5 py-1.5 text-[0.9375rem] leading-[1.1] font-bold',
        outline
          ? 'bg-background text-link shadow-[inset_0_0_0_2px_var(--link)]'
          : 'bg-primary text-primary-foreground',
        className,
      )}
    >
      {children}
    </span>
  )
}
