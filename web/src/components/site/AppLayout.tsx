import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router'

import { useAuth } from '@/auth/AuthContext'
import { signedInName } from '@/auth/accounts'
import { cn } from '@/lib/utils'

import { TurnstoneMark } from './TurnstoneMark'
import { SignOutButton } from './SignOutButton'
import { SiteFooter } from './SiteFooter'
import { SkipLink } from './SiteHeader'

type AppLink = { label: string; to: string; managerOnly?: boolean; end?: boolean }

// The pages in the bar, home first and then in the order of an item's day: in at appraisal, through approval, out on the pick list.
const APP_LINKS: AppLink[] = [
  { label: 'Home', to: '/app', end: true },
  { label: 'Appraise', to: '/app/appraise' },
  { label: 'Approvals', to: '/app/approvals', managerOnly: true },
  { label: 'Pick list', to: '/app/pick-list' },
  { label: 'Needs attention', to: '/app/attention' },
  { label: 'Dashboards', to: '/app/dashboards', managerOnly: true },
  { label: 'Team', to: '/app/team', managerOnly: true },
  { label: 'Settings', to: '/app/settings', managerOnly: true },
]

// The frame for every signed-in page: the navigation bar, the page, and the footer kept at the bottom.
// Text runs the page's width, and a form or field keeps its own narrower width.
export function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <SkipLink />
      <AppHeader />
      <main id="main" className="app-wrap flex-1 pt-8 pb-12">
        {children}
      </main>
      <SiteFooter />
    </div>
  )
}

function AppHeader() {
  const { me, session } = useAuth()
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const { pathname } = useLocation()
  const links = APP_LINKS.filter((link) => !link.managerOnly || me?.role === 'manager')
  const name = me?.display_name || signedInName(session?.user.email)

  // A new page closes the phone menu.
  const [lastPath, setLastPath] = useState(pathname)
  if (pathname !== lastPath) {
    setLastPath(pathname)
    setOpen(false)
  }

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        buttonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'block rounded-md px-3 py-2 text-[0.9375rem] font-semibold whitespace-nowrap text-foreground no-underline hover:bg-white/10 hover:text-foreground hover:no-underline',
      isActive && 'bg-white/15 text-foreground',
    )

  return (
    <header className="relative band">
      <div className="app-wrap flex min-h-16 items-center gap-6">
        <Link
          to="/app"
          className="flex shrink-0 items-center gap-2.5 text-lg font-bold text-foreground no-underline hover:text-foreground hover:no-underline"
          aria-label="Turnstone, home"
        >
          <TurnstoneMark />
          Turnstone
        </Link>
        <button
          ref={buttonRef}
          type="button"
          className="ml-auto inline-flex min-h-11 cursor-pointer items-center gap-1.5 px-1 text-base leading-none font-bold text-link app-nav:hidden"
          aria-expanded={open}
          aria-controls="app-nav"
          onClick={() => setOpen(!open)}
        >
          Menu
          <svg
            width="12"
            height="8"
            viewBox="0 0 12 8"
            aria-hidden="true"
            className={cn(
              'transition-transform motion-reduce:transition-none',
              open && 'rotate-180',
            )}
          >
            <path d="M1 1.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
        <div
          id="app-nav"
          className={cn(
            'absolute inset-x-0 top-full z-10 border-t border-rule band px-4 pt-2 pb-4 app-nav:static app-nav:flex app-nav:flex-1 app-nav:items-center app-nav:border-0 app-nav:p-0',
            open ? 'block' : 'hidden',
          )}
        >
          <nav aria-label="Main" className="app-nav:flex-1">
            <ul className="flex flex-col gap-1 app-nav:flex-row app-nav:items-center">
              {links.map((link) => (
                <li key={link.to}>
                  <NavLink to={link.to} end={link.end} className={linkClass}>
                    {link.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="mt-3 flex items-center justify-between gap-4 border-t border-rule pt-3 app-nav:mt-0 app-nav:border-0 app-nav:pt-0">
            {name && <span className="text-[0.9375rem] text-muted-foreground">{name}</span>}
            <SignOutButton size="default" />
          </div>
        </div>
      </div>
    </header>
  )
}
