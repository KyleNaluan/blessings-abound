import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { REPO_URL, SiteFooter } from '@/components/site/SiteFooter'
import { SiteHeader, SkipLink } from '@/components/site/SiteHeader'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/usePageTitle'

import { By } from './landing/parts'
import { Walkthrough } from './landing/Walkthrough'

const sections = [
  { label: 'Walkthrough', href: '#walkthrough' },
  { label: 'The rules', href: '#rules' },
  { label: 'Limits', href: '#limits' },
  { label: 'About', href: '#about' },
]

export function LandingPage() {
  usePageTitle()

  return (
    <>
      <SkipLink />
      <SiteHeader brandHref="#top" links={sections} />
      <main id="main">
        <Start />
        <Walkthrough />
        <Problems />
        <Rules />
        <Limits />
        <About />
      </main>
      <SiteFooter />
    </>
  )
}

function Start() {
  return (
    <div
      className="page-wrap grid grid-cols-1 gap-6 pt-8 pb-8 wide:grid-cols-[2fr_1fr] wide:gap-12 wide:pt-12"
      id="top"
    >
      <div>
        <h1 className="mb-6 max-w-[38rem] text-[clamp(2.25rem,4.6vw,3rem)] leading-[1.1] font-extrabold tracking-[-0.02em]">
          List donated items online and keep every shop in sync
        </h1>
        <p className="mb-4">
          Turnstone takes an item from a photo to an approved listing on two shops, ends the other
          listing when it sells, and tells you which shelf to pick it from. AI drafts and explains,
          code enforces the rules, and a person makes every final call.
        </p>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <Button
            asChild
            size="lg"
            className="px-[1.4rem] py-[0.8rem] text-[1.1875rem] leading-[1.1]"
          >
            <Link to="/sign-in">
              Sign in
              <svg width="14" height="16" viewBox="0 0 14 16" aria-hidden="true">
                <path d="M2 1.5 9.5 8 2 14.5" fill="none" stroke="currentColor" strokeWidth="3" />
              </svg>
            </Link>
          </Button>
          <p className="text-muted-foreground">
            Accounts come from a store manager. There's no public sign-up.
          </p>
        </div>
      </div>
      <aside
        className="hidden self-start border-t-4 border-primary pt-4 wide:block"
        aria-labelledby="related-heading"
      >
        <h2
          id="related-heading"
          className="mb-3 text-lg leading-[1.2] font-bold tracking-[-0.01em]"
        >
          Related
        </h2>
        <ul className="text-base">
          <li className="mb-2.5">
            <a href="#walkthrough">Follow one item through the app</a>
          </li>
          <li className="mb-2.5">
            <a href="#rules">Who decides what</a>
          </li>
          <li className="mb-2.5">
            <a href="#limits">What it can't tell you yet</a>
          </li>
          <li className="mb-2.5">
            <a href={REPO_URL}>The code on GitHub</a>
          </li>
        </ul>
      </aside>
    </div>
  )
}

function Band({
  id,
  title,
  intro,
  className,
  children,
}: {
  id: string
  title: string
  intro: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section id={id} className={className ?? 'pt-12 pb-4 sm:pt-18'}>
      <div className="page-wrap">
        <h2 className="text-[clamp(1.5rem,3vw,2rem)] leading-[1.2] font-extrabold tracking-[-0.02em]">
          {title}
        </h2>
        <p className="mt-3 mb-7 max-w-[42rem]">{intro}</p>
        {children}
      </div>
    </section>
  )
}

// A GOV.UK summary list: a bold label and its explanation, side by side on a desktop.
function Summary({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="max-w-[52rem] border-t border-rule">
      {rows.map(([term, detail], index) => (
        <div
          key={index}
          className="grid grid-cols-1 gap-1 border-b border-rule py-3.5 sm:grid-cols-[14rem_1fr] sm:gap-6"
        >
          <dt className="font-bold">{term}</dt>
          <dd>{detail}</dd>
        </div>
      ))}
    </dl>
  )
}

function Problems() {
  return (
    <Band
      id="problem"
      title="Why the store needs it"
      intro="Blessings Abound, a Kansas City nonprofit with three thrift stores, told our class that online sales are under 3% of its revenue. These are the problems it described."
    >
      <ul className="max-w-[42rem] list-disc pl-5">
        <li className="mb-2">
          Items go back and forth between the store floor and Ecommerce, and the store asked for a
          log of what gets turned down and why.
        </li>
        <li className="mb-2">
          Deciding what's worth listing, and at what price, rests on judgment and Google Lens
          lookups.
        </li>
        <li className="mb-2">Photos and descriptions are the slowest part of making a listing.</li>
        <li className="mb-2">
          Items listed on two sites sometimes sell on both. The store reported 12 orders cancelled
          for that in a year, which was 1.6% of its sales.
        </li>
      </ul>
    </Band>
  )
}

function Rules() {
  return (
    <Band
      id="rules"
      title="Who decides what"
      intro="The language model writes words. It never produces a price, approves a listing or changes an item's status."
    >
      <Summary
        rows={[
          [
            <>
              <By who="ai">AI</By> drafts and explains
            </>,
            "Reads the photo into a draft item card, explains the price in two or three sentences, writes listing drafts, gives a one-line reason for a channel, explains Needs Attention problems, and answers a manager's questions about sales. It never sets a price or changes a status.",
          ],
          [
            <>
              <By who="code">Code</By> enforces the rules
            </>,
            "Makes the SKU, the price range and the worth-listing rule, checks drafts for unsupported claims, rejects any explanation that contains a number it didn't compute, and does all syncing, delisting and flagging.",
          ],
          [
            <>
              <By who="person">A person</By> decides
            </>,
            'Staff correct the item card, decide whether to list, and fix flagged problems. A manager approves every listing, sets the price and channels, and picks the box and shelf.',
          ],
        ]}
      />
      <p className="mt-4 mb-4 max-w-[42rem] text-muted-foreground">
        Two analyses the store asked about are left out on purpose: order risk by buyer ZIP code,
        and whether a buyer's username predicts offer acceptance. ZIP code stands in for income,
        race and age, and a username says nothing reliable about how someone behaves in a deal.
      </p>
    </Band>
  )
}

function Limits() {
  return (
    <Band
      id="limits"
      title="What it can't tell you yet"
      intro="This is a proof of concept for two categories, branded apparel, and electronics and video games. These are its limits."
    >
      <Summary
        rows={[
          [
            'The shops are mock',
            'Channel A stands in for an eBay-style marketplace and Channel B for a Depop or Poshmark-style app. We built both, and nothing is listed on a real site.',
          ],
          [
            'Comps are asking prices',
            "The eBay search we use no longer returns sold listings, so a factor turns asking prices into expected sale prices, and it's labeled an assumption. For apparel the factor is 0.645, from Poshmark data where the ask-to-sale ratios ran from 1.21 to 2.93. For games and hardware it's 0.94, from the median asking price per reference on 18 items.",
          ],
          [
            'Sales history is synthetic',
            "The store's sales log isn't part of this project, so the dashboards run on about 600 simulated items over 12 months, and every chart says so. The simulation is tuned to vendor-reported sell-through and time-to-sell figures from two resale tools, FlowLister and Closo, so the charts show what the tool can do, not a finding about what sells.",
          ],
          [
            'Samples are small',
            "The pricing prototype was scored on 8 items, and 6 of its ranges held the sold price against 2 for raw asking prices. That's too few items to trust the percentages.",
          ],
          [
            'Thresholds are borrowed',
            "The $30 bar comes from the client's short Q&A, not from their sales data, so it lives in Settings where a manager can change it.",
          ],
        ]}
      />
    </Band>
  )
}

function About() {
  return (
    <Band
      id="about"
      title="About this project"
      className="pt-12 pb-16 sm:pt-18"
      intro="A student team is building this for Hack-A-Roo Fall 2026, with a research poster, a hosted demo and the code due on November 9. It shows how data science and AI could help with the problems the store described, whether or not they adopt it."
    >
      <p className="-mt-3 mb-4 max-w-[42rem]">
        We have no client sales data, so the tool uses public listings, our own photos and made-up
        sales. It stores items, photos, decisions and staff accounts, and no buyer data.
      </p>
      <p className="mb-4">
        <a href={REPO_URL}>Read the code on GitHub</a>
      </p>
    </Band>
  )
}
