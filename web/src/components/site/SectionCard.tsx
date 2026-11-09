import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

import { cardSurface } from './card'

// One section of a signed-in page, such as a settings group or a review panel: a white card on the
// cream page, with its heading at the top. A list of items goes in a DataTable instead.
export function SectionCard({
  id,
  title,
  description,
  className,
  children,
}: {
  id: string
  title: ReactNode
  description?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className={cn('mb-6', cardSurface, className)}>
      <h2 id={`${id}-heading`} className="text-xl font-bold">
        {title}
      </h2>
      {description && <p className="mt-1 text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}
