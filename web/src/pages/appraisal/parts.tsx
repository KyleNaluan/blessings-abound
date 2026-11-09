import type { ReactNode } from 'react'

import { SectionCard } from '@/components/site/SectionCard'

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
    <SectionCard id={id} title={title} className={className}>
      {children}
    </SectionCard>
  )
}
