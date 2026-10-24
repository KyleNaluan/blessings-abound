# Contributing

This is how we work together in this repo so that nobody overwrites anyone else's changes and every change gets a second look before it lands.
It's a small-team version of how most professional teams work.

## The main rule

Nobody pushes directly to `main`.
Every change goes through a pull request, and at least one other person reviews and approves it before it merges.

`main` should always run.
It's the branch we demo from, so if a merge breaks it, we revert the merge first and fix it on a branch after.

## Step by step

### 1. Start from the latest main

```sh
git checkout main
git pull
```

### 2. Make a branch

Name it `<firstname>/short-description`, for example `kyle/ebay-listing-sync`.
Use one branch per feature or fix, because small branches are faster to review and conflict less.

```sh
git checkout -b kyle/ebay-listing-sync
```

### 3. Commit as you go

Commit your own work under your own GitHub account.
Write the first line as a short present-tense summary of what the change does, such as `Add delist call when an item sells`, not `stuff` or `fixes`.
Small, working commits are easier to review than one large commit at the end.

```sh
git add <files>
git commit -m "Add delist call when an item sells"
```

### 4. Push the branch

```sh
git push -u origin kyle/ebay-listing-sync
```

The `-u` links your branch to GitHub the first time, so after that a plain `git push` works.

### 5. Open a pull request

GitHub prints a link after the first push, or you can use the "Compare & pull request" button on the repo page.
The description should answer three things:

1. **What changed and why**, in a short paragraph.
2. **How to test it**, with the exact commands or clicks you used.
3. **Anything you're unsure about**, so the reviewer looks there first.

### 6. Ask for a review

Tag a teammate on the pull request or message them in the group chat.
People are busy with their own work, so don't wait for them to notice it.

### 7. Respond to comments

Push more commits to the same branch and they show up in the pull request automatically.
Reply to each comment as you address it, so the reviewer knows what to check again.
Don't force-push over a branch someone has already reviewed.

### 8. Merge when approved

Use **"Create a merge commit"**, not squash.
A merge commit keeps each person's commits as they were, which keeps the history of who built what.
Don't merge your own pull request without an approval, and don't merge one with a failing check.
Checks run on a self-hosted runner, so if it is offline they wait in the queue and start when it comes back.

### 9. Delete the branch

GitHub shows a button after the merge.
It keeps the branch list short.

## Staying in sync

Pull `main` at the start of each work session.
Before asking for a review, merge the latest `main` into your branch and fix any conflicts yourself.

## Reviewing

- Run the change when it can be run, rather than only reading the diff.
- Check that it does what the description says.
- Ask about anything you had to think hard to understand, because someone will have to understand it again later.
- Look for the edge cases we're likely to hit, such as an item that's already sold, a missing photo, or a listing API that's down.
- Skip arguments about style choices where both ways are fine.

One or two rounds of comments is normal.
If a pull request goes past four or five rounds, it's probably too big or the design isn't settled, so split it up or talk it through first.

## What stays out of the repo

- Secrets, API keys and `.env` files, which we share privately instead.
  Commit a `.env.example` with the variable names and no values.
- Client data, such as real inventory exports or contact details.
  Use mock data in the repo.
- Large binaries, exports and scratch files, which belong in the shared drive.
- AI tool config files and chat logs, except the shared `AGENTS.md` and the one-line `CLAUDE.md` that points to it.
- AI attribution in commits and pull requests, such as `Co-Authored-By` lines or "Generated with" footers that some tools add by default.
  Turn them off in your tool's settings, or delete them before you push.

## Project board

Work is tracked as GitHub issues on the project board, with one issue per pull-request-sized task.
Pick an issue, assign yourself, and move it across the board as you go.
Put `Closes #N` in the pull request description, so the issue closes when the pull request merges.

## Conventions

These keep the parts of the app consistent and the results reproducible.
If one gets in your way, raise it in the group chat rather than working around it.

### Naming and data

- API JSON fields and database columns use `snake_case`, such as `item_id` and `listed_at`.
- Money is stored and sent as integer cents in fields ending in `_cents`, such as `price_cents = 1299` for $12.99, never as floats.
- Times are stored and sent in UTC as ISO 8601 strings with an offset, and only the web app converts them to local time for display.

### Database

- The schema changes only through Alembic migrations in `api/alembic/versions/`, never by editing tables by hand, in Supabase or anywhere else.
- Create one with `uv run alembic revision --autogenerate -m "Add items table"` in `api/`, read what it generated, and commit it with the model change.
- Never edit a migration that has already merged, and add a new one instead.

### Dependencies

- Dependencies are pinned by the lock files, `api/uv.lock` and `web/package-lock.json`, which are committed with every dependency change.
- Add packages with `uv add <package>` or `npm install <package>`, not by editing the lock files.
- Install from the lock files with `uv sync` and `npm ci`.

### The generated API client

- `web/src/api/schema.d.ts` is generated from the API's OpenAPI schema, so the web app and the API cannot drift apart without a type error.
- Whenever an API change touches a route or a request or response model, run `npm run gen:api` in `web/` and commit the regenerated file in the same pull request.
- Never edit `schema.d.ts` by hand, because CI regenerates it and fails when the committed file differs.

### Data and secrets

- Secrets live in `.env`, which is git-ignored, and every new variable is added to `.env.example` with no value.
- Keep seller names and other personal details out of the repo, including in fixtures.

### Pricing

- The language model never produces a price, and prices come from code over comps, as described in `docs/architecture.md`.
- Anything the language model writes about an item is checked by code, which rejects the text if it contains a number that is not in the facts it was given.

### SerpApi fixtures

- The free SerpApi plan allows 250 searches a month, so cache every response.
- Cached responses are committed as JSON test fixtures in `api/tests/fixtures/serpapi/`, and tests read the fixtures rather than calling SerpApi.

## Asking for help

Ask early, in the pull request or the group chat.
If you're stuck for more than a day, say so, because a blocker the team can see is much easier to fix than one it can't.
