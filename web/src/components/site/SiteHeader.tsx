import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { cn } from '@/lib/utils'

import { HangTag } from './HangTag'

export type NavLink = { label: string; href: string }

type SiteHeaderProps = {
  // Where the brand points: "/" by default, or an in-page anchor such as "#top" on the landing page.
  brandHref?: string
  // In-page sections to list before Sign in, with a menu button on a phone.
  links?: NavLink[]
  // Shown at the end of the bar instead, such as a Sign out button.
  end?: ReactNode
}

export function SkipLink() {
  return (
    <a
      href="#main"
      className="absolute top-0 -left-[999rem] z-20 bg-warn px-4 py-2 text-foreground no-underline focus:left-0"
    >
      Skip to main content
    </a>
  )
}

export function SiteHeader({ brandHref = '/', links, end }: SiteHeaderProps) {
  const brandClass =
    'flex items-center gap-2.5 text-lg font-bold text-foreground no-underline hover:text-foreground hover:no-underline'
  const brand = (
    <>
      <HangTag />
      Turnstone
    </>
  )

  return (
    <header className="relative border-b border-border bg-background">
      <div className="page-wrap flex min-h-16 items-center justify-between gap-4">
        {brandHref.startsWith('#') ? (
          <a className={brandClass} href={brandHref} aria-label="Turnstone, home">
            {brand}
          </a>
        ) : (
          <Link className={brandClass} to={brandHref} aria-label="Turnstone, home">
            {brand}
          </Link>
        )}
        {links ? <SiteNav links={links} /> : end}
      </div>
    </header>
  )
}

function SiteNav({ links }: { links: NavLink[] }) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)

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

  const itemClass =
    'block border-b border-rule py-3.5 text-[1.0625rem] text-foreground no-underline hover:text-link hover:underline wide:border-0 wide:py-0 wide:text-base'
  const close = () => setOpen(false)

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 px-1 text-base leading-none font-bold text-link wide:hidden"
        aria-expanded={open}
        aria-controls="site-nav"
        onClick={() => setOpen(!open)}
      >
        Menu
        <svg
          width="12"
          height="8"
          viewBox="0 0 12 8"
          aria-hidden="true"
          className={cn('transition-transform motion-reduce:transition-none', open && 'rotate-180')}
        >
          <path d="M1 1.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>
      </button>
      <nav
        id="site-nav"
        aria-label="Main"
        className={cn(
          'absolute inset-x-0 top-full z-10 border-b border-border bg-background wide:static wide:block wide:border-0',
          open ? 'block' : 'hidden',
        )}
      >
        <ul className="flex flex-col px-4 pb-2 wide:flex-row wide:items-center wide:gap-7 wide:p-0">
          {links.map((link) => (
            <li key={link.href}>
              <a className={itemClass} href={link.href} onClick={close}>
                {link.label}
              </a>
            </li>
          ))}
          <li>
            <Link
              className={cn(itemClass, 'border-b-0 font-bold text-link underline')}
              to="/sign-in"
              onClick={close}
            >
              Sign in
            </Link>
          </li>
        </ul>
      </nav>
    </>
  )
}
