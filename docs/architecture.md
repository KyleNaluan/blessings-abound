# Architecture

This page lists the main technical choices and why we made them.
Update it in the same pull request whenever one of them changes.

## Stack

| Part | Choice | Why |
| --- | --- | --- |
| Repository | One repo with `api/`, `web/` and `ml/` | One place to clone, review and reproduce, with each part keeping its own dependencies. |
| Backend | FastAPI on Python 3.12 | Python matches the data science work, and FastAPI generates an OpenAPI schema from the code. |
| Python packages | uv | One fast tool for Python versions, virtual environments and lock files. |
| Frontend | Vite, React and TypeScript | A common, well-documented setup with fast reloads and type checking. |
| Styling | Tailwind and shadcn/ui | Ready-made accessible components that we own as source and can restyle. |
| API client | `openapi-typescript` and `openapi-fetch` | Frontend types come from the API's schema, so a change on one side shows up as a type error on the other. |
| Database | Postgres | One relational database for items, appraisals and decisions, the same engine locally and in the demo. |
| Database access | SQLModel on SQLAlchemy | Table models double as Pydantic models, which keeps the API code short. |
| Schema changes | Alembic | Every schema change is a reviewed, repeatable migration file. |
| Price model | pandas, scikit-learn and LightGBM | LightGBM trains quickly on tabular listing data and handles categories well. |
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

Cloudflare Pages builds the frontend with root directory `web`, build command `npm run build` and output directory `dist`, and `VITE_API_URL` is set there to the Render API's address.
Pages serves `index.html` for any path without a file, because the build has no `404.html`, so the app needs no rewrite config.

## Decisions log

Add new decisions at the bottom, with the date and a line on why.

- 2026-10-23: Keep a local Postgres for development and tests, and use Supabase only as the shared hosted database for the demo, so local work never changes shared data.
- 2026-10-23: Store money as integer cents and times in UTC, as described in CONTRIBUTING.md.
- 2026-10-23: Keep `ml/` as its own uv project, so the API does not install training-only packages, and load the trained model file in the API.
- 2026-10-23: Generate the web client's types from the API's OpenAPI schema and check in CI that the committed file is current.
- 2026-10-23: Pin TypeScript to 5.9, because `openapi-typescript` does not support TypeScript 6 yet.
- 2026-10-23: Use `httpx2` as the HTTP client, because Starlette's test client deprecated `httpx` in its favor.
- 2026-10-23: Run Postgres 17 locally and in CI, the same major version as the Supabase project, so migrations behave the same everywhere.
- 2026-10-23: Host the frontend on Cloudflare Pages instead of Vercel.
- Open: how the trained model file reaches the deployed API on Render, decided with the training work.
