# Thrift Listing Assistant

A staff-facing web app that helps a thrift store decide which donated items to sell online, price them, and list them on more than one site.
A staff member uploads a photo of an item, a vision model turns it into an editable item card, and a trained price model plus a live market lookup suggest a price range and whether the item is worth listing.
Later stages draft the listing text, suggest a sales channel, and publish to several sites at once.
Staff make every final decision.

The project is a proof of concept inspired by Blessings Abound, a Kansas City nonprofit thrift organization, and it uses only public or self-generated data.

## Repository layout

| Folder | What it holds |
| --- | --- |
| `api/` | FastAPI backend, database models and Alembic migrations |
| `web/` | Vite, React and TypeScript frontend with Tailwind and shadcn/ui |
| `ml/` | Price model training, kept apart from the API |
| `docs/` | Architecture notes and decisions, see [docs/architecture.md](docs/architecture.md) |

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
uv run pytest
```

Web:

```sh
cd web
npm run lint && npm run format:check
npm run typecheck
npm test
npm run build
```

ML:

```sh
cd ml
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

To run the formatters and linters before every commit, install the pre-commit hooks once with `uvx pre-commit install`.

## Changing the API

After changing a route or a request or response model, regenerate the web app's typed client and commit it with the change:

```sh
cd web
npm run gen:api
```

Schema changes go through Alembic migrations, as described in [CONTRIBUTING.md](CONTRIBUTING.md#database).

## Retraining the price model

Training code is not written yet, and [ml/README.md](ml/README.md) describes how it will work.
Once it exists, retraining is two steps from `ml/`: download the Mercari dataset with `uv run --with kaggle python download_data.py`, then run the training script, which saves the model file to `ml/models/` and its metrics to `ml/results/`.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the branch and review workflow and the project conventions.
