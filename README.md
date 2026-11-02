# Turnstone

A staff web app for Blessings Abound, a Kansas City nonprofit thrift store chain, that follows a donated item from intake to sale.
Every item forwarded to Ecommerce gets a SKU and a triage log entry at intake, and every item is one of a kind and sold online only.
A staff member uploads a photo of an item and enters details such as condition and size, a vision model turns them into an editable item card, and the app looks up similar eBay listings to suggest a price range and whether the item is worth listing.
The price comes from code over those listings, never from the language model, which only explains the result.
Later stages draft the listing text, recommend a channel and timing, and send each listing to a manager for approval, along with its storage location and a pick list for when it sells.
Listings publish to two fictional mock channels that stay in sync after a sale, with conflicts flagged on a Needs Attention screen, and managers see sales insight on synthetic data.
Staff and managers make every final decision.

The project is a proof of concept built from a short Q&A with Blessings Abound, which is where thresholds such as the $30 worth-listing bar come from, and it otherwise uses only public or self-generated data.

## Repository layout

| Folder | What it holds |
| --- | --- |
| `api/` | FastAPI backend, database models and Alembic migrations |
| `web/` | Vite, React and TypeScript frontend with Tailwind and shadcn/ui |
| `docs/` | Requirements and architecture, see [docs/requirements.md](docs/requirements.md) and [docs/architecture.md](docs/architecture.md) |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [Node.js](https://nodejs.org/) 24, the version in `web/.nvmrc`
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python 3.12 itself

## Setup

Run the database and the API in one terminal:

```sh
cp .env.example .env
docker compose up
```

The API applies database migrations on start and serves at http://localhost:8000, with interactive docs at http://localhost:8000/docs.

Run the web app in a second terminal:

```sh
cd web
npm ci
npm run dev
```

Open http://localhost:5173 for the landing page.
Signing in needs `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in `.env` and an account in that Supabase project.
An email address works with just those two, but a username also needs the API running with `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` set.
The service role key stays on the server, and the web build stops with an error if it finds that key in a `VITE_` variable.
After signing in, the page at http://localhost:5173/app should show the API status as `ok`.

The appraisal screen at http://localhost:5173/app/appraise also needs the API to check your sign-in and find your profile.
Set `SUPABASE_URL` and `SUPABASE_ANON_KEY` in `.env`, then give your Supabase Auth user a profile in the local database:

```sh
cd api
uv run python -m app.seed_local_profile <auth user id> <username> [staff|manager]
```

The Auth user id is on the user's row in the Supabase dashboard, and the script refuses any database that isn't local.

If port 5432 or 8000 is already taken on your machine, set `POSTGRES_PORT` or `API_PORT` in `.env`, and update `DATABASE_URL` or `VITE_API_URL` to match.

## Offline demo

This runs the whole app on one laptop with no keys and no Wi-Fi, in case the venue's network or a hosted service fails.
Build it once while you still have a network, because the images have to be downloaded and built:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml build
```

Then start it, with or without a network:

```sh
docker compose -f docker-compose.yml -f docker-compose.offline.yml up
```

Open http://localhost:5173 and sign in as `demo.staff` or `demo.manager`, both with the password `offline-demo`.
A small stand-in service in [api/app/offline_standin.py](api/app/offline_standin.py) answers for Supabase, the vision model and SerpApi, and the app's own code runs unchanged.
It doesn't read the photo, so every photo gets the same Levi's 501 card, and prices come from the saved eBay responses in `api/tests/fixtures/serpapi/`, chosen by the words in the search.
The addresses it uses are `localhost`, so it works only in a browser on the laptop running it, not from a phone.

## Hosted demo

The demo is at https://blessings-abound.pages.dev, with the API at https://blessings-abound-api.onrender.com.

| Part | Where | Settings |
| --- | --- | --- |
| Web app | Cloudflare Pages project `blessings-abound`, built from `main` | `VITE_API_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in the production environment variables |
| API | Render free web service `blessings-abound-api`, Docker from `api/` on `main` in Ohio, deployed on every merge | The list below |
| Database, photos and sign-in | Supabase | Auth site URL set to the web app's address, and its `/choose-password` address in the redirect list |

To set the API up again, create the Render service with those details and a health check path of `/health`, then set these from [.env.example](.env.example):

- `DATABASE_URL`, using Supabase's session pooler on port 5432 with the `postgresql+psycopg://` scheme.
- `CORS_ORIGINS`, as `["https://blessings-abound.pages.dev","http://localhost:5173"]`.
- `WEB_APP_URL`, as `https://blessings-abound.pages.dev`.
- `SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY`.
- `SUPABASE_STORAGE_BUCKET`, as `item-photos`, which is the hosted bucket's name.
- `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY` and the matching `AI_FALLBACK_` settings.
- `SERPAPI_API_KEY`.

The service role key goes only on Render, and only the project URL and the anon key go in the Pages settings.
A change to a `VITE_` value needs a new Pages deployment, because those values are built into the JavaScript.
`GET /health` shows the commit Render deployed, and `GET /health/db` also checks the database.

[keep-alive.yml](.github/workflows/keep-alive.yml) calls `/health/db` every 10 minutes, because Render stops a free service after 15 idle minutes and Supabase pauses a free project after about a week.
It runs on our self-hosted CI runner, so it stops while that PC is off and can wait behind a CI job, and GitHub can also start scheduled runs late.
A sleeping service still answers, after about a minute, so a missed ping costs time rather than the demo.
Render's free plan allows 750 hours a month across a workspace, which covers one service running all month but not three, so limit the schedule when the mock channels are added.

### Wake checklist

Do this the day before judging, and again 15 minutes before it starts.

1. Check that `curl https://blessings-abound-api.onrender.com/health` answers `200` with the commit at the top of `main`, allowing a minute for a cold start.
2. Check that `curl https://blessings-abound-api.onrender.com/health/db` answers `200`. If it answers `503`, restore the project if the Supabase dashboard shows it paused, then try again.
3. Check that the latest Keep the demo awake run in GitHub Actions passed within the last 15 minutes.
4. On a phone, open https://blessings-abound.pages.dev, sign in as `demo.staff`, check that the home page shows the API status as `ok`, and sign out.
5. Do the same as `demo.manager`.
6. Check on the SerpApi dashboard that searches are left this month.
7. On the laptop, run the offline demo's `up` command once, sign in, and leave it ready in case the network fails.

## Tests and lint

Each part runs the same checks as CI.

API, with the database from `docker compose up` running:

```sh
cd api
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run alembic upgrade head
uv run alembic check
uv run alembic heads
uv run pytest
```

`alembic heads` should print exactly one line.
The tests refuse to run against anything but a local database.

A change to the pricing rules, the comp filter or the evaluation items makes a test fail until `uv run python -m app.evaluate` in `api/` rewrites [docs/evaluation.md](docs/evaluation.md), which spends no searches and needs no keys.

A change to the saved cards, the vision labels or the item card prompt makes a test fail until `uv run python -m app.vision_accuracy` in `api/` rewrites [docs/vision-accuracy.md](docs/vision-accuracy.md), which makes no model calls and needs no keys.

Web:

```sh
cd web
npm run lint && npm run format:check
npm run typecheck
npm test
npm run build
```

To run the formatters and linters before every commit, install the pre-commit hooks once with `uvx pre-commit install`.

## Changing the API

After changing a route or a request or response model, regenerate the web app's typed client and commit it with the change:

```sh
cd web
npm run gen:api
```

Schema changes go through Alembic migrations, as described in [CONTRIBUTING.md](CONTRIBUTING.md#database).
The tables are described in [docs/database.md](docs/database.md), which also covers creating the first manager account, seeding the demo accounts and the manager routes for adding people.

## Pricing

The pricing pipeline is described in [docs/architecture.md](docs/architecture.md#pricing-pipeline), and an appraisal now runs it from the confirmed item card through the SerpApi comps lookup, the comp filter and the pricing functions.
It needs a SerpApi key in `SERPAPI_API_KEY`, and without one an appraisal saves a "check" with no price.
Tests never call SerpApi, because they read committed fixture responses instead and clear the key.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow and the project conventions.
See [docs/requirements.md](docs/requirements.md) for what the team is building, by tier, and the assumptions it rests on.
See [WORKLOG.md](WORKLOG.md) for a log of what each developer has changed.
