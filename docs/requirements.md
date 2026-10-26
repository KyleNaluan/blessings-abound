# Requirements

This page lists what the team is building, who it is for, and what has to work for judging on Nov 9.
Every requirement links to the GitHub issue that tracks it, and the issue holds the detail.

## Purpose and status

This is a living document, not a fixed contract.
Blessings Abound has not answered the team's client questions yet, and the deadline does not leave room to wait for them, so the team builds now on the guesses listed under [Assumptions](#assumptions).
A change to this page comes from one of three things: a client answer that settles an assumption, a Verify check that changes what is possible, or a team decision recorded in the decisions log in [architecture.md](architecture.md#decisions-log).
Update this page in the same pull request as the change it describes, and close or rewrite the assumption that the change settles.

The stack and the pricing pipeline are described in [architecture.md](architecture.md), and this page does not repeat them.

## Users and roles

The primary users are staff and volunteers who sort donations and create listings.
The secondary users are managers who want to see what is listed where.

Accounts are invite-only, so there is no public sign-up.
A setup script seeds the first admin, and seeded demo staff and demo admin accounts exist for judging.
Every person signs in with a username that an admin creates, and an email address is optional.
A person without email cannot reset their own password, so an admin issues a temporary password, and the first sign-in with it requires choosing a new one.
Accounts are deactivated rather than deleted, and a deactivated person's past appraisals stay.

Each role can do everything the role to its left can do.

| Permission | Staff | Manager | Admin |
| --- | --- | --- | --- |
| Appraise items, edit the item card and make the yes/no call | Yes | Yes | Yes |
| Write draft listings | Yes | Yes | Yes |
| See the store's items | Yes | Yes | Yes |
| Approve listings and publish them to channels | No | Yes | Yes |
| Override a staff decision | No | Yes | Yes |
| Set the per-category price cutoffs | No | Yes | Yes |
| View the dashboard and every decision | No | Yes | Yes |
| Add or deactivate staff | No | Yes | Yes |
| Manage managers and admins | No | No | Yes |
| Manage channel connections, such as eBay and Shopify keys | No | No | Yes |
| Change app settings | No | No | Yes |

Only the staff path is in the MVP, so the manager permissions can come after the walking skeleton.
Scoping people to one of Blessings Abound's three stores is out for now, so every account sees the same items.

## Requirements by tier

The MVP is the floor if time runs short, Target is the real goal, and Stretch is built only if time and the Verify checks allow.
The MVP covers two categories, branded apparel and electronics and video games, on one database.

### MVP, due Nov 1

| Requirement | Issue | Done when |
| --- | --- | --- |
| Walking skeleton from photo to saved decision, with placeholders that later issues replace | [#30](https://github.com/KyleNaluan/blessings-abound/issues/30) | A photo taken on a phone-sized screen goes through upload, item card, price and decision, and the decision shows up in the recent decisions list. |
| Item and decision tables | [#8](https://github.com/KyleNaluan/blessings-abound/issues/8) | The migration runs on a fresh database, with money in integer cents and times in UTC. |
| Photo upload and storage | [#9](https://github.com/KyleNaluan/blessings-abound/issues/9) | Upload returns the item ID, and bad file types and oversized files get a clear error. |
| Photo and notes to an editable item card | [#10](https://github.com/KyleNaluan/blessings-abound/issues/10) | The response matches the item card schema, and tests use a stubbed model response. |
| Live market lookup with SerpApi and a response cache | [#14](https://github.com/KyleNaluan/blessings-abound/issues/14) | Cached responses are reused, and tests run only on committed fixtures. |
| Comp relevance filter | [#12](https://github.com/KyleNaluan/blessings-abound/issues/12) | Each dropped comp has a reason, with unit tests on real listing titles. |
| Price range and confidence from comps | [#15](https://github.com/KyleNaluan/blessings-abound/issues/15) | The rule matches architecture.md, with tests for no, few and many comps. |
| Worth-listing rule with per-category cutoffs | [#16](https://github.com/KyleNaluan/blessings-abound/issues/16) | Fees, supplies and cutoffs live in config with a reason each, with tests for yes, no and check. |
| Appraisal screen | [#17](https://github.com/KyleNaluan/blessings-abound/issues/17) | It works on a phone-sized screen and a desktop, with loading and error states for each step. |
| Save every decision, including no | [#18](https://github.com/KyleNaluan/blessings-abound/issues/18) | Yes and no decisions are both stored, and a list endpoint returns recent ones. |
| Evaluation set and scoring script | [#11](https://github.com/KyleNaluan/blessings-abound/issues/11) | The script reports the in-range rate and median error for the pipeline and the raw-median baseline. |

### Target, due Nov 6

| Requirement | Issue | Done when |
| --- | --- | --- |
| Draft the listing with a language model, which staff edit and approve | [#19](https://github.com/KyleNaluan/blessings-abound/issues/19) | Draft, edit and approve work end to end, and the numeric guard rejects a draft with an invented number. |
| Suggest eBay or Shopify for each item, with a one-line reason | [#20](https://github.com/KyleNaluan/blessings-abound/issues/20) | The rule behind it is documented and shown on the item screen. |
| Mock publish and sync with simulated sales | [#21](https://github.com/KyleNaluan/blessings-abound/issues/21) | A sold item disappears from every other mock channel, and a double sale is handled. |
| Invite-only accounts and roles | [#31](https://github.com/KyleNaluan/blessings-abound/issues/31) | Public sign-up fails, roles are enforced in the API and in row-level security, and deactivated accounts cannot sign in. |
| Sign-in and Team pages | [#32](https://github.com/KyleNaluan/blessings-abound/issues/32) | Sign-in, forgot password and the first sign-in password change work, and only admins reach the Team page. |
| Landing page | [#33](https://github.com/KyleNaluan/blessings-abound/issues/33) | Sign in is the only call to action, and the page works on a phone-sized screen and a desktop. |
| Deploy the demo | [#22](https://github.com/KyleNaluan/blessings-abound/issues/22) | The demo URL works from a phone, and the steps are in README.md. |

### Stretch, no due date

| Requirement | Issue | Done when |
| --- | --- | --- |
| Real publish and sync on the eBay sandbox and a Shopify development store, if the Verify checks show it is possible | [#26](https://github.com/KyleNaluan/blessings-abound/issues/26) | A real sandbox sale delists the item on the other channel. |
| Dashboard of items by status, decisions and channel mix for managers | [#27](https://github.com/KyleNaluan/blessings-abound/issues/27) | A dashboard page shows the three views. |

## Out of scope

- Books and home decor, which leave the two MVP categories above.
- Deciding whether an item sells in store or online, because items listed online are not also on the store floor, so sync runs only between online sites.
- Payments.
- Scoping accounts to one of the three stores.
- Client data of any kind, since the project uses only public or self-generated data and stores no personal data beyond item photos, staff decisions and the accounts above.
- A price from the language model, because every price comes from code over comps.

## Demo requirements for judging

The deliverables are due Nov 9: a research poster, a working demo app, and a reproducible GitHub repository.
Features freeze on Nov 7, and the Poster and demo milestone covers the rest.

- The demo shows one item going from photo to saved decision in under 3 minutes, following a written script, with a backup recording in the shared drive in case the live demo fails ([#24](https://github.com/KyleNaluan/blessings-abound/issues/24)).
- Judges can sign in with the seeded demo staff and demo admin accounts ([#31](https://github.com/KyleNaluan/blessings-abound/issues/31)).
- The deployed demo URL works from a phone ([#22](https://github.com/KyleNaluan/blessings-abound/issues/22)).
- The 48 by 36 inch landscape poster covers the problem, the approach, the pricing results against the baseline, and demo screenshots, with a draft by Nov 7 and the final PDF by Nov 9 at 11:59 PM CT ([#23](https://github.com/KyleNaluan/blessings-abound/issues/23)).
- A team member follows README.md from a fresh clone on a different computer and fixes whatever does not work ([#25](https://github.com/KyleNaluan/blessings-abound/issues/25)).
- Everything shown stays honest about being a proof of concept, with no invented endorsements, numbers or partnerships.

## Assumptions

Each assumption is a guess the team made in order to keep building, and the client question named with it would confirm or change it.

1. **The MVP prices two categories, branded apparel and electronics and video games.**
   The team brief set them for the MVP, and the client's own category mix is unknown.
   Settled by the request for an anonymized export of 20 to 50 item records and the category list, and by "Which items get chosen for online?"
2. **One item record is one unique item.**
   The tables in #8 assume this, because one photo maps to one appraisal and one decision.
   Settled by "Is each record one unique item, or can one record cover several of the same item?"
3. **The worth-listing cutoff is a net of $15 for every category until the team sets real ones.**
   The $15 is a placeholder in config, and a dated snapshot of the store's public eBay listings serves as a sanity check.
   Settled by "Which items get chosen for online, and is there a value threshold?"
4. **Prices come from active eBay listings, not sold prices or the store's own price tags.**
   Free sold-price data is not available, and the store's pricing method is unknown.
   Settled by "How are prices set: fixed tag prices, Google Lens lookups, or judgment?"
5. **eBay and Shopify are the two channels.**
   The brief names them, and both have free test environments that the Verify checks cover.
   Settled by "Which accounts exist today (eBay, Etsy, Shopify), and would he let us connect a test or real account?"
6. **Delisting happens as soon as the mock channel reports a sale.**
   The team has no required delay to design for, so the mock delists on the simulated sale event.
   Settled by "When an item sells on one site, how fast must it come down from the others?" and "What exactly is the eBay penalty?"
7. **The channel suggestion is a documented rule over the item card, not a model trained on the store's sales.**
   The team has no sales history to learn from.
   Settled by "Can he share past eBay and Etsy sales reports, anonymized?"
8. **Some staff and volunteers have no email address.**
   That is why sign-in uses a username and admins issue temporary passwords, which also works for people who do have email.
   No client question covers this yet, so it is listed under open questions.
9. **One staff member photographs, appraises and decides in a single sitting.**
   The appraisal screen in #17 is built as one flow on a phone or a desktop.
   Settled by "Roughly how long does one listing take today, from photo to live, and who does it?" and "What statuses does an item go through from donation to sale or disposal?"
10. **Success means the demo works end to end and the pricing beats the raw-median baseline on the evaluation set.**
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
- Who creates the eBay developer, Shopify Partner and SerpApi accounts ([#6](https://github.com/KyleNaluan/blessings-abound/issues/6)), which the stretch tier depends on.
- Whether the eBay sandbox and a Shopify development store can create a listing and detect a sale ([#2](https://github.com/KyleNaluan/blessings-abound/issues/2), [#3](https://github.com/KyleNaluan/blessings-abound/issues/3)), which decides whether #26 is built.
- Whether SerpApi's eBay search returns usable prices for both categories ([#4](https://github.com/KyleNaluan/blessings-abound/issues/4)).
- Which vision model provider the app uses ([#7](https://github.com/KyleNaluan/blessings-abound/issues/7)).
- The real per-category cutoffs, which managers set once the team has them.
- The landing page and account page design, which waits on the landing page direction being picked ([#33](https://github.com/KyleNaluan/blessings-abound/issues/33)).
- Issues #31 and #32 still describe sign-in by email, and #22 still names Vercel, so their text should follow the username sign-in above and the Cloudflare Pages hosting in architecture.md.
