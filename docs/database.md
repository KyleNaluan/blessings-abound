# Database

This page is the agreed design for the tables, and the models in `api/app/models.py` and the migrations in `api/alembic/versions/` are its code.
Update it in the same pull request as any schema change.

The tables follow the data model in the team's project plan, so later migrations add to them rather than rename them.
Money is in integer `_cents` columns, times are `timestamptz` in UTC, and names are `snake_case`, as in [CONTRIBUTING.md](../CONTRIBUTING.md#naming-and-data).
Fixed value lists are text with a check constraint, so a later migration can change a list by swapping the constraint.

## Tables

### `profiles`

One row per person who can sign in.

| Column | Type | Rules |
| --- | --- | --- |
| `auth_user_id` | `uuid` | Primary key, the Supabase Auth user id, with no foreign key to `auth.users` |
| `username` | `text` | Required, unique, only lowercase letters, digits, `.`, `_` and `-` |
| `display_name` | `text` | Required |
| `email` | `text` | Optional, unique when given, lowercase |
| `role` | `varchar(32)` | `staff` or `manager`, default `staff` |
| `is_active` | `boolean` | Default true, false once a manager deactivates the account |
| `must_change_password` | `boolean` | Default false, true while the API should refuse the person until they choose their own password |
| `invited_at` | `timestamptz` | Optional, when a manager emailed an invite, which tells an invited person from one given a temporary password |
| `temporary_password_issued_at` | `timestamptz` | Optional, when Auth accepted the latest temporary password, on Auth's clock, and kept after the person chooses their own so older sessions stay refused |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

### `sign_in_attempts`

One row per username sign-in that was wrong or is still waiting for Auth's answer, which is what `POST /auth/sign-in` counts.
Rows older than the 5 minute window are deleted as new attempts arrive, a right password deletes that username's rows, and an attempt where Auth gave no answer about the password is deleted too.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `username_hash` | `text` | Required, the SHA-256 of the lowercase username, because people sometimes type a password into that box, and indexed with `attempted_at` |
| `attempted_at` | `timestamptz` | Set by the database, indexed for clearing expired rows |

It has no foreign key to `profiles`, because an unknown username has to be limited in the same way as a real one.

### `items`

One row per item, including rejected ones.
Each item is one of a kind.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `sku` | `text` | Required, unique, and a placeholder from the walking skeleton until #37 |
| `lister_id` | `uuid` | Required, foreign key to `profiles` |
| `status` | `varchar(32)` | `intake`, `card_ready`, `appraised`, `declined`, `approved`, `held_for_season`, `listed`, `sold` or `picked`, default `intake` |
| `photo_keys` | `text[]` | Storage keys, 1 to 4 of them |
| `photo_hash` | `text` | Required and indexed for the duplicate guard, not unique because a repeat photo prompts staff rather than being refused, and a placeholder from the walking skeleton until #9 |
| `notes` | `text` | Optional |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

### `item_cards`

The editable card, one per item.
Which optional fields apply depends on the category, and the API checks that rather than the database.

| Column | Type | Rules |
| --- | --- | --- |
| `item_id` | `uuid` | Primary key, foreign key to `items` |
| `category` | `varchar(32)` | `apparel` or `electronics_games` |
| `brand`, `product`, `visible_text` | `text` | Optional, from the vision model and editable by staff |
| `search_query` | `text` | Required, from the vision model and editable by staff |
| `model_confidence` | `varchar(32)` | `low`, `medium` or `high` |
| `condition` | `varchar(32)` | `new_with_tags`, `new_without_tags` or `pre_owned`, from staff |
| `department` | `varchar(32)` | Optional, `mens`, `womens` or `kids`, from staff |
| `size`, `size_type` | `text` | Optional, from staff |
| `flaws` | `text[]` | Any of `stains`, `tears`, `scuffs` and `missing_parts`, default empty |
| `tested_working`, `complete_in_box` | `boolean` | Optional, from staff |
| `accessories_included` | `text` | Optional, from staff |
| `color`, `material`, `exact_model`, `platform` | `text` | Optional, proposed by the model and confirmed by staff |
| `staff_edited` | `boolean` | Default false, true once staff change a field |
| `staff_confirmed` | `boolean` | Default false, true once staff save the card, and needed before a search when the model is unsure |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

### `appraisals`

The computed price and recommendation.
An item can have several, because editing the card and searching again gives a new one.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items` |
| `price_low_cents`, `price_typical_cents`, `price_high_cents` | `integer` | Optional, empty when there are no comps, never negative, and low to typical to high must be in order |
| `net_after_fees_cents` | `integer` | Optional, and the one cents column that may be negative, because fees can exceed the price of a cheap item |
| `comps_count` | `integer` | Never negative, default 0 |
| `confidence` | `varchar(32)` | `low`, `medium` or `high` |
| `recommendation` | `varchar(32)` | `yes`, `no` or `check` |
| `rules_config` | `jsonb` | Required, the rules and config used, under `pricing`, and how the search went, under `search`, with its outcome, query, condition ids and the queries searched |
| `explanation` | `text` | Optional |
| `created_at` | `timestamptz` | Set by the database |

### `decisions`

Every staff yes or no, kept as a history, so an item can have several.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items` |
| `appraisal_id` | `uuid` | Required, and a foreign key on `appraisal_id` and `item_id` together means it must be an appraisal of the same item |
| `decision` | `varchar(32)` | `yes` or `no` |
| `override_reason`, `note` | `text` | Optional |
| `decided_by` | `uuid` | Required, foreign key to `profiles` |
| `decided_at` | `timestamptz` | Set by the database, indexed for the recent decisions list |

The foreign keys have no cascade, so a person or an item with history cannot be deleted by accident.
People are deactivated rather than deleted, so their past decisions stay.

### `comp_searches`

Every SerpApi eBay response, kept so repeats and tests spend no searches.
Code reuses the newest row for a key while it is under 7 days old, and a refresh adds a row instead of replacing one, so the rows fetched this month are the searches spent against the monthly budget.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `engine` | `text` | Required, `ebay` |
| `query` | `text` | Required |
| `condition` | `text` | Required, the eBay condition ids joined with `\|`, as sent in `LH_ItemCondition` |
| `buying_format` | `text` | Required, `BIN` |
| `response` | `jsonb` | Required, the response with any `api_key` removed |
| `fetched_at` | `timestamptz` | Set by the database, indexed with the four key columns for the cache lookup |

It has no foreign keys, because a response belongs to a search and not to an item.

## Who may read or change what

The website never talks to the database.
Only our API does, and it connects as the owner of the tables.

| Who | Access |
| --- | --- |
| Our API | Reads and writes every table, and enforces the roles in its own code |
| Supabase's automatic web API | Nothing, because every table has row-level security turned on with no policies |
| Staff and managers | Only through our API, with the permissions listed in [requirements.md](requirements.md#users-and-roles), which still describes three roles until it is updated |

Any new table needs row-level security turned on in its migration, and a test fails if one is missing.

`profiles` stores the Auth user id as a plain UUID because local Postgres and CI have no `auth.users` table, so a foreign key to it would make the migration run only on Supabase.

## The first manager

`api/app/create_first_manager.py` creates the first manager's Supabase Auth user and profile.
Run it once against the shared demo, after the migrations have been applied there:

```sh
cd api
DATABASE_URL=<Supabase connection string> \
SUPABASE_URL=<project URL> \
SUPABASE_SERVICE_ROLE_KEY=<service role key> \
FIRST_MANAGER_USERNAME=<username> \
FIRST_MANAGER_EMAIL=<email> \
FIRST_MANAGER_PASSWORD=<temporary password> \
uv run python -m app.create_first_manager
```

These can also go in the root `.env`.
Keep the password out of the repo and out of anything you paste.

It is safe to run again:

- If the manager already exists, it changes nothing and says so, and the password is not needed.
- If an earlier run created the Auth user but stopped before the profile, it keeps that user and its password and adds the profile.
- If an existing account disagrees with the settings, it changes nothing and exits with an error, and the same goes for an Auth user with that email whose address is unconfirmed.
- If `DATABASE_URL` and `SUPABASE_URL` point at different environments, one local and one hosted, it refuses to start.

## A local profile

The API refuses anyone without an active profile, and `api/app/seed_local_profile.py` gives an existing Auth user a profile on a developer's own database, as the [README](../README.md#setup) shows.
It refuses any database that isn't local, so it can't touch the shared demo.

## Demo accounts

`api/app/seed_demo_accounts.py` creates one demo staff account and one demo manager account for judging.
The passwords come from the environment, so none are in the repo:

```sh
cd api
DATABASE_URL=<Supabase connection string> \
SUPABASE_URL=<project URL> \
SUPABASE_SERVICE_ROLE_KEY=<service role key> \
DEMO_STAFF_PASSWORD=<password> \
DEMO_MANAGER_PASSWORD=<password> \
uv run python -m app.seed_demo_accounts
```

The usernames are `demo.staff` and `demo.manager` unless `DEMO_STAFF_USERNAME` or `DEMO_MANAGER_USERNAME` says otherwise.
Running it again puts these passwords back and turns the accounts back on, so a judge's changes don't carry over to the next judge.
It refuses to change a username that already belongs to a real person with a different role, and it refuses mixed local and hosted settings as the first manager script does.

## Accounts

Nobody can sign themselves up, because the app has no sign-up route or form and a new Auth user with no profile gets a 403 from every API route.
The Supabase setting **Allow new users to sign up** should also be off so that a sign-up attempt fails at Auth, and `seed_demo_accounts` prints a warning if it finds that setting on.

The API routes under `/team` are for managers only, and they check the role on the server for every request:

| Route | What it does |
| --- | --- |
| `GET /team/people` | Lists everyone with their role and status |
| `POST /team/people/invite` | Emails an invite, and the person chooses a password from the link |
| `POST /team/people/temporary-password` | Creates a username, with an email or without one, and returns a temporary password once |
| `POST /team/people/{id}/temporary-password` | Replaces a person's password with a new temporary one |
| `PATCH /team/people/{id}` | Changes the role |
| `POST /team/people/{id}/deactivate` | Bans the person in Auth and marks the profile inactive, keeping their decisions |
| `POST /team/people/{id}/reactivate` | Lifts the ban and marks the profile active |

Nobody can deactivate themselves, and nobody can deactivate or demote the last active manager.
A person with no email gets a hidden address at `accounts.turnstone.invalid`, which only Auth ever sees, because Auth needs an address and `.invalid` can never receive mail.
The `email` column stays empty for that person.

While `must_change_password` is true, the API answers every signed-in route with a 403 except `GET /me` and `POST /me/password`, and the web app sends the person to the Choose your password page.
The flag lives in `profiles` rather than in Auth's user metadata, because a signed-in person can write their own metadata from the browser.

Every signed-in route answers a 401 for a token issued before `temporary_password_issued_at`, including `POST /me/password`, so a session opened before a reissue can't set the new password.
Auth ended those sessions itself when we tested version 2.197.0, and this check keeps the rule on our side too.
Tokens record whole seconds, so a token from the same second as the reissue still passes.

A username sign-in goes to `POST /auth/sign-in`, where the API finds the person's Auth address, so that address never reaches the browser.
An email sign-in goes straight from the browser to Supabase, as it did before, and any existing Auth address keeps working this way.

A wrong password, an unknown username and a turned-off account all get the same answer on both paths, so sign-in can't show that a password was right.
A person who was already signed in when they were deactivated still gets a clear message from the API, because they have already proved who they are.

After 10 wrong passwords in 5 minutes, `POST /auth/sign-in` answers a 429 for that username without asking Auth, until the oldest of them is 5 minutes old or the right password has cleared them.
The count is in `sign_in_attempts`, so it survives a restart and is shared by every API process.
Supabase Auth has its own limit on email sign-ins, which come straight from the browser and don't pass through this count.
