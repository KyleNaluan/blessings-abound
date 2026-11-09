import type { ReactNode } from 'react'

import { SiteFooter } from './SiteFooter'
import { SiteHeader, SkipLink } from './SiteHeader'

// The frame for the signed-out pages, sign-in and choosing a password: the brand bar, one narrow column, and the footer.
// Signed-in pages use AppLayout instead.
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <SkipLink />
      <SiteHeader />
      <main id="main" className="page-wrap flex-1 pt-10 pb-12">
        <div className="max-w-[30rem]">{children}</div>
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
