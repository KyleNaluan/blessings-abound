import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

// The tables for lists of items, such as the pick list and Needs attention. A card frames a
// section of a page, and an item is a row in one of these tables, never a card of its own.
// On a wide screen each table has lined columns of fixed widths, so two tables with the same
// columns line up. On a phone the column names hide and each row stacks its cells.
// A table's children are TableBody elements, which hold its rows.

export type Column = {
  label: string
  // A Tailwind width class, such as 'w-[9rem]'. A column without one takes the space left.
  width?: string
  // Kept for screen readers only, such as the column of buttons.
  hidden?: boolean
}

// A group of items: a heading with how many there are, an optional note, and its table or its
// empty message.
export function TableSection({
  id,
  title,
  count,
  unit = ['item', 'items'],
  description,
  children,
}: {
  id: string
  title: ReactNode
  count?: number
  unit?: [string, string]
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="mb-10">
      <h2 id={`${id}-heading`} className="mb-3 text-xl font-bold">
        {title}
        {count !== undefined && (
          <span className="font-normal text-muted-foreground">
            {' '}
            · {count} {count === 1 ? unit[0] : unit[1]}
          </span>
        )}
      </h2>
      {description && <p className="-mt-1 mb-3 text-muted-foreground">{description}</p>}
      {children}
    </section>
  )
}

export function DataTable({ columns, children }: { columns: Column[]; children: ReactNode }) {
  return (
    <table className="w-full table-fixed border-collapse border border-rule bg-card text-left max-wide:block max-wide:border-x-0 max-wide:border-b-0 max-wide:bg-transparent">
      <colgroup className="max-wide:hidden">
        {columns.map((column) => (
          <col key={column.label} className={column.width} />
        ))}
      </colgroup>
      <thead className="max-wide:sr-only">
        <tr className="border-b-2 border-rule bg-surface text-sm text-muted-foreground [&>th:not(:last-child)]:border-r [&>th:not(:last-child)]:border-rule">
          {columns.map((column) => (
            <th key={column.label} scope="col" className="px-3 py-2 font-semibold">
              {column.hidden ? <span className="sr-only">{column.label}</span> : column.label}
            </th>
          ))}
        </tr>
      </thead>
      {children}
    </table>
  )
}

// The rows of a table. A list of plain rows shares one body, and an item that opens details
// below its row has a body of its own, so the row and its details stay together.
export function TableBody({ children }: { children: ReactNode }) {
  return <tbody className="max-wide:block">{children}</tbody>
}

// One item. An open row shares its tint with the details row under it.
export function Row({ open = false, children }: { open?: boolean; children: ReactNode }) {
  return (
    <tr
      className={cn(
        'border-b border-rule wide:[&>td:not(:last-child)]:border-r wide:[&>td:not(:last-child)]:border-rule',
        'max-wide:grid max-wide:gap-1 max-wide:py-3.5',
        open && 'bg-muted/50',
      )}
    >
      {children}
    </tr>
  )
}

// On a phone the column names are hidden, so a cell whose value doesn't say what it is, such as a
// date or a price, gives its column's name above the value. Screen readers already have the column
// names, so they skip it.
export function Cell({
  label,
  className,
  children,
}: {
  label?: string
  className?: string
  children: ReactNode
}) {
  return (
    <td className={cn('px-3 py-3 align-middle max-wide:p-0', className)}>
      {label && (
        <span
          aria-hidden="true"
          className="block text-[0.8125rem] font-normal text-muted-foreground wide:hidden"
        >
          {label}
        </span>
      )}
      {children}
    </td>
  )
}

// The buttons at the end of a row, which go under the rest of the row on a phone.
export function ActionCell({ children }: { children: ReactNode }) {
  return (
    <td className="px-3 py-3 text-right align-middle max-wide:p-0 max-wide:pt-2 max-wide:text-left">
      <div className="inline-flex flex-wrap justify-end gap-2 max-wide:flex max-wide:justify-start">
        {children}
      </div>
    </td>
  )
}

// A second, quieter line in a cell, such as the SKU under an item's name.
export function SubText({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span className={cn('block text-sm wrap-anywhere text-muted-foreground', className)}>
      {children}
    </span>
  )
}

// What a row's button opens, across the whole table under that row.
export function DetailsRow({
  id,
  colSpan,
  children,
}: {
  id: string
  colSpan: number
  children: ReactNode
}) {
  return (
    <tr className="border-b border-rule bg-muted/50 max-wide:block">
      <td id={id} colSpan={colSpan} className="px-4 pt-1 pb-5 max-wide:block max-wide:px-0">
        <div className="max-w-[48rem]">{children}</div>
      </td>
    </tr>
  )
}

// What a section says when it has no items, framed like a table so the page keeps its shape.
export function EmptyTable({ children }: { children: ReactNode }) {
  return <p className="border border-rule bg-card px-4 py-3 text-muted-foreground">{children}</p>
}
