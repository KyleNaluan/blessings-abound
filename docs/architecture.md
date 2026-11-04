# Architecture

This page lists the main technical choices behind Turnstone and why we made them.
Update it in the same pull request whenever one of them changes.

## Stack

| Part | Choice | Why |
| --- | --- | --- |
| Repository | One repo with `api/` and `web/` | One place to clone, review and reproduce, with each part keeping its own dependencies. |
| Backend | FastAPI on Python 3.12 | Python suits the pricing math and the AI calls, and FastAPI generates an OpenAPI schema from the code. |
| Python packages | uv | One fast tool for Python versions, virtual environments and lock files. |
| Frontend | Vite, React and TypeScript | A common, well-documented setup with fast reloads and type checking. |
| Styling | Tailwind and shadcn/ui | Ready-made accessible components that we own as source and can restyle. |
| API client | `openapi-typescript` and `openapi-fetch` | Frontend types come from the API's schema, so a change on one side shows up as a type error on the other. |
| Database | Postgres | One relational database for items, appraisals and decisions, the same engine locally and in the demo. |
| Database access | SQLModel on SQLAlchemy | Table models double as Pydantic models, which keeps the API code short. |
| Schema changes | Alembic | Every schema change is a reviewed, repeatable migration file. |
| Pricing | Active eBay listings from SerpApi, priced by code | Similar listings give a price range we can explain and link to, with no training data to collect, see [Pricing pipeline](#pricing-pipeline). |
| Vision and language model | Groq (qwen) for vision, with Gemini as fallback, through one OpenAI-compatible client | The provider is a setting, `AI_BASE_URL`, `AI_MODEL` and `AI_API_KEY`, with the fallback in the matching `AI_FALLBACK_` settings, so we can switch without code changes, and the same client powers the explanation, drafts and insight chat. Groq allows 1,000 requests and 200,000 tokens a day, which is about 80 items a day, see [Vision model check](#vision-model-check). |
| Auth | Supabase Auth, with a plain UUID login ID, display name and role in `profiles` | The API enforces the two roles, staff and manager, and row-level security blocks all other access. Accounts are invite-only, see [docs/database.md](database.md#accounts). |
| Mock channels | Two separate FastAPI services on Render, each with its own database role and schema, `channel_a` and `channel_b` | They stand in for real platforms behind an adapter interface, and they keep their data in Postgres, so it survives restarts on free hosts. |
| Background work | An in-process scheduler and a `jobs` table in Postgres | It handles polling, retries and AI calls without a separate worker to host. |
| Photo storage | Local folder or Supabase Storage | One interface in `api/app/storage.py`, with the backend picked by settings. |
| Hosting | Cloudflare Pages for the frontend, Render for the API and mock channels, Supabase for the database and photos | Each has a free tier that fits a student demo. |
| Keeping the demo up | A scheduled GitHub Actions ping on our self-hosted runner, and an offline `docker compose` demo with a local stand-in and fixture responses | An idle free service stops polling and can miss webhooks, and the offline demo works with no keys or Wi-Fi. |
| Python tooling | ruff and pyright | Fast lint, format and type checks with little configuration. |
| Frontend tooling | ESLint, Prettier, `tsc` and Vitest | The standard checks for a Vite and React project. |
| Checks | pre-commit hooks and GitHub Actions | The same lint, type checks and tests run on every commit and every pull request. |

## Environments

| | Development and tests | Shared demo |
| --- | --- | --- |
| Database | Postgres 17 in Docker Compose | Supabase Postgres 17 |
| Photo storage | Local folder | Supabase Storage |
| API | `docker compose up` on each laptop | Render, one service today, up to three with the two mock channels |
| Frontend | `npm run dev` on each laptop | Cloudflare Pages |

Development and tests use a local database, so each of us can reset data and run migrations without touching the shared demo or needing a network connection.
CI starts its own Postgres for the same reason.
The demo reads its connection details from environment variables, so the code is the same in both places.

The Cloudflare Pages project `blessings-abound` builds the frontend from `main` with root directory `web`, build command `npm run build` and output directory `dist`, and serves it at https://blessings-abound.pages.dev.
Every pull request gets its own preview link from Pages, and nobody needs a Cloudflare account to open it.
The build uses the Node version in `web/.nvmrc`, and `VITE_API_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are in the Pages project's production environment variables.
The API runs as the free Render service `blessings-abound-api` at https://blessings-abound-api.onrender.com, and the steps are in the [README](../README.md#hosted-demo).
Each site's `/choose-password` address must be in the Supabase Auth redirect list for reset and invite links to work.
Pages serves `index.html` for any path without a file, because the build has no `404.html`, so the app needs no rewrite config.

The hosted demo follows these steps:

- Connect to Supabase with the session pooler on port 5432, which works over IPv4, because the transaction pooler needs prepared statements disabled for psycopg (`prepare_threshold=None`).
- Start each Render service with `alembic upgrade head && uvicorn ...`, which is the command in `api/Dockerfile`, so Supabase receives migrations only after merge.
- Before judging, reset the demo data with a rerunnable seed script, compare the structure with `pg_dump --schema-only`, and back up Supabase the day before.
- Wake Supabase and every Render service before judging, because free Supabase projects pause after about a week of inactivity.

## Pricing pipeline

Each step is a board issue, and so far the item card in step 2 and steps 3 to 9 are built, and `POST /items/{id}/appraisals` runs them through `price_item` in `api/app/pipeline.py`.
The item card in step 2 is read, edited and confirmed by staff, and the SerpApi lookup in step 4 is the active Buy It Now search with its 7 day cache and the drop-a-word fallback.
Steps 5 to 9 are built as pure functions in `api/app/comp_filter.py` and `api/app/pricing.py`, with their numbers in `PricingRules` in `api/app/settings.py`.
Step 10's language model is not built, so the explanation is the code template it falls back to.
The other steps are not built yet.
The language model never produces a price, and every number comes from code over comps, which are similar items for sale on eBay.

1. Staff upload 1 required photo and up to 4, and a code-only blur and brightness check prompts a retake.
   Staff enter the condition grade, using eBay's values, and any flaws, plus the department, size and size type for apparel and shoes, or tested and working, complete-in-box and accessories for electronics and games.
   Those come from staff, never from the model.
2. The vision model turns the photos and staff entries into an item card with the category, brand, product, any visible text, a search query and its own confidence, and it proposes the color, material, exact model and platform for staff to confirm.
   Staff can edit the card before any search is spent, with `PATCH /items/{id}/card`, which also confirms it.
   The appraisal step refuses a card with no brand or with a model confidence below `ITEM_CARD_MIN_CONFIDENCE`, default `medium`, until staff confirm it.
   Any staff entry the model sends back is dropped, and photos go to the model as upright JPEGs at most 960 pixels on the long side.
3. Code builds the eBay search from the card's search query, with condition ids for the card's condition and for whether it is a video game.
   A pre-owned item searches `3000`, or `2750|4000|5000|6000` for a video game, new with tags searches `1000`, and new without tags searches `1500`, or `2750` for a video game.
4. SerpApi's eBay engine returns active Buy It Now listings filtered by condition, and if fewer than 8 survive the filters, code drops the last query word and searches again, at most twice.
5. Code filters the listings by title, dropping accessories, lots, parts and similar matches unless the item itself is one of those.
   Department, tall, plus and petite sizes, and complete in box are judged against the staff entries, a plain size never drops a listing, and each dropped listing keeps its reason.
   A listing returned more than once is dropped by its item id with reason DUPLICATE, so one listing cannot weigh twice in the percentiles.
6. Code trims outliers with Tukey fences on log price, skipped when fewer than 4 listings remain, and takes the low, typical and high price from the percentiles.
   Apparel uses the 25th, 50th and 75th, and games and hardware use the 15th, 50th and 85th.
7. Asking prices run higher than sale prices, so code multiplies the range by an ask-to-sale factor from config, which is one value per category rather than one per channel, because comps always come from eBay.
   Apparel's 0.645 is labeled an assumption, because it comes from Poshmark data with ratios from 1.21 to 2.93, and a re-measure on eBay is a stretch item done by hand.
   The 0.94 for games and hardware is also labeled an assumption, because it comes from 18 items in [evaluation.md](evaluation.md).
8. Confidence is high with at least 10 listings left after the trim and a ratio of at most 2 between the 75th and 25th percentiles, medium with at least 5 and a ratio of at most 3, and low otherwise.
9. The worth-listing rule says "yes" when the typical sale price is at least $30, "no" below it, and "check" when confidence is low or there are no comps, and the threshold, fees and supplies live in config.
   The net after eBay's fees, which are 13.6% for most categories plus $0.40 per order, and $1.50 for supplies is shown beside it.
10. The language model writes a 2 to 3 sentence explanation from the computed numbers only, and code rejects the text if it contains any number that is not in those facts and falls back to a template.

When the budget is spent, the search fails, no key is set or no usable comps remain, the appraisal is still saved, with no prices, confidence low, the recommendation "check" and an explanation that says which of those happened.

Staff see the range, the comps as links, the confidence and the recommendation, and they make the final call, which the app saves.
If they disagree with the recommendation they choose a reason from a dropdown and may add a note, and a rejected item gets a destination, which is the store floor, seasonal storage, or discard or donate onward, written to the triage log.

Comps come through SerpApi rather than eBay's own API, because eBay's API license does not allow using its content to suggest or model prices.
SerpApi's free plan allows 250 searches a month and 50 an hour, so every response is cached in a `comp_searches` table, keyed by the engine, query, condition and buying format, and reused for 7 days.
Tests read committed fixture responses and never call SerpApi.

## Vision model check

Checked on 2026-11-01 with 5 openly licensed Wikimedia Commons photos, each sent twice to both providers through `api/app/vision.py`, which asks for a JSON object and validates it against the item card model.
The photos were an Xbox 360 controller, a Game Boy Color, Levi's 501 jeans, an Air Jordan 4 and a Carhartt jacket, and they were resized to 960 pixels on the long side.

| | Groq `qwen/qwen3.8-27b` | Gemini `gemini-3.5-flash` |
| --- | --- | --- |
| Median latency | 1.1 s | 4.3 s |
| Worst latency | 1.9 s | 8.2 s |
| Valid JSON on the first try | 10 of 10 | 8 of 10, and the other 2 were quota errors (HTTP 429), not bad JSON |

- Neither model needed a retry for a bad parse, so the retry and the fallback to Gemini are covered by stubbed tests only.
- Both models returned valid JSON with `response_format` set to `json_object`, and the schema is described in the prompt instead of being enforced by the provider.
- Groq named the Levi's 501 photo "American Eagle" with high confidence, so a confident brand can still be wrong, and staff confirmation of the brand and model stays necessary.
- Groq's free limits for `qwen/qwen3.8-27b` are 30 requests a minute, 1,000 requests a day, 8,000 tokens a minute and 200,000 tokens a day, from https://console.groq.com/docs/rate-limits.
  One photo costs about 2,300 input tokens, so the per-minute token limit allows about 3 photos a minute and the daily limit about 80 items a day with one photo each.
  Groq answered HTTP 429 once the tokens per minute ran out, so a 429 goes straight to the fallback instead of being retried.
- Gemini's rate limits page lists no free-tier numbers, and says to read them in Google AI Studio, so the free limits are not recorded here.
  Gemini answered HTTP 429 on 2 of 10 photos sent a few seconds apart, so its free quota is tight too.
- `gemini-2.5-flash` returns HTTP 404 for new API keys, and `gemini-3.8-flash` and `gemini-flash-latest` timed out after 40 seconds, so the fallback uses `gemini-3.5-flash`.

## Listing drafts

After a yes decision, `POST /items/{id}/drafts` writes a title, description and category for each channel, `PATCH /items/{id}/drafts/{channel}` saves staff's edits, and `POST /items/{id}/drafts/submit` sends the drafts on to manager approval.
Channel A takes every item and Channel B takes apparel only, which `listing_channels` in `api/app/pipeline.py` decides until #20 lets staff choose the channels.
A draft is stored in `listing_drafts` with the state `draft`, and sending it sets `awaiting_approval`, which is the state the manager screen in #42 reads.

The model is the same pair as the item card, Groq `qwen/qwen3.8-27b` with Gemini `gemini-3.5-flash` as the fallback, through `complete_json` in `api/app/ai.py`.
It asks for a JSON object, retries a bad reply once on the same provider and falls back at once on an HTTP error.
The prompt is `PROMPT` in `api/app/listing_drafts.py`, sent as one user message, and it holds:

- a line on the channel, plain and searchable for Channel A and relaxed for Channel B,
- the facts, which are the card's fields and the staff entries, leaving out anything nobody recorded,
- rules that forbid any brand, number, size, condition, flaw, working or box claim the facts don't support, built per item, so an item tested as working may say so and one with no record may not,
- the banned words, and
- the JSON keys, with the channel's own categories to copy one from.

The rule-based checker in `api/app/claims.py` reads the model's title and description apart, so a "not" in one can't excuse the other, and flags:

- a banned word, such as rare, authentic, antique, vintage, mint or official, unless it is on the card,
- a brand, system or product line the card doesn't name, where a product line counts for its maker, so "Switch" is fine on a Nintendo card,
- a letter size, a size after the word "size", a fit such as slim or oversized, or a department, that the card doesn't give,
- a number or number word that isn't on the card, and
- a condition claim the card or staff entries don't support, such as new, sealed, tested, complete in box or a flaw, where a "not" or "no" up to three words before it in the same clause makes it a statement the card allows, except for grades such as "no flaws".

Words in double quotes that are on the card, such as the text printed on the item, are read as a copy of the card and not as a claim, and the prompt asks the model to quote that text after "It reads".

A flagged draft, or no usable reply from either model, falls back to the fixed template in `template_draft`, which only restates the card, and the stored row keeps the model's draft and its flags so staff can see why.
Staff can edit either one, and the API checks the text again on every read, so the item screen shows the flags as they stand and sending is refused while any remain.
On the 48 evaluation items, which are all games and hardware for Channel A, 46 of the model's drafts passed the checker, 95.8%, measured once on 2026-11-03.
The 2 flagged drafts said "sold as is" and "no record of it being tested", which the card doesn't say either.
[listing-drafts.md](listing-drafts.md) has each draft and the limits of that sample.

## Database

The tables, their constraints and who may reach them are described in [database.md](database.md).

## Decisions log

Add new decisions at the bottom, with the date and a line on why.

- 2026-10-23: Keep a local Postgres for development and tests, and use Supabase only as the shared hosted database for the demo, so local work never changes shared data.
- 2026-10-23: Store money as integer cents and times in UTC, as described in CONTRIBUTING.md.
- 2026-10-23: Generate the web client's types from the API's OpenAPI schema and check in CI that the committed file is current.
- 2026-10-23: Pin TypeScript to 5.9, because `openapi-typescript` does not support TypeScript 6 yet.
- 2026-10-23: Use `httpx2` as the HTTP client, because Starlette's test client deprecated `httpx` in its favor.
- 2026-10-23: Run Postgres 17 locally and in CI, the same major version as the Supabase project, so migrations behave the same everywhere.
- 2026-10-23: Host the frontend on Cloudflare Pages instead of Vercel.
- 2026-10-24: Price items from active eBay comps through SerpApi with the math in code, instead of a model trained on the Mercari dataset, so the API loads no model file and there is no `ml/` project.
- 2026-10-29: Treat items as online-only and one of a kind, with no in-store channel or quantities, because each item is sold in only one place.
- 2026-10-29: Keep the photo-to-price pipeline and drop the live web price search, because comps are traceable and eBay's license bars using its content to suggest prices.
- 2026-10-29: Say yes when the typical sale price is at least $30 and show the net beside it, replacing the $15 net cutoff, because $30 is the client's stated bar.
- 2026-10-29: Keep one ask-to-sale factor of 0.645, labeled an assumption, instead of one per channel, because comps always come from eBay. Games and hardware got their own factor on 2026-11-01, see below.
- 2026-10-29: Attempt no real eBay or Shopify connection, and build Channel A (eBay-style) and Channel B (Depop or Poshmark-style, apparel only) as separate services in separate schemas of one Postgres, which gives one platform-fit case and one sync case and survives restarts on free hosts.
- 2026-10-29: Use Groq for vision with Gemini as fallback, through one OpenAI-compatible client, because both have free limits and the provider stays a setting.
- 2026-10-29: Use a rule-based claim checker on listing drafts, because it is deterministic and measurable against the 90% target.
- 2026-10-29: Run sync as deterministic code with a language model that only explains problems, because that is reliable and testable.
- 2026-10-29: Run the dashboards on a synthetic history from a model calibrated to published figures, labeled on every chart, because no real sales history is available.
- 2026-10-29: Leave out order-risk analyses by ZIP code and username, because they would profile buyers through proxies and carry no valid signal.
- 2026-10-30: Store the Supabase Auth user id in `profiles` as a plain UUID with no foreign key to `auth.users`, and enforce roles in the API, because local Postgres and CI have no `auth` schema and a migration that refers to it would only run on Supabase.
- 2026-10-30: Turn on row-level security with no policies on every table, including `alembic_version`, so Supabase's automatic web API reads nothing and only our API, which connects as the table owner, reaches the data.
- 2026-10-30: Use two roles, staff and manager, as the 2026-10-29 project plan does, instead of the three in `requirements.md` and issue #31.
- 2026-10-30: Store fixed value lists as text with a check constraint rather than Postgres enums, because item statuses and similar lists are expected to change and swapping a constraint is a simpler migration.
- 2026-10-30: Allow `net_after_fees_cents` to go below zero, unlike every other cents column, because fees can exceed the price of a cheap item and hiding that would misstate the net.
- 2026-10-30: Install pyright with the `nodejs` extra so it runs the Node bundled in `nodejs-wheel-binaries`, instead of letting it fetch Node at runtime through nodeenv, which broke CI when a Node pre-release version string nodeenv could not parse became the latest.
- 2026-10-30: Name the product Turnstone, with the rename in code tracked in #40.
- 2026-10-30: Keep usernames, invites and temporary passwords, with optional email, because some volunteers may not have an email address and the project plan does not change that.
- 2026-10-30: Let the browser talk to Supabase only for Auth, using the anon key, and send all table access through the API, with row-level security and no policies blocking the anon role from tables.
- 2026-10-30: Route the web app with React Router, with the landing page at `/`, sign-in pages beside it and the signed-in app under `/app`.
- 2026-10-30: Use the USWDS colors and Public Sans in place of the shadcn defaults and Geist, to match the approved landing and sign-in mockups.
- 2026-10-30: Look up a username's email through `web/src/auth/accounts.ts` only, so issue #31 can back usernames and temporary passwords without changing the pages.
- 2026-11-01: Search the video games category with condition ids `2750|4000|5000|6000` and everything else with `3000`, because `3000` on a game query returned mostly console bundles, see [serpapi-ebay-check.md](serpapi-ebay-check.md).
- 2026-11-01: Use `gemini-3.5-flash` as the fallback model instead of `gemini-2.5-flash`, because Google closed 2.5 to new keys, and retry a bad parse once before falling back, but fall back at once on an HTTP error, because a retry meets the same rate limit.
- 2026-11-01: Build the staff path as one route per step, `POST /items`, `/items/{id}/card`, `/items/{id}/appraisals` and `/items/{id}/decisions`, with the placeholder steps in `api/app/pipeline.py`, so #9, #10, #15, #16 and #37 each replace one function and leave the routes and the screen alone.
- 2026-11-01: Check each request's token by asking Supabase Auth at `/auth/v1/user` rather than verifying the JWT in the API, because it works with both the older shared secret and the newer signing keys and a banned user stops working at once, at the cost of one extra call per request.
- 2026-11-01: Refuse anyone without an active profile, even with a good token, because the profile holds the role and a decision needs someone to point at.
- 2026-11-01: Show staff their own decisions and managers everyone's in the recent decisions list, because `requirements.md` keeps every decision to managers.
- 2026-11-01: Make saving the card with `PATCH /items/{id}/card` the confirmation, with no separate route, because staff have read what they save and one call is all the screen needs.
- 2026-11-01: Treat a card with no brand like one with low confidence, because a search without a brand spends quota on a vague query, and keep one `model_confidence` rather than one for the brand and one for the model, because the schema has one and the prompt defines it over both.
- 2026-11-01: Resize photos with Pillow before the vision call, because the 2,300 tokens per photo in the vision check assumes 960 pixels and a full-size phone photo would hit the provider's limits.
- 2026-11-01: Keep an item `appraised` after a yes and set it to `declined` after a no, because no status means "staff said yes" and `approved` belongs to the manager step.
- 2026-11-01: Add a new `comp_searches` row on every refresh instead of overwriting the cached one, so the rows of the current month are the count of searches spent against `SERPAPI_MONTHLY_BUDGET` (default 240 of the free plan's 250), and the lookup refuses cleanly once that is spent.
- 2026-11-01: Skip a listing that shows a from-to price in `parse_comps` instead of averaging the two ends, because that range spans different variants and no one is asking the midpoint.
- 2026-11-01: Let plain sizes such as 34x32 or Large keep their comps and drop only tall, plus and petite cuts that staff did not enter, because a page of 60 listings spreads across many sizes and matching one exactly would leave too few comps to price.
- 2026-11-01: Tell a game from a console by the card's product and platform, because both share the `electronics_games` category and a console's comps must drop games while a game's comps must drop consoles.
- 2026-11-01: Show the net beside a "check" whenever comps gave a typical price, and leave it empty only with no comps, so staff can still see what a low-confidence item might clear.
- 2026-11-01: Save an appraisal with no price and a "check" when the budget is spent, the search fails or the key is missing, rather than answering with an error, so staff can still make and record a call, and appraising again costs nothing for the searches already cached.
- 2026-11-01: Give no price when a fallback search fails even if an earlier search found a few comps, because a retry reuses the cached searches and a price from a search cut short would look like a finished one.
- 2026-11-01: Search new items with their own condition ids, because the used id `3000` returns only listings the condition filter drops for a new item, which would leave every new item with no price.
- 2026-11-01: Cache a SerpApi response only when its status is `Success`, and turn every search failure into `SerpApiError` with no URL in its message, because a cached failure would last 7 days and the request URL carries the key.
- 2026-11-01: Score pricing against PriceCharting's loose price for games and hardware, with items fixed before the first run, and accept hand-recorded sold prices for apparel, because no other sold-price source we checked could be used, see [evaluation.md](evaluation.md).
- 2026-11-01: Save evaluation cards and slimmed search responses in `api/eval/` and roll back the `comp_searches` rows of a run, so a rerun spends nothing and can't count against the app's budget, and a test fails when the saved results no longer match the code.
- 2026-11-01: Restart a `findBy` or `waitFor` that failed while the test process was frozen, instead of raising its deadline, because the deadline timer runs before the render already due when the process wakes, so a longer freeze beats any limit, and a wait that ran undisturbed still fails at the normal 1s.
- 2026-11-01: End the session before leaving the sign-out button's page, and hold `RequireAuth`'s redirect to sign-in with a signing-out mark on the auth context while the session clears, because the router's low priority navigation to the landing page otherwise loses to that redirect; clear the mark when the protected page unmounts so a later visit while signed out still redirects, and keep a failed sign-out on the page with a visible error rather than swallowing it.
- 2026-11-01: Sign in by username through `POST /auth/sign-in` on the API rather than through a lookup in the browser, which replaces the plan to keep it in `web/src/auth/accounts.ts`, because a lookup the browser can call would hand out anyone's address and tell a stranger which usernames exist.
- 2026-11-01: Find the Auth address from `auth_user_id` at sign-in rather than from `profiles.email`, so local profiles with no email and people with a hidden placeholder address can all use a username.
- 2026-11-01: Keep the sign-in failure count per username, because Auth sees every username sign-in as coming from the API's address. It first lived in the API process and now lives in `sign_in_attempts`, see the later entry.
- 2026-11-01: Store `must_change_password` in `profiles` rather than in Auth's user metadata, because a signed-in person can write their own metadata from the browser and would be able to lift the block on a temporary password.
- 2026-11-01: Change a person's own password by forwarding their token to Auth from `POST /me/password` and clearing the flag in the same request, so Auth still applies its own password rules and the browser can't clear the flag without really changing the password.
- 2026-11-01: Treat sign-up as closed by the code, with no route or form and a 403 for an Auth user with no profile, so nothing depends on the hosted Supabase setting being right.
- 2026-11-01: Deactivate by banning in Auth first and marking the profile second, and keep the profile row, because a failure between the two leaves the person locked out rather than still able to sign in, and their decisions still point at that row.
- 2026-11-01: Lock the active manager rows with `FOR UPDATE` before deactivating or demoting a manager, because two managers deactivating each other at the same moment would otherwise leave none.
- 2026-11-01: Stop the web build if a `VITE_` variable is named for the service role key or holds its value, because every `VITE_` value ends up in the public JavaScript.
- 2026-11-01: Change the pricing rules for games and hardware after the first evaluation, where the pipeline lost to raw asking prices on 18 items, because asking prices before the factor were a median 1.06 times the sold reference, so a factor of 0.645 from Poshmark apparel was too strong for them. This replaces the earlier call to leave the rules alone, whose worry about only fitting those 18 items is now answered by scoring fresh items that had no part in the tuning, and the 18 are labeled as tuning data.
- 2026-11-01: Set the factor for games and hardware to 0.94, one over that median, rather than the value that scored best, because a value picked for its score would fit the 18 items more closely and say less about the next item.
- 2026-11-01: Widen the range for games and hardware to the 15th to 85th percentiles and leave the comp filter alone, because a 25th to 75th band holds about half of what it measures by design, and the report shows the width and a like-for-like row, so a wider range can't pass as better pricing.
- 2026-11-01: Keep confidence on the 25th to 75th percentiles in every category, so widening the range doesn't turn a high-confidence item into a "check" with no new evidence about the item.
- 2026-11-02: Read and write every text file as UTF-8 and pass `newline="\n"` on each write, and check the repo out with LF through `.gitattributes`, so the evaluation report and saved results compare equal and the tests pass on Windows, where the default encoding is cp1252 and checkout would otherwise introduce CRLF.
- 2026-11-01: Leave apparel's factor and percentiles as they were, because none of the tuning evidence comes from apparel.
- 2026-11-01: Keep the fresh evaluation items in their own file, `api/eval/fresh_items.json`, so `git log` on that file shows the list came before its first score.
- 2026-11-01: Count username sign-in failures in the `sign_in_attempts` table instead of the API process, so the count survives a restart and holds across processes. Each attempt is counted under a short per-username advisory lock before Auth is asked, because counting afterwards would let requests arriving together all pass, and the username is hashed because people sometimes type a password into that box.
- 2026-11-01: Answer a wrong password, an unknown username and a turned-off account with one message, and count a turned-off account's tries like any others, because a different message or a limit that never arrives would show whether a password was right or an account exists.
- 2026-11-01: Refuse a token issued before `temporary_password_issued_at` on every signed-in route, and take that time from Auth's own reply rather than the API's clock, because the token's issue time is on Auth's clock. Auth 2.197.0 already ends old sessions when an admin changes a password, so this is a second check rather than the only one.
- 2026-11-01: Grow the fresh set to 30 games and hardware items with 15 picked to be harder, and report each batch beside the total, so the first batch's easier items can't hide the harder ones and the total can't be read as a random sample. The factor and percentiles stayed frozen even though asking prices ran a median 1.16 times the reference on the 30.
- 2026-11-01: Run the keep-alive ping as a scheduled GitHub Actions job on the self-hosted runner rather than an outside pinger service, because it needs no new account and spends no paid minutes, and accept that it stops while that PC is off, since a sleeping service still wakes in about a minute.
- 2026-11-01: Point the offline demo at a local stand-in for Supabase, the vision model and SerpApi rather than adding an offline switch to the app, so no setting in the deployed code can turn sign-in off.
- 2026-11-01: Report the deployed commit on `/health` from Render's `RENDER_GIT_COMMIT`, so anyone can check from outside which commit is live.
- 2026-11-02: Score vision accuracy from the saved evaluation cards rather than a new model run, because they came from the current prompt and providers and a rerun spends nothing, and count a near miss as wrong so the accuracy never gives partial credit, see [vision-accuracy.md](vision-accuracy.md).
- 2026-11-03: Work out the claim checker's flags whenever a draft is read rather than storing them, and store only the flags that sent the model's draft to the template, because a staff edit or a card edit would leave stored flags out of date.
- 2026-11-03: Allow a banned word or a claim when the card's own text has it, such as "vintage wash" in a product name, because the checker's job is to stop claims the card doesn't make, and refuse grades such as "mint" or "no flaws" even after a "not", because the card has no field for them.
- 2026-11-03: Refuse to send drafts for approval while any of them has a flag, rather than warning, because a manager approving a flagged claim is the mistake the checker is there to stop, and staff can always reword or fall back to the template text.
- 2026-11-03: Write a draft only for an item whose latest decision is yes, and draft a missing channel again rather than replacing one, so a lost response can be retried without overwriting staff's edits.
- 2026-11-03: Share `complete_json` in `api/app/ai.py` between the item card and the drafts, so both retry and fall back the same way.
- 2026-11-03: Read quoted words that are on the card as a copy of the card, and have the prompt quote the item's printed text, because the first live run passed 40 of 48 drafts, and 4 of its 7 flags came from the model describing that text with "includes" or "with" while the other 3 used "includes" for parts the card already names, so the prompt also bans "includes" when nothing extra was recorded.
