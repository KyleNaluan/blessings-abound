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

- [Git](https://git-scm.com/downloads), which on Windows also gives you Git Bash
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose, running before you start the setup (on Windows, open Docker Desktop and wait for it to say the engine is running)
- [Node.js](https://nodejs.org/) 24, the version in `web/.nvmrc`
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python 3.12 itself

On Windows, run every command below in Git Bash, because Windows PowerShell 5.1 does not accept `&&` and Command Prompt has no `cp`.

## Setup

Clone the repository and go into it:

```sh
git clone https://github.com/KyleNaluan/blessings-abound.git
cd blessings-abound
```

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

If port 5432, 8000, 8001 or 8002 is already taken on your machine, set `POSTGRES_PORT`, `API_PORT`, `CHANNEL_A_PORT` or `CHANNEL_B_PORT` in `.env`, and update `DATABASE_URL` or `VITE_API_URL` to match.

## Mock channels

`docker compose up` also starts the two mock sales channels, which [docs/architecture.md](docs/architecture.md#mock-channels-and-sync) describes.
Channel A, an eBay-style marketplace for clothing, electronics and games, has its storefront at http://localhost:8001, and Channel B, a resale app for clothing only, has its storefront at http://localhost:8002.

To see a sale come through:

1. Appraise an item in the web app, say yes to it, and send its listings on.
2. As a manager, approve it from the approvals page and enter its shelf or bin.
   Storing it lists it on each channel its drafts are for, at the price on the review page, and the review shows each listing go live within a few seconds.
   A game or a console goes on Channel A only, because Channel B takes clothing only.
3. Open either storefront and buy the item.
   It disappears from the other storefront within a few seconds, because the sale webhook tells the API at once, and the item shows on the pick list.
4. Untick "Tell the seller right away, by sale webhook" before buying to show a missed webhook, and the API's poll, every 30 seconds, finds the sale instead.

Each channel's `/admin` page, at http://localhost:8001/admin or http://localhost:8002/admin, takes the channel offline and back.
Sign in with any username and the channel key, which is `local-channel-a-key` or `local-channel-b-key` unless `.env` sets `CHANNEL_A_KEY` or `CHANNEL_B_KEY`.
While a channel is offline, the API's updates to it fail and are retried from the `jobs` table, with waits from 5 seconds up to 5 minutes, and go through once it is back.
A listing that still hasn't gone up after 10 tries shows on the review page with a button to try that channel again.
Buying the same item on the second channel before the first has taken it down is flagged as a double sale.
Every change and every flag is in the `sync_log` table, as [docs/database.md](docs/database.md#needs-attention-flags) describes.

To see a double sale fixed:

1. Store an item that goes on both channels, such as a piece of clothing with a brand.
2. Buy it on Channel A with "Tell the seller right away, by sale webhook" unticked, then buy it on Channel B within 30 seconds, before the poll finds the first sale.
3. Open "Needs attention" from the home page, as staff or a manager.
   The double sale says which order keeps the item and which one to cancel.
4. Press "Cancel the Channel B order".
   Channel B cancels the order, and the flag moves to "Recently handled" with who fixed it.

Take Channel B offline before step 4 to see the cancel retried, and it goes through once Channel B is back.

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
The mock channels run as they do in `docker compose up`, so the steps in [Mock channels](#mock-channels) work offline too, with `demo.manager` as the manager who approves and stores the item.

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
Render's free plan allows 750 hours a month across a workspace, which covers one service running all month but not three, so the mock channels should be kept awake only in the days around judging.

### Mock channels on Render

The mock channels are not hosted yet.
Each one would be a Render free web service, Docker from `api/` on `main`, with a health check path of `/health`, and these settings:

| Setting | Channel A | Channel B |
| --- | --- | --- |
| Start command | `uvicorn mock_channel.channel_a:app --host 0.0.0.0 --port $PORT` | `uvicorn mock_channel.channel_b:app --host 0.0.0.0 --port $PORT` |
| `CHANNEL_DATABASE_URL` | Supabase's session pooler with the user `channel_a.<project ref>` and the `postgresql+psycopg://` scheme | The same with `channel_b.<project ref>` |
| `CHANNEL_KEY` | A long random key | A different long random key |
| `CHANNEL_WEBHOOK_URL` | `https://blessings-abound-api.onrender.com/channels/channel_a/sales` | `https://blessings-abound-api.onrender.com/channels/channel_b/sales` |

The start command replaces the image's own, so a channel service never runs migrations.
After the API has applied the migration, run `uv run python -m app.channel_roles` in `api/` once with `DATABASE_URL` pointing at Supabase and `CHANNEL_A_DB_PASSWORD` and `CHANNEL_B_DB_PASSWORD` set, so the two roles can sign in.
Then set `CHANNEL_A_URL`, `CHANNEL_A_KEY`, `CHANNEL_B_URL` and `CHANNEL_B_KEY` on the API service, with each key matching that channel's `CHANNEL_KEY`.

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

A change to the listing prompt, the claim checker or the saved drafts makes a test fail until `uv run python -m app.draft_eval` in `api/` rewrites [docs/listing-drafts.md](docs/listing-drafts.md), which makes no model calls and needs no keys.
A prompt change also needs the drafts written again with `--write-drafts`, which uses the AI keys.

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
A manager can change the worth-listing price, the fees and the ask-to-sale factors on the Settings page, which is described with its sources in [docs/settings.md](docs/settings.md).

## Approval and the pick list

A manager approves or rejects each item whose listings staff sent on, sets a price per channel, enters the package and the shelf or bin, and staff pull sold items from the pick list, as described in [docs/architecture.md](docs/architecture.md#manager-approval-and-storage).
Storing an approved item lists it on the mock channels, and a sale on either one puts it on the pick list, as [Mock channels](#mock-channels) shows.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow and the project conventions.
See [docs/requirements.md](docs/requirements.md) for what the team is building, by tier, and the assumptions it rests on.
See [WORKLOG.md](WORKLOG.md) for a log of what each developer has changed.
