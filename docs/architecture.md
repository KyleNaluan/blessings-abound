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
| Auth | Supabase Auth, with a plain UUID login ID, display name and role in `profiles` | The API enforces the two roles, staff and manager, and row-level security blocks all other access. |
| Mock channels | Two separate FastAPI services on Render, each with its own database role and schema, `channel_a` and `channel_b` | They stand in for real platforms behind an adapter interface, and they keep their data in Postgres, so it survives restarts on free hosts. |
| Background work | An in-process scheduler and a `jobs` table in Postgres | It handles polling, retries and AI calls without a separate worker to host. |
| Photo storage | Local folder or Supabase Storage | One interface in `api/app/storage.py`, with the backend picked by settings. |
| Hosting | Cloudflare Pages for the frontend, Render for the API and mock channels, Supabase for the database and photos | Each has a free tier that fits a student demo. |
| Keeping the demo up | A free external pinger, and an offline `docker compose` demo with cached lookups and fixture responses | An idle free service stops polling and can miss webhooks, and the offline demo works with no keys or Wi-Fi. |
| Python tooling | ruff and pyright | Fast lint, format and type checks with little configuration. |
| Frontend tooling | ESLint, Prettier, `tsc` and Vitest | The standard checks for a Vite and React project. |
| Checks | pre-commit hooks and GitHub Actions | The same lint, type checks and tests run on every commit and every pull request. |

## Environments

| | Development and tests | Shared demo |
| --- | --- | --- |
| Database | Postgres 17 in Docker Compose | Supabase Postgres 17 |
| Photo storage | Local folder | Supabase Storage |
| API | `docker compose up` on each laptop | Render, up to three services with the two mock channels |
| Frontend | `npm run dev` on each laptop | Cloudflare Pages |

Development and tests use a local database, so each of us can reset data and run migrations without touching the shared demo or needing a network connection.
CI starts its own Postgres for the same reason.
The demo reads its connection details from environment variables, so the code is the same in both places.

The Cloudflare Pages project `blessings-abound` builds the frontend from `main` with root directory `web`, build command `npm run build` and output directory `dist`, and serves it at https://blessings-abound.pages.dev.
Every pull request gets its own preview link from Pages, and nobody needs a Cloudflare account to open it.
The build uses the Node version in `web/.nvmrc`, and `VITE_API_URL` goes in the Pages project's environment variables once the Render API exists, along with `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for sign-in.
Each site's `/choose-password` address must be in the Supabase Auth redirect list for reset links to work.
Pages serves `index.html` for any path without a file, because the build has no `404.html`, so the app needs no rewrite config.

The hosted demo follows these steps:

- Connect to Supabase with the direct or session connection string, because the transaction pooler needs prepared statements disabled for psycopg (`prepare_threshold=None`).
- Start each Render service with `alembic upgrade head && uvicorn ...`, so Supabase receives migrations only after merge.
- Before judging, reset the demo data with a rerunnable seed script, compare the structure with `pg_dump --schema-only`, and back up Supabase the day before.
- Wake Supabase and every Render service before judging, because free Supabase projects pause after about a week of inactivity.

## Pricing pipeline

None of this is built yet, and each step is a board issue.
The language model never produces a price, and every number comes from code over comps, which are similar items for sale on eBay.

1. Staff upload 1 required photo and up to 4, and a code-only blur and brightness check prompts a retake.
   Staff enter the condition grade, using eBay's values, and any flaws, plus the department, size and size type for apparel and shoes, or tested and working, complete-in-box and accessories for electronics and games.
   Those come from staff, never from the model.
2. The vision model turns the photos and staff entries into an item card with the category, brand, product, any visible text, a search query and its own confidence, and it proposes the color, material, exact model and platform for staff to confirm.
   Staff can edit the card before any search is spent, and low brand or model confidence needs their confirmation before searching.
3. Code builds the eBay search from the card and the staff notes.
4. SerpApi's eBay engine returns active Buy It Now listings filtered by condition, and if fewer than 8 survive the filters, code drops the last query word and searches again, at most twice.
5. Code filters the listings by title, dropping accessories, lots, parts and similar matches unless the item itself is one of those.
6. Code trims outliers with Tukey fences on log price, skipped when fewer than 4 listings remain, and takes the 25th, 50th and 75th percentiles as the low, typical and high price.
7. Asking prices run higher than sale prices, so code multiplies the range by an ask-to-sale factor of 0.645, which is one value in config rather than one per channel, because comps always come from eBay.
   It is labeled an assumption, because it comes from Poshmark data with ratios from 1.21 to 2.93, and a re-measure on eBay is a stretch item done by hand.
8. Confidence is high with at least 10 listings and a high-to-low ratio of at most 2, medium with at least 5 and a ratio of at most 3, and low otherwise.
9. The worth-listing rule says "yes" when the typical sale price is at least $30, "no" below it, and "check" when confidence is low or there are no comps, and the threshold, fees and supplies live in config.
   The net after eBay's fees, which are 13.6% for most categories plus $0.40 per order, and $1.50 for supplies is shown beside it.
10. The language model writes a 2 to 3 sentence explanation from the computed numbers only, and code rejects the text if it contains any number that is not in those facts and falls back to a template.

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
- 2026-10-29: Keep one ask-to-sale factor of 0.645, labeled an assumption, instead of one per channel, because comps always come from eBay.
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
- 2026-11-01: Keep an item `appraised` after a yes and set it to `declined` after a no, because no status means "staff said yes" and `approved` belongs to the manager step.
