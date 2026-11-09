import { Link } from 'react-router'

import { SiteFooter } from '@/components/site/SiteFooter'
import { SiteHeader, SkipLink } from '@/components/site/SiteHeader'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

import { SITE_LINKS } from './landing/links'
import { Walkthrough } from './landing/Walkthrough'

// The front door: what Turnstone does, Sign in, and one example item followed through the app.
// The rest of the project's story is on the About page, so this one stays short.
export function LandingPage() {
  usePageTitle()

  return (
    <>
      <SkipLink />
      <SiteHeader brandHref="#top" links={SITE_LINKS} />
      <main id="main" className="pb-12">
        <Start />
        <Walkthrough />
      </main>
      <SiteFooter />
    </>
  )
}

function Start() {
  return (
    <div
      className="page-wrap grid grid-cols-1 gap-x-12 gap-y-5 pt-8 pb-8 wide:grid-cols-[1.1fr_1fr] wide:items-start wide:pt-10"
      id="top"
    >
      <h1 className="text-[clamp(2rem,4vw,2.75rem)] leading-[1.1] font-extrabold tracking-[-0.02em]">
        List donated items online and keep every shop in sync
      </h1>
      <div>
        <p className="mb-4">
          From a photo to an approved listing on two shops, with the other listing ended when it
          sells. AI drafts and explains, code enforces the rules, and a person makes every final
          call.
        </p>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <Button asChild size="lg">
            <Link to="/sign-in">
              Sign in
              <svg width="14" height="16" viewBox="0 0 14 16" aria-hidden="true">
                <path d="M2 1.5 9.5 8 2 14.5" fill="none" stroke="currentColor" strokeWidth="3" />
              </svg>
            </Link>
          </Button>
          <p className="text-sm text-muted-foreground">
            Accounts come from a store manager. There's no public sign-up.
          </p>
        </div>
      </div>
    </div>
  )
}
