import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

// One part of the appraisal screen, framed like the panels on the review page.
export function Panel({
  id,
  title,
  className,
  children,
}: {
  id: string
  title: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section
      aria-labelledby={`${id}-heading`}
      className={cn('mb-7 border border-rule p-4', className)}
    >
      <h2 id={`${id}-heading`} className="mb-3 text-xl font-bold">
        {title}
      </h2>
      {children}
    </section>
  )
}
