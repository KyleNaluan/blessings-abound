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

Open http://localhost:5173, and the page should show the API status as `ok`.

If port 5432 or 8000 is already taken on your machine, set `POSTGRES_PORT` or `API_PORT` in `.env`, and update `DATABASE_URL` or `VITE_API_URL` to match.

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
The tables are described in [docs/database.md](docs/database.md), which also covers creating the first manager account.

## Pricing

The pricing pipeline is described in [docs/architecture.md](docs/architecture.md#pricing-pipeline), and none of it is built yet.
It needs a SerpApi key in `SERPAPI_API_KEY`, but tests never call SerpApi, because they read committed fixture responses instead.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow and the project conventions.
See [docs/requirements.md](docs/requirements.md) for what the team is building, by tier, and the assumptions it rests on.
See [WORKLOG.md](WORKLOG.md) for a log of what each developer has changed.
