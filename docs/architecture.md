# Architecture

This page lists the main technical choices and why we made them.
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
| Vision and language model | Any OpenAI-compatible chat-completions endpoint | The provider is a setting, `AI_BASE_URL`, `AI_MODEL` and `AI_API_KEY`, so we can switch without code changes. |
| Photo storage | Local folder or Supabase Storage | One interface in `api/app/storage.py`, with the backend picked by settings. |
| Hosting | Cloudflare Pages for the frontend, Render for the API, Supabase for the database and photos | Each has a free tier that fits a student demo. |
| Python tooling | ruff and pyright | Fast lint, format and type checks with little configuration. |
| Frontend tooling | ESLint, Prettier, `tsc` and Vitest | The standard checks for a Vite and React project. |
| Checks | pre-commit hooks and GitHub Actions | The same lint, type checks and tests run on every commit and every pull request. |

## Environments

| | Development and tests | Shared demo |
| --- | --- | --- |
| Database | Postgres 17 in Docker Compose | Supabase Postgres 17 |
| Photo storage | Local folder | Supabase Storage |
| API | `docker compose up` on each laptop | Render |
| Frontend | `npm run dev` on each laptop | Cloudflare Pages |

Development and tests use a local database, so each of us can reset data and run migrations without touching the shared demo or needing a network connection.
CI starts its own Postgres for the same reason.
The demo reads its connection details from environment variables, so the code is the same in both places.

The Cloudflare Pages project `blessings-abound` builds the frontend from `main` with root directory `web`, build command `npm run build` and output directory `dist`, and serves it at https://blessings-abound.pages.dev.
Every pull request gets its own preview link from Pages, and nobody needs a Cloudflare account to open it.
The build uses the Node version in `web/.nvmrc`, and `VITE_API_URL` goes in the Pages project's environment variables once the Render API exists.
Sign-in needs `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` there too, and each site's `/choose-password` address must be in the Supabase Auth redirect list for reset links to work.
Pages serves `index.html` for any path without a file, because the build has no `404.html`, so the app needs no rewrite config.

## Pricing pipeline

None of this is built yet, and each step is a board issue.
The language model never produces a price, and every number comes from code over comps, which are similar items for sale on eBay.

1. Staff upload a photo and add notes, and they always supply the condition, size, whether it is a kids' item, and whether it is complete in box.
   Those four come from staff, never from the model.
2. The vision model turns the photo and notes into an item card with the category, brand, product, any visible text, a search query and its own confidence, and staff can edit the card before any search is spent.
3. Code builds the eBay search from the card and the staff notes.
4. SerpApi's eBay engine returns active Buy It Now listings filtered by condition, and if fewer than 8 survive the filters, code drops the last query word and searches again, at most twice.
5. Code filters the listings by title, dropping accessories, lots, parts and similar matches unless the item itself is one of those.
6. Code trims outliers with Tukey fences on log price, skipped when fewer than 4 listings remain, and takes the 25th, 50th and 75th percentiles as the low, typical and high price.
7. Asking prices run higher than sale prices, so code multiplies the range by an ask-to-sale factor of 0.645, which is set in config per category and should be recalibrated on our evaluation set.
8. Confidence is high with at least 10 listings and a high-to-low ratio of at most 2, medium with at least 5 and a ratio of at most 3, and low otherwise.
9. The worth-listing rule takes the typical price, subtracts eBay's fees of 13.6% plus $0.40 per order and $1.50 for supplies, and compares the net with a cutoff in config, a placeholder of $15 net for now.
   The answer is "yes" at or above the cutoff, "no" below it, and "check" when confidence is low or there are no comps.
10. The language model writes a short explanation from the computed numbers only, and code rejects the text if it contains any number that is not in those facts.

Staff see the range, the comps as links, the confidence and the recommendation, and they make the final call, which the app saves.

Comps come through SerpApi rather than eBay's own API, because eBay's API license does not allow using its content to suggest or model prices.
SerpApi's free plan allows 250 searches a month and 50 an hour, so every response is cached in a `comp_searches` table, keyed by the engine, query, condition and buying format, and reused for 7 days.
Tests read committed fixture responses and never call SerpApi.

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
- 2026-10-30: Route the web app with React Router, with the landing page at `/`, sign-in pages beside it and the signed-in app under `/app`.
- 2026-10-30: Sign people in with Supabase Auth straight from the web app, using only the public anon key, so the API needs no auth code of its own for now.
- 2026-10-30: Use the USWDS colors and Public Sans in place of the shadcn defaults and Geist, to match the approved landing and sign-in mockups.
- 2026-10-30: Look up a username's email through `web/src/auth/accounts.ts` only, so issue #31 can back usernames and temporary passwords without changing the pages.
