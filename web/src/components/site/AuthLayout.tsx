import type { ReactNode } from 'react'

import { SiteFooter } from './SiteFooter'
import { SiteHeader, SkipLink } from './SiteHeader'

// The frame for sign-in and account pages: the brand bar, one narrow column, and the footer kept at the bottom.
// A wide page uses the full width and narrows its own parts, as the appraisal screen does beside the price.
export function AuthLayout({
  end,
  wide = false,
  children,
}: {
  end?: ReactNode
  wide?: boolean
  children: ReactNode
}) {
  return (
    <div className="flex min-h-svh flex-col">
      <SkipLink />
      <SiteHeader end={end} />
      <main id="main" className="page-wrap flex-1 pt-10 pb-12">
        <div className={wide ? undefined : 'max-w-[30rem]'}>{children}</div>
      </main>
      <SiteFooter />
    </div>
  )
}

export function PageHeading({ children }: { children: ReactNode }) {
  return (
    <h1 className="mb-4 text-[2.5rem] leading-[1.1] font-extrabold tracking-[-0.02em]">
      {children}
    </h1>
  )
}

export function Lead({ children }: { children: ReactNode }) {
  return <p className="mb-7">{children}</p>
}
