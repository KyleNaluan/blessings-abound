import type { ReactNode } from 'react'
import { Tabs } from 'radix-ui'

import { cn } from '@/lib/utils'

import {
  AiText,
  By,
  Checks,
  Heading4,
  KeyValues,
  MiniTable,
  Note,
  ShownButton,
  ShownField,
  Tag,
} from './parts'

// One example item, a fleece jacket, followed from intake to sale. Every number here is illustrative.

type Step = { value: string; label: ReactNode; panel: ReactNode }

const steps: Step[] = [
  { value: 'intake', label: <Numbered n={1}>Intake</Numbered>, panel: <IntakePanel /> },
  { value: 'card', label: <Numbered n={2}>Item card</Numbered>, panel: <ItemCardPanel /> },
  { value: 'price', label: <Numbered n={3}>Price</Numbered>, panel: <PricePanel /> },
  { value: 'draft', label: <Numbered n={4}>Draft and approve</Numbered>, panel: <DraftPanel /> },
  { value: 'shelve', label: <Numbered n={5}>Shelve</Numbered>, panel: <ShelvePanel /> },
  { value: 'sold', label: <Numbered n={6}>Sold and synced</Numbered>, panel: <SoldPanel /> },
  { value: 'sales', label: 'Sales views', panel: <SalesPanel /> },
]

export function Walkthrough() {
  return (
    <div className="page-wrap" id="walkthrough">
      <h2 className="sr-only">Follow one item through the app</h2>
      <div className="border border-border bg-surface">
        <div className="bg-warn px-4 py-1.5 text-sm font-semibold text-foreground">
          Example data. One fleece jacket, DS10292603, from intake to sale.
        </div>
        <Tabs.Root defaultValue={steps[0].value}>
          <div className="border-b border-border bg-background px-4 pt-3 pb-3 wide:border-b-0 wide:pb-0">
            <Tabs.List
              aria-label="Steps for one item"
              className="flex flex-wrap gap-1 wide:flex-nowrap wide:gap-0 wide:border-b wide:border-border"
            >
              {steps.map((step) => (
                <Tabs.Trigger
                  key={step.value}
                  value={step.value}
                  className={cn(
                    'cursor-pointer border border-border bg-muted px-3.5 pt-2 pb-2 text-left text-[0.9375rem] leading-[1.3] text-link underline underline-offset-[0.15em] hover:text-primary-hover hover:decoration-2',
                    'data-[state=active]:border-foreground data-[state=active]:bg-foreground data-[state=active]:font-bold data-[state=active]:text-background data-[state=active]:no-underline',
                    'wide:mr-1 wide:-mb-px wide:border-b-0 wide:border-transparent wide:data-[state=active]:border-border wide:data-[state=active]:bg-background wide:data-[state=active]:text-foreground',
                  )}
                >
                  {step.label}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
          </div>
          {steps.map((step) => (
            <Tabs.Content
              key={step.value}
              value={step.value}
              className="bg-background p-5 focus-visible:-outline-offset-4 wide:border-t wide:border-border"
            >
              {step.panel}
            </Tabs.Content>
          ))}
        </Tabs.Root>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        Example screens with illustrative data. Channel A and Channel B are mock shops built for
        this project.
      </p>
    </div>
  )
}

function Numbered({ n, children }: { n: number; children: ReactNode }) {
  return (
    <>
      <span className="tabular-nums">{n}.</span> {children}
    </>
  )
}

function PanelHead({ title, by }: { title: string; by: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
      <h3 className="text-xl leading-[1.3] font-bold tracking-[-0.01em]">{title}</h3>
      <p className="flex flex-wrap gap-1.5">{by}</p>
    </div>
  )
}

function Columns({ wideLeft = false, children }: { wideLeft?: boolean; children: ReactNode }) {
  return (
    <div
      className={cn(
        'grid grid-cols-1 gap-6 *:min-w-0',
        wideLeft ? 'wide:grid-cols-[1.3fr_1fr]' : 'wide:grid-cols-2',
      )}
    >
      {children}
    </div>
  )
}

function IntakePanel() {
  return (
    <>
      <PanelHead
        title="Log it and give it a SKU"
        by={
          <>
            <By who="person">Staff</By>
            <By who="code">Code</By>
          </>
        }
      />
      <Columns>
        <div>
          <KeyValues
            className="text-[0.9375rem]"
            rows={[
              ['SKU', 'DS10292603'],
              ['Sent by', "Store floor, men's apparel"],
              ['Date sent', 'Oct 29, 2026'],
              ['Outcome', 'Accepted'],
              ['Duplicate check', 'No earlier photo matches'],
            ]}
          />
          <Note className="mt-4">
            The SKU is the lister's initials, the date and the day's count. The box size gets added
            after approval.
          </Note>
        </div>
        <MiniTable
          caption="Triage log, today"
          head={['SKU', 'Outcome', 'Where it went']}
          numeric={[0]}
          rows={[
            ['DS10292601', <Tag tone="green">Accepted</Tag>, 'Appraisal'],
            [
              'DS10292602',
              <Tag tone="red">Rejected</Tag>,
              'Back to the store floor. Missing its charger.',
            ],
            ['DS10292603', <Tag tone="green">Accepted</Tag>, 'Appraisal'],
          ]}
        />
      </Columns>
    </>
  )
}

function ItemCardPanel() {
  return (
    <>
      <PanelHead
        title="Turn the photo into an item card"
        by={
          <>
            <By who="person">Staff</By>
            <By who="ai">AI</By>
          </>
        }
      />
      <Columns>
        <div>
          <div className="mb-4 grid aspect-[4/3] max-w-[22rem] place-items-center bg-[#e6e6e6]">
            <FleeceDrawing />
          </div>
          <Heading4>Staff notes</Heading4>
          <KeyValues
            className="max-w-[22rem]"
            rows={[
              ['Condition', 'Pre-owned'],
              ['Department', "Men's"],
              ['Size', 'M'],
              ['Size type', 'Regular'],
            ]}
          />
        </div>
        <div>
          <Heading4>Item card</Heading4>
          <ShownField label="Category" value="Branded apparel, jackets" />
          <ShownField label="Brand" value="Patagonia" />
          <ShownField label="Product" value="Better Sweater quarter-zip fleece" />
          <ShownField label="Color" value="Gray" />
          <ShownField label="Material" value="Polyester fleece" />
          <ShownField label="Search query" value="patagonia better sweater 1/4 zip mens M" />
          <Note>
            Drafted by the vision model, which was sure of the brand. Staff confirmed the color and
            material, and can change anything before the search runs.
          </Note>
        </div>
      </Columns>
    </>
  )
}

// A drawn fleece instead of a photo, so the page uses no stock or real item photos.
function FleeceDrawing() {
  return (
    <svg
      viewBox="0 0 120 110"
      aria-hidden="true"
      fill="none"
      stroke="#3d4551"
      strokeWidth="2"
      strokeLinejoin="round"
      className="h-auto w-[70%]"
    >
      <path d="M42 8 60 18 78 8l26 12 12 40-16 6-6-20v58H26V46l-6 20-16-6L16 20z" fill="#c9cdd2" />
      <path d="M60 18v34M52 13l8 12 8-12" />
      <path d="M56 30h8" strokeWidth="3" />
      <path d="M36 56h14v10H36z" fill="#dfe1e2" />
    </svg>
  )
}

function PricePanel() {
  const comps: [string, string][] = [
    ["Patagonia Better Sweater 1/4 Zip Fleece Men's M Gray", '$54.99'],
    ['Patagonia Mens Better Sweater Pullover Medium', '$49.00'],
    ['Patagonia Better Sweater Quarter Zip Fleece M', '$59.95'],
  ]
  return (
    <>
      <PanelHead
        title="Price it and decide"
        by={
          <>
            <By who="code">Code</By>
            <By who="ai">AI</By>
            <By who="person">Staff</By>
          </>
        }
      />
      <Columns>
        <div>
          <dl className="grid grid-cols-3 tabular-nums">
            <div>
              <dt className="text-[0.8125rem] text-muted-foreground">Low</dt>
              <dd className="text-[1.35rem] font-bold">$31</dd>
            </div>
            <div className="text-center">
              <dt className="text-[0.8125rem] text-muted-foreground">Typical</dt>
              <dd className="text-[2rem] leading-[1.2] font-bold">$36</dd>
            </div>
            <div className="text-right">
              <dt className="text-[0.8125rem] text-muted-foreground">High</dt>
              <dd className="text-[1.35rem] font-bold">$43</dd>
            </div>
          </dl>
          <div
            aria-hidden="true"
            className="relative mt-1.5 mb-[1.1rem] h-[1.1rem] before:absolute before:inset-x-0 before:top-1/2 before:-mt-px before:h-0.5 before:bg-foreground before:content-['']"
          >
            <i className="absolute top-0 left-0 h-full w-0.5 bg-foreground" />
            <i className="absolute top-0 left-[42%] -ml-0.5 h-full w-1 bg-foreground" />
            <i className="absolute top-0 right-0 h-full w-0.5 bg-foreground" />
          </div>
          <div className="mb-4 border-l-[5px] border-yes bg-yes-soft px-3.5 py-2.5 text-[0.9375rem] text-yes-ink">
            <b className="block">Worth listing, high confidence</b>
            The typical sale price is at least $30, and about $29.20 is left after eBay fees and
            supplies.
          </div>
          <AiText source="Written by the language model. Code checked every number against the computed facts.">
            12 similar listings put the typical sale price at $36, which clears the $30 bar. After
            eBay fees and supplies, about $29.20 would be left.
          </AiText>
        </div>
        <div>
          <table className="mb-4 w-full table-fixed border-collapse text-sm">
            <caption className="pb-1.5 text-left text-sm font-bold">
              Similar listings, asking price (3 of 12)
            </caption>
            <tbody>
              {comps.map(([title, price]) => (
                <tr key={title}>
                  <td className="truncate border-t border-rule py-2 pr-3">{title}</td>
                  <td className="w-[5.5rem] border-t border-rule py-2 text-right tabular-nums">
                    {price}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Note className="-mt-2 mb-4">
            Expected sale prices are asking prices times 0.645, an assumption from Poshmark data.
          </Note>
          <div className="flex flex-wrap gap-3" aria-hidden="true">
            <ShownButton className="min-h-11 flex-1 justify-center px-5 py-3 text-base">
              List it
            </ShownButton>
            <ShownButton outline className="min-h-11 flex-1 justify-center px-5 py-3 text-base">
              Don't list
            </ShownButton>
          </div>
        </div>
      </Columns>
    </>
  )
}

function DraftPanel() {
  return (
    <>
      <PanelHead
        title="Draft the listings and approve them"
        by={
          <>
            <By who="ai">AI</By>
            <By who="code">Code</By>
            <By who="person">Manager</By>
          </>
        }
      />
      <Columns wideLeft>
        <div>
          <Heading4>Channel A draft</Heading4>
          <div className="mb-3 border border-input px-3 py-2.5 text-[0.9375rem]">
            <b className="mb-1 block">
              Patagonia Better Sweater 1/4 Zip Fleece Pullover Men's M Gray
            </b>
            Patagonia Better Sweater quarter-zip fleece in men's medium, gray polyester. Pre-owned.
          </div>
          <Heading4>Item specifics, with brand, color and material from the card</Heading4>
          <KeyValues
            className="mb-4"
            rows={[
              ['Department', "Men's"],
              ['Type', 'Pullover'],
              ['Style', 'Quarter zip'],
              ['Size', 'M, regular'],
            ]}
          />
          <Heading4>Claim check</Heading4>
          <Checks
            items={[
              'No banned words, such as "rare", "authentic" or "antique"',
              'Brand "Patagonia" is on the item card',
              'Size "Men\'s M" and color "Gray" match the staff notes and item card',
              'Condition "Pre-owned" matches the staff notes',
              "Title is 61 of Channel A's 80 characters",
            ]}
          />
        </div>
        <div>
          <Heading4>Shops</Heading4>
          <AiText className="text-sm" source="Reason written by the language model.">
            Apparel can go on both shops, and a branded fleece suits either one.
          </AiText>
          <KeyValues
            className="mb-4 text-[0.9375rem]"
            rows={[
              ['Channel A', '$36.00'],
              ['Channel B', '$36.00'],
              ['Timing', 'List now'],
              ['Weight', '1 lb 2 oz'],
              ['Box size', '12x12'],
            ]}
          />
          <Note className="mt-0 mb-3">
            Channel A can't be approved without a weight and box size, so the manager enters both
            here. The shelf comes after approval.
          </Note>
          <ShownButton>Approve listings</ShownButton>
        </div>
      </Columns>
    </>
  )
}

function ShelvePanel() {
  return (
    <>
      <PanelHead
        title="Shelve it"
        by={
          <>
            <By who="person">Manager</By>
            <By who="code">Code</By>
          </>
        }
      />
      <Columns>
        <KeyValues
          className="self-start text-[0.9375rem]"
          rows={[
            ['Shelf or bin', 'C3'],
            ['SKU', 'DS10292603 12x12'],
            ['Status', <Tag tone="blue">Listed</Tag>],
          ]}
        />
        <MiniTable
          caption="Shelf C3, 12x12 boxes, in listing order"
          head={['SKU', 'Listed']}
          numeric={[0]}
          rows={[
            ['RT10212605 12x12', 'Oct 21'],
            ['DS10272601 12x12', 'Oct 27'],
            ['DS10292603 12x12', 'Oct 29'],
          ]}
        />
      </Columns>
    </>
  )
}

function SoldPanel() {
  return (
    <>
      <PanelHead
        title="Sold on one shop, ended on the other"
        by={
          <>
            <By who="code">Code</By>
            <By who="ai">AI</By>
            <By who="person">Staff</By>
          </>
        }
      />
      <Columns wideLeft>
        <MiniTable
          caption="Sync log for DS10292603"
          head={['Time', 'What happened']}
          numeric={[0]}
          rows={[
            ['2:14:05 pm', 'Sale notice from Channel B, $36.00'],
            ['2:14:05 pm', 'Marked sold'],
            ['2:14:06 pm', 'Listing ended on Channel A'],
            ['2:14:06 pm', 'Added to the pick list: box section 12x12, shelf C3'],
          ]}
        />
        <div className="border-4 border-warn px-4 py-3.5">
          <h4 className="mb-1.5 text-base font-bold">Needs Attention: stale listing</h4>
          <p className="mb-2.5 text-[0.9375rem]">
            Channel A still shows DS10272604 as available, but it sold on Channel B on Oct 27.
          </p>
          <AiText
            className="mb-3 text-sm"
            source="Explained by the language model. The check itself is code."
          >
            Channel A was offline when the app tried to end this listing, and both retries failed.
            Ending it now stops a second buyer from ordering it.
          </AiText>
          <ShownButton>End the Channel A listing</ShownButton>
        </div>
      </Columns>
    </>
  )
}

function SalesPanel() {
  return (
    <>
      <PanelHead
        title="See how things sell"
        by={
          <>
            <span className="inline-block bg-foreground px-2 py-px text-[0.8125rem] font-semibold text-background">
              Synthetic data
            </span>
            <By who="person">Manager</By>
          </>
        }
      />
      <Columns>
        <div>
          <p className="mb-3 bg-muted px-3 py-2.5 text-[0.9375rem]">
            Which category sells fastest in December?
          </p>
          <AiText source="Answer written by the language model from these numbers. Query: median_days_to_sell, by category, month 12.">
            In the synthetic history, branded apparel sold in a median of 9 days in December, and
            electronics and video games in 14.
          </AiText>
        </div>
        <div>
          <Heading4>Manager views</Heading4>
          <Checks
            className="text-[0.9375rem]"
            items={[
              'Time to sell, by category and price band',
              'Seasonality, by category and month',
              'Triage funnel, from sent to sold',
              'Sync health and how often staff overrode the recommendation',
            ]}
          />
          <Note>
            The sales history is simulated for the demo, so these views show what the tool can do,
            not what sells.
          </Note>
        </div>
      </Columns>
    </>
  )
}
