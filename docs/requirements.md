# Requirements

This page lists what the team is building, who it is for, and what has to work for judging on Nov 9.
The product is Turnstone, a staff web app for Blessings Abound, a Kansas City nonprofit thrift store chain, that follows a donated item from intake to sale.
Every requirement links to the GitHub issue that tracks it, and the issue holds the detail.

## Purpose and status

This is a living document, not a fixed contract.
Blessings Abound has answered only a short Q&A and not the team's follow-up questions, and the deadline does not leave room to wait for them, so the team builds now on the guesses listed under [Assumptions](#assumptions).
A change to this page comes from one of three things: a client answer that settles an assumption, a Verify check that changes what is possible, or a team decision recorded in the decisions log in [architecture.md](architecture.md#decisions-log).
Update this page in the same pull request as the change it describes, and close or rewrite the assumption that the change settles.

The stack and the pricing pipeline are described in [architecture.md](architecture.md), and this page does not repeat them.

## Users and roles

The primary users are staff and volunteers who sort donations, create item cards and drafts, and record decisions.
The secondary users are managers, who approve every listing, set prices and channels, assign box size and location, and run Settings and the dashboards.

Accounts are invite-only, so there is no public sign-up.
A setup script seeds the first manager, username `manager1`, and seeded demo staff and demo manager accounts exist for judging.
Every person signs in with a username that a manager creates, and an email address is optional.
A person without email cannot reset their own password, so a manager issues a temporary password, and the first sign-in with it requires choosing a new one.
Accounts are deactivated rather than deleted, and a deactivated person's past appraisals stay.

A manager can do everything staff can do.

| Permission | Staff | Manager |
| --- | --- | --- |
| Run intake and record the triage outcome | Yes | Yes |
| Appraise items, edit the item card and make the yes/no call | Yes | Yes |
| Write and edit draft listings | Yes | Yes |
| Fix Needs Attention items | Yes | Yes |
| See the store's items | Yes | Yes |
| Approve listings and publish them to channels | No | Yes |
| Set prices and channels, including a per-channel price override | No | Yes |
| Assign weight, box size and shelf or bin location | No | Yes |
| Override a staff decision | No | Yes |
| Change Settings, such as box sizes, the seasonal calendar, cutoffs and fees | No | Yes |
| View the dashboards, the insight chat and every decision | No | Yes |
| Add, deactivate and reactivate accounts, change roles and issue temporary passwords | No | Yes |

Only the staff path is in the MVP, from intake through the saved decision, so the manager permissions can come after the walking skeleton.
Scoping people to one of Blessings Abound's three stores is out for now, so every account sees the same items.

## Requirements by tier

The MVP is the floor if time runs short, Target is the real goal, and Stretch is built only if time allows.
The demo covers two categories, branded apparel and electronics and video games, two roles and two mock channels, on one database.
If the team falls behind, the timing hint goes first, then the number of dashboard views and chat functions, keeping at least two views and a handful of functions.

### MVP, due Nov 1

| Requirement | Issue | Done when |
| --- | --- | --- |
| Walking skeleton from photo to saved decision, with placeholders that later issues replace | [#30](https://github.com/KyleNaluan/blessings-abound/issues/30) | A photo taken on a phone-sized screen goes through upload, item card, price and decision, and the decision shows up in the recent decisions list. |
| Item and decision tables, the start of the plan's data model | [#8](https://github.com/KyleNaluan/blessings-abound/issues/8) | The migration runs on a fresh database, with money in integer cents and times in UTC. |
| Intake with a SKU, triage log and duplicate guard | [#37](https://github.com/KyleNaluan/blessings-abound/issues/37) | Every forwarded item gets a SKU and a triage log row, and a previously rejected photo is flagged. |
| Photo upload and storage, 1 required photo and up to 4 | [#9](https://github.com/KyleNaluan/blessings-abound/issues/9) | Upload returns the item ID and SKU, and bad file types and oversized files get a clear error. |
| Photo blur and brightness check | [#38](https://github.com/KyleNaluan/blessings-abound/issues/38) | A blurry or badly lit photo prompts a retake, with no model call. |
| Photo and staff entries to an editable item card | [#10](https://github.com/KyleNaluan/blessings-abound/issues/10) | The response matches the item card schema, low brand or model confidence needs staff confirmation before searching, and tests use a stubbed model response. |
| Live market lookup with SerpApi and a response cache | [#14](https://github.com/KyleNaluan/blessings-abound/issues/14) | Cached responses are reused, and tests run only on committed fixtures. |
| Comp relevance filter | [#12](https://github.com/KyleNaluan/blessings-abound/issues/12) | Each dropped comp has a reason, with unit tests on real listing titles, including bundles and modded items. |
| Price range and confidence from comps | [#15](https://github.com/KyleNaluan/blessings-abound/issues/15) | The rule matches architecture.md, with tests for no, few and many comps. |
| Worth-listing rule: yes when the typical sale price is at least $30, with the net after fees shown beside it | [#16](https://github.com/KyleNaluan/blessings-abound/issues/16) | The threshold, fees and supplies live in config with a reason each, with tests for yes, no and check. |
| Appraisal screen | [#17](https://github.com/KyleNaluan/blessings-abound/issues/17) | It works on a phone-sized screen and a desktop, with loading and error states for each step, and a disagreement needs a reason. |
| Save every decision, including no | [#18](https://github.com/KyleNaluan/blessings-abound/issues/18) | Yes and no decisions are both stored with any override reason, a rejection writes its destination to the triage log, and a list endpoint returns recent ones. |
| Evaluation set and scoring script | [#11](https://github.com/KyleNaluan/blessings-abound/issues/11) | The script reports the in-range rate and median error against independent sold prices, for the pipeline and the raw asking prices. |
| Vision accuracy evaluation | [#39](https://github.com/KyleNaluan/blessings-abound/issues/39) | Brand, category and product accuracy are reported on about 50 hand-labeled photos. |
| Rename the app to Turnstone in code | [#40](https://github.com/KyleNaluan/blessings-abound/issues/40) | The old name no longer appears anywhere in the repo. |

### Target, due Nov 6

| Requirement | Issue | Done when |
| --- | --- | --- |
| Draft the listing per channel with a language model and a rule-based claim checker | [#19](https://github.com/KyleNaluan/blessings-abound/issues/19) | At least 90% of first drafts pass with no unsupported claims, and a flagged draft uses a fixed template. |
| Recommend Channel A or Channel B and a list now or hold hint for each item | [#20](https://github.com/KyleNaluan/blessings-abound/issues/20) | Category rules decide the eligible channels, a one-line reason is shown, and staff choose. |
| Manager approval, storage location and pick list | [#42](https://github.com/KyleNaluan/blessings-abound/issues/42) | Channel A cannot be approved without weight and box size, and a sold item appears on a pick list sorted by box section and shelf. |
| Publish and sync on two mock channels | [#21](https://github.com/KyleNaluan/blessings-abound/issues/21) | A sold item comes down from the other channel within seconds, a missed webhook is caught by polling, and the demo run shows zero oversold items. |
| Needs Attention checks | [#43](https://github.com/KyleNaluan/blessings-abound/issues/43) | Every planted stale-status, unknown-listing and double-sale conflict is flagged, and a planted double sale is fixed in one click. |
| Settings page | [#41](https://github.com/KyleNaluan/blessings-abound/issues/41) | Managers can change box sizes, the seasonal calendar, cutoffs, fees and the ask-to-sale factor. |
| Sales insight dashboards | [#27](https://github.com/KyleNaluan/blessings-abound/issues/27) | The four views work: time to sell, seasonality, triage funnel, and sync health and agreement, with every chart labeled "synthetic". |
| Synthetic sales data generator | [#44](https://github.com/KyleNaluan/blessings-abound/issues/44) | About 600 items over 12 months come from a fixed seed, within about 25% of each calibration target. |
| Insight chat with fixed query functions | [#45](https://github.com/KyleNaluan/blessings-abound/issues/45) | Numbers come from tested functions in code, and every answer shows the query it came from. |
| Invite-only accounts and roles | [#31](https://github.com/KyleNaluan/blessings-abound/issues/31) | Public sign-up fails, the two roles are enforced in the API, row-level security blocks all other access, and deactivated accounts cannot sign in. |
| Sign-in and Team pages | [#32](https://github.com/KyleNaluan/blessings-abound/issues/32) | Sign-in with a username or email, forgot password and the first sign-in password change work, and only managers reach the Team page. |
| Landing page | [#33](https://github.com/KyleNaluan/blessings-abound/issues/33) | Sign in is the only call to action, and the page works on a phone-sized screen and a desktop. |
| Deploy the demo | [#22](https://github.com/KyleNaluan/blessings-abound/issues/22) | The demo URL works from a phone, and the steps are in README.md. |

### Stretch, no due date

These two have no issue yet, and each gets one if the team picks it up.

| Requirement | Done when |
| --- | --- |
| Free-form text-to-SQL for the insight chat | A manager's free-form question returns numbers that can be checked against the query shown. |
| Re-measure the ask-to-sale factor on eBay by hand | About 25 to 30 pairs of active and sold medians are recorded, in roughly 2 to 3 hours of work. |

## Success measures

- Median time to an approved listing falls by at least 30% against a baseline timed on the same items done by hand.
- At least 90% of first drafts contain no unsupported claims, checked by the rule-based claim checker and a hand review of a sample.
- Every planted stale-status or double-sale conflict is caught on the Needs Attention screen.
- The demo run shows zero oversold items, against the 12 cancelled orders from double listing in a year (1.6% of sales) that the client reported.

## Out of scope

- Books and home decor, which leave the two categories above.
- In-store sales and in-store versus online profitability, because an item is either online or not, and every item is one of a kind with no quantities or sets.
- Real channel connections, so no real eBay or Shopify connection is attempted.
- Order-risk reports by buyer ZIP code or username, which are left out on purpose because they would profile buyers through proxies and carry no valid signal.
- Payments.
- Scoping accounts to one of the three stores.
- Client data, since the project uses only public or self-generated data apart from the thresholds in the client's short Q&A, and stores no personal data beyond item photos, staff decisions and the accounts above.
- A price from the language model, because every price comes from code over comps.

## Demo requirements for judging

The deliverables are due Nov 9: a research poster, a hosted working demo, and a reproducible GitHub repository.
Features freeze on Nov 7, and the Poster and demo milestone covers the rest.

- The demo shows one item going from photo to saved decision in under 3 minutes, following a written script, with a backup recording in the shared drive in case the live demo fails and a rehearsed offline `docker compose` run ([#24](https://github.com/KyleNaluan/blessings-abound/issues/24)).
- Judges can sign in with the seeded demo staff and demo manager accounts ([#31](https://github.com/KyleNaluan/blessings-abound/issues/31)).
- The deployed demo URL works from a phone ([#22](https://github.com/KyleNaluan/blessings-abound/issues/22)).
- The 48 by 36 inch landscape poster covers the problem, the approach, the results against the baseline, the limitations, the fairness choice and demo screenshots, with a draft by Nov 7 and the final PDF by Nov 9 at 11:59 PM CT ([#23](https://github.com/KyleNaluan/blessings-abound/issues/23)).
- The limitations on the poster are that comps are asking prices, that the 0.645 ask-to-sale factor comes from Poshmark, that the prototype scored 8 items, and that the channels and sales history are mock and synthetic.
- A team member follows README.md from a fresh clone on a different computer and fixes whatever does not work ([#25](https://github.com/KyleNaluan/blessings-abound/issues/25)).
- Everything shown stays honest about being a proof of concept, with no invented endorsements, numbers or partnerships.

## Assumptions

Each assumption is a guess the team made in order to keep building, and the client question named with it would confirm or change it.

1. **The demo prices two categories, branded apparel and electronics and video games.**
   The team brief set them, and the client's own category mix is unknown.
   Settled by the request for an anonymized export of 20 to 50 item records and the category list, and by "Which items get chosen for online?"
2. **One item record is one unique item.**
   The client's items are one of a kind, so one record maps to one item that is either available or sold, and there are no quantities or sets.
   Settled by "Is each record one unique item, or can one record cover several of the same item?"
3. **An item is worth listing when its typical sale price is at least $30, with the net after fees shown beside it.**
   The $30 is sourced from the client's Q&A, not from their data, so it stays in config, and it replaces the earlier $15 net placeholder.
   Settled by "Which items get chosen for online, and is there a value threshold?"
4. **Prices come from active eBay listings, not sold prices or the store's own price tags.**
   Free sold-price data is not available, and the store's pricing method is unknown.
   Settled by "How are prices set: fixed tag prices, Google Lens lookups, or judgment?"
5. **Two fictional mock channels are enough to show publishing and sync.**
   Channel A is eBay-style and takes both categories, and Channel B is Depop or Poshmark-style and takes apparel only, which gives one case of platform fit and one of sync.
   The app reaches each through an adapter interface, so a real channel could replace a mock later.
   Settled by "Which accounts exist today (eBay, Etsy, Shopify), and would he let us connect a test or real account?"
6. **Delisting within seconds of a sale is fast enough.**
   A sale webhook reaches the app within seconds, a polling job catches a missed webhook, and failed channel updates retry from the `jobs` table.
   No system can fully prevent two people buying the same item in the same second, so the goal is to shrink that window and flag the rest on Needs Attention.
   Settled by "When an item sells on one site, how fast must it come down from the others?" and "What exactly is the eBay penalty?"
7. **The channel and timing recommendation comes from category rules and a seasonal calendar, not a model trained on the store's sales.**
   The team has no sales history to learn from, so a language model only writes the one-line reason.
   The dashboards use a synthetic history for the same reason, so they show the capability and not a finding.
   Settled by "Can he share past eBay and Etsy sales reports, anonymized?"
8. **Some staff and volunteers have no email address.**
   That is why sign-in uses a username and managers issue temporary passwords, which also works for people who do have email.
   No client question covers this yet, so it is listed under open questions.
9. **One staff member photographs, appraises and decides in a single sitting, and a manager approves and stores the item later.**
   The appraisal screen in #17 is built as one flow on a phone or a desktop up to the decision, and approval, box size and location are a separate manager step.
   Settled by "Roughly how long does one listing take today, from photo to live, and who does it?" and "What statuses does an item go through from donation to sale or disposal?"
10. **Success means the measures listed under [Success measures](#success-measures), and pricing that beats raw asking prices on the evaluation set.**
    The team has no client measure of success, so it uses its own.
    Settled by "What would make him call this a success?"
11. **The demo and poster use team-photographed items and openly licensed photos, not the store's photos.**
    The team has no permission to use the store's photos.
    Settled by "Can we use photos of their items on the poster, and what must stay confidential?"
12. **The app only needs to run for the demo, so free tiers are enough.**
    The brief limits the project to free tools, and the hosting in architecture.md uses free plans.
    Settled by "After the hackathon, would anyone actually run this, and is there any budget for hosting or paid tools?"

## Open questions

- Whether the client's volunteers have email addresses, which decides how much the username and temporary-password path matters.
- Who creates the Render, Cloudflare, Supabase, Groq, Gemini and SerpApi accounts ([#6](https://github.com/KyleNaluan/blessings-abound/issues/6)).
- Whether SerpApi's eBay search returns usable prices for both categories ([#4](https://github.com/KyleNaluan/blessings-abound/issues/4)).
- Whether Groq's vision model is fast enough and returns strict JSON, which is still untested, with Gemini as the fallback ([#7](https://github.com/KyleNaluan/blessings-abound/issues/7)).
- What goes in the seasonal calendar table and the standard box sizes list ([#41](https://github.com/KyleNaluan/blessings-abound/issues/41)).
- Who owns each workstream.
- Whether the current free-tier terms for Render, Cloudflare Pages and Supabase still fit, and what the AI mentor counts as hosted and when it must be up.
- What the poster outline is.
- Whether the name Turnstone has any trademark or domain conflict, which has not been checked.
