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
| `sku` | `text` | Required and unique, the lister's initials, the store's date as `MMDDYY` and a two-digit daily sequence, such as `RT11042601`, with the box code added after a space once the item is packed |
| `lister_id` | `uuid` | Required, foreign key to `profiles` |
| `status` | `varchar(32)` | `intake`, `card_ready`, `appraised`, `declined`, `approved`, `held_for_season`, `listed`, `sold` or `picked`, default `intake` |
| `photo_keys` | `text[]` | Storage keys, 1 to 4 of them |
| `photo_hashes` | `text[]` | The SHA-256 of each photo, in the order of `photo_keys`, default empty, and either empty or as long as `photo_keys`, with a GIN index for the repeat photo guard |
| `store_department` | `varchar(32)` | Optional, `clothing` or `electronics_games`, the store department the item came from, which intake asks for |
| `notes` | `text` | Optional |
| `release_month` | `date` | Optional, the first day of the month a held item is released in, which the timing hint sets when the listing is first drafted |
| `package_weight_oz` | `double precision` | Optional, more than 0, the packed weight a manager enters, set together with `box_code` |
| `box_code` | `text` | Optional, one of the Settings box size codes, copied, and added to the SKU after a space |
| `location_code` | `text` | Optional, the shelf or bin, such as `B12-2`, set only once there is a box |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

The box code is copied rather than referenced, so taking a size out of Settings doesn't change the SKU of an item already packed in it.
The initials and the sequence are explained under [`sku_sequences`](#sku_sequences).
The migration that added real SKUs gave each placeholder SKU from the walking skeleton a real one, from its lister's initials and the store's date on the day it was taken in, numbered in the order the items were made.
Items taken in before #9 have no photo hashes and no store department, because their photos were never fingerprinted, so the repeat photo guard never matches them.
The API checks the code against Settings when it is saved, upper-cases the shelf or bin and closes up the spaces around a dash, so `b12 - 2` is saved as `B12-2`.
An approved item whose release month is still to come is `held_for_season`, and it keeps its release month.
`sold` is set by `mark_sold` in `api/app/approval.py`, which the channel sync calls when it records a sale.

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
| `comps` | `jsonb` | Required, default `[]`, the listings the price came from, cheapest first, each with its `title`, `asking_cents`, `condition`, `url` and `outlier`, which is true for a listing the trim left out |
| `created_at` | `timestamptz` | Set by the database |

### `decisions`

Every staff yes or no, kept as a history, so an item can have several.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items` |
| `appraisal_id` | `uuid` | Required, and a foreign key on `appraisal_id` and `item_id` together means it must be an appraisal of the same item |
| `decision` | `varchar(32)` | `yes` or `no` |
| `override_reason` | `text` | Optional, set when staff go against the recommendation, to `wrong_comps`, `better_condition`, `sells_for_more`, `worse_condition`, `sells_for_less`, `hard_to_ship`, `not_genuine` or `other`, which the API checks, while a manager's change on the approval screen writes its own words |
| `note` | `text` | Optional, at most 500 characters from the appraisal screen |
| `decided_by` | `uuid` | Required, foreign key to `profiles` |
| `decided_at` | `timestamptz` | Set by the database, indexed for the recent decisions list |

The foreign keys have no cascade, so a person or an item with history cannot be deleted by accident.
People are deactivated rather than deleted, so their past decisions stay.

### `triage_log`

One row for each staff yes or no on an item forwarded to Ecommerce, written in the same transaction as the decision.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items`, indexed |
| `decision_id` | `uuid` | Required and unique, foreign key to `decisions`, so a decision has one row |
| `submitted_by` | `uuid` | Required, foreign key to `profiles`, indexed, the person who took the item in |
| `store_department` | `varchar(32)` | Optional, copied from the item |
| `outcome` | `varchar(32)` | `accepted` or `rejected` |
| `rejection_reason` | `text` | Required for a rejection and empty for an acceptance, up to 200 characters, which the API checks |
| `destination` | `varchar(32)` | Required for a rejection and empty for an acceptance, `store_floor`, `seasonal_storage` or `discard_or_donate` |
| `recorded_at` | `timestamptz` | The decision's own time, indexed |

The submitter and the department are copied so each row reads on its own.
A manager's reject on the approval screen records a decision but no triage row, because the item was already accepted at triage.

### `sku_sequences`

The last number given out for each SKU prefix, which is the initials and the store's date.

| Column | Type | Rules |
| --- | --- | --- |
| `prefix` | `text` | Primary key, such as `RT110426` |
| `last_value` | `integer` | More than 0 |

Initials are the first letters of the first and last words of the lister's display name, after accents are dropped, so Rosa Maria Torres is `RT` and Ángel Ruiz is `AR`.
A one-word name gives its first two letters, padded with `X`, and a name with no letters gives `XX`.
The date is the store's date in `America/Chicago`, so an item taken in at 8 PM Central is numbered with that day even though it is already the next day in UTC.
Intake bumps the row with one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`, which locks it until the intake commits, so two intakes at once wait for each other rather than sharing a number, and a failed intake gives its number back.
Two people with the same initials share a prefix and so share the day's count, so their items still get different SKUs, but the SKU alone doesn't tell them apart and `lister_id` does.
Past 99 items in one day for one prefix, the number grows to three digits.

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

### `listing_drafts`

The listing text for one item on one channel, which staff edit and then send on to a manager.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items`, and unique with `channel`, so an item has one draft per channel |
| `channel` | `text` | `channel_a` or `channel_b` |
| `title`, `description` | `text` | Required, the text as it stands after any staff edit |
| `category` | `text` | Required, one of the channel's own categories, which the API checks |
| `state` | `text` | `draft`, `awaiting_approval`, `approved` or `rejected`, `draft` by default |
| `source` | `text` | `model` or `template` |
| `fallback_reason` | `text` | `flagged`, `model_failed` or `not_configured`, set exactly when `source` is `template` |
| `model_name` | `text` | Optional, the provider that answered, even when its draft was flagged |
| `model_flags` | `jsonb` | Required, the checker's flags that sent the model's draft to the template, empty by default |
| `staff_edited` | `boolean` | False by default |
| `created_by`, `submitted_by` | `uuid` | Foreign keys to `profiles`, where `submitted_by` is set with `submitted_at` |
| `submitted_at` | `timestamptz` | Required once `state` is past `draft` |
| `price_override_cents` | `integer` | Optional, more than 0, the manager's price for this channel in place of the appraisal's typical price |
| `reviewed_by` | `uuid` | Foreign key to `profiles`, the manager who approved or rejected the listing, set with `reviewed_at` |
| `reviewed_at` | `timestamptz` | Required exactly when `state` is `approved` or `rejected` |
| `created_at`, `updated_at` | `timestamptz` | Set by the database |

The checker's flags on the current text are not stored, because the API works them out from the card whenever a draft is read, so they can't go stale after a card or text edit.

### `settings`

One row per section of the Settings page, holding the values a manager can change without a code change, see [settings.md](settings.md).

| Column | Type | Rules |
| --- | --- | --- |
| `key` | `varchar(32)` | Primary key, `box_sizes`, `seasonal_calendar`, `worth_listing`, `fees`, `ask_to_sale`, `shipping_weight` or `channel_b_fees` |
| `value` | `jsonb` | Required, the section's values, checked by its model in `api/app/store_settings.py` on every write |
| `updated_by` | `uuid` | Optional, references `profiles`, empty until a manager saves the section |
| `updated_at` | `timestamptz` | Set by the database on insert, and by the API on each save, which checks it to refuse a save from a stale page |

The first settings migration seeds six rows with the values the code used before, the manager approval migration seeds `channel_b_fees`, and a section with no row reads as those same values.
`fees` holds Channel A's fees, and keeps its key so the rows saved before Channel B had a section still read.
The seed is a copy written into the migration, so a later change to the code's defaults doesn't change what an old migration does.

### `listings`

One row per item per channel, as Turnstone sees it.
Its `id` is also the `external_ref` the channel stores, so publishing the same listing twice gives back one channel listing.
The status changes only on what the channel has confirmed, so a listing being taken down stays `active`, with an `end_listing` job, until the channel says it has ended.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items`, and unique with `channel`, so an item has at most one listing per channel |
| `channel` | `varchar(32)` | `channel_a` or `channel_b` |
| `channel_listing_id` | `text` | Optional, the channel's own id, empty until the channel confirms the publish, and unique with `channel` |
| `price_cents` | `integer` | Required, above zero |
| `content` | `jsonb` | Required, the listing as sent, or to be sent, so a retried publish sends the same thing |
| `status` | `varchar(32)` | `pending`, `active`, `sold`, `ended`, `rejected` or `failed`, default `pending` |
| `status_detail` | `text` | Optional, why the channel refused the listing or the publish gave up |
| `approved_by` | `uuid` | Required, foreign key to `profiles`, the manager who approved the drafts it was built from |
| `approved_at` | `timestamptz` | Required, when the drafts were approved |
| `published_at`, `sold_at`, `ended_at` | `timestamptz` | Optional, set as the channel confirms each |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

A `rejected` or `failed` listing can be published again, which resets the same row to `pending`.

### `sale_events`

One row per order a channel reported.
The webhook and polling can both report the same order, and the unique `channel` and `channel_order_id` keep it to one row.
Two rows for one item mean a double sale.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `item_id` | `uuid` | Required, foreign key to `items` |
| `listing_id` | `uuid` | Required, foreign key to `listings` |
| `channel` | `varchar(32)` | `channel_a` or `channel_b` |
| `channel_order_id` | `text` | Required, the channel's order id |
| `price_cents` | `integer` | Required, never negative |
| `sold_at` | `timestamptz` | Required, on the channel's clock |
| `source` | `varchar(32)` | `webhook` or `polling`, whichever reported it first |
| `received_at` | `timestamptz` | Set by the database |
| `cancelled_at` | `timestamptz` | Optional, set once the channel confirms it cancelled the order, which only the Needs Attention fix does |

A cancelled order no longer counts toward a double sale.

### `sync_log`

One row for every change sync makes, and one row for every conflict it flags for the Needs Attention screen.
Rows are added and never changed, except that a flag gets its resolution filled in.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `event` | `varchar(32)` | `published`, `publish_rejected`, `publish_failed`, `publish_gave_up`, `publish_skipped`, `sale_recorded`, `delisted`, `delist_failed`, `delist_gave_up`, `delist_found_sold`, `flagged`, `order_cancelled`, `cancel_rejected`, `cancel_failed` or `cancel_gave_up` |
| `channel` | `varchar(32)` | Optional, `channel_a` or `channel_b` |
| `item_id` | `uuid` | Optional, foreign key to `items` |
| `listing_id` | `uuid` | Optional, foreign key to `listings` |
| `channel_listing_id`, `channel_order_id` | `text` | Optional, the channel's own ids, which are all a flag about an unknown listing has |
| `source` | `varchar(32)` | Optional, `webhook` or `polling`, for anything a sale started |
| `message` | `text` | Required, a plain sentence for the log and the Needs Attention screen |
| `detail` | `jsonb` | Required, default `{}`, facts that depend on the event |
| `conflict` | `varchar(32)` | `double_sale`, `stale_listing` or `unknown_listing`, set exactly when `event` is `flagged` |
| `conflict_key` | `text` | Set exactly when `conflict` is, and unique among open flags |
| `resolved_at`, `resolved_by`, `resolution` | `timestamptz`, `uuid`, `text` | Optional, only on flags, with `resolved_by` a foreign key to `profiles` and empty when sync resolved the flag itself |
| `created_at` | `timestamptz` | Set by the database, indexed |

### `jobs`

Background work that is retried until it succeeds or runs out of tries, which is how a channel that was down gets its update later.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `uuid` | Primary key |
| `kind` | `varchar(32)` | `publish_listing`, `end_listing` or `cancel_order` |
| `payload` | `jsonb` | Required, `{"listing_id": "<uuid>"}` for the first two, and for `cancel_order` also `channel_order_id`, the `flag_id` it settles and the `requested_by` profile |
| `status` | `varchar(32)` | `pending`, `done` or `failed`, default `pending` |
| `attempts` | `integer` | Never negative, default 0 |
| `max_attempts` | `integer` | Required, 10 for every kind |
| `run_after` | `timestamptz` | Required, when the job is next due, indexed with `status` |
| `last_error` | `text` | Optional, the latest failure |
| `created_at` | `timestamptz` | Set by the database |
| `updated_at` | `timestamptz` | Maintained by the API through the ORM's `onupdate`, not the database |

A runner claims a due job with `FOR UPDATE SKIP LOCKED` and moves its `run_after` 60 seconds ahead before calling the channel, so a runner that dies mid-call leaves a job that comes due again rather than one that is stuck.
A failed try waits 5 seconds, then 10, 20 and so on up to 5 minutes, and the 10th failure marks the job `failed`.
A channel that refuses a cancel outright marks a `cancel_order` job `failed` straight away, since trying the same cancel again won't change the answer.

### `flag_explanations`

The plain-language explanation and suggested fix shown with one Needs Attention flag, written once per flag.

| Column | Type | Rules |
| --- | --- | --- |
| `flag_id` | `uuid` | Primary key, foreign key to `sync_log`, so a flag has at most one |
| `explanation` | `text` | Required, what went wrong and why it matters |
| `suggested_fix` | `text` | Required, what to do about it |
| `source` | `varchar(32)` | `model` or `template` |
| `fallback_reason` | `varchar(32)` | `flagged`, `model_failed` or `not_configured`, set exactly when `source` is `template` |
| `model_name` | `text` | Optional, the provider that answered, kept even when its text was refused |
| `created_at` | `timestamptz` | Set by the database |

A flag with no row yet shows the fixed sentences in `api/app/flag_explanations.py`, so it never waits on the model to appear.

## Needs Attention flags

The Needs Attention screen reads the open flags with this query:

```sql
SELECT * FROM sync_log
WHERE event = 'flagged' AND resolved_at IS NULL
ORDER BY created_at DESC;
```

Each flag has a `conflict`, a `message` that can be shown as it is, the ids it knows in their own columns, and the rest in `detail`.
Polling finds the same conflict on every run, and the unique `conflict_key` among open flags means it is flagged only once.
Resolving a flag means setting `resolved_at`, `resolved_by` and `resolution` on that row, and if the conflict comes back after that, a new flag is added.

| `conflict` | When | `conflict_key` | `detail` |
| --- | --- | --- | --- |
| `double_sale` | A second channel reports a sale of an item that has already sold | `double_sale:<channel>:<channel order id>` of the later order | `external_ref`, `price_cents` and `sold_at` of the later order, and `other_orders`, a list of `channel`, `channel_order_id`, `listing_id`, `price_cents` and `sold_at` for the earlier ones |
| `stale_listing` | Polling finds a listing live on a channel while Turnstone has the listing as anything but `pending` or `active`, or has the item as `sold` or `picked` | `stale_listing:<channel>:<channel listing id>` | `listing_status`, `item_status`, the channel's `price_cents`, and `taking_down`, true when sync has queued another `end_listing` job |
| `unknown_listing` | A channel reports a sale of, or has live, a listing with no row in `listings` | `unknown_listing:<channel>:order:<order id>` or `unknown_listing:<channel>:listing:<listing id>` | `external_ref`, `price_cents`, and `sold_at` for a sale |

A double sale leaves the item `sold` and both orders in `sale_events`.
The order the buyer paid for first, by the channels' `sold_at` and then `received_at`, keeps the item, and the one-click fix queues a `cancel_order` job for the latest one.
Once the channel confirms, the job sets `cancelled_at`, marks that listing `ended`, logs `order_cancelled`, and resolves the flag with the profile that pressed the fix as `resolved_by`.
Anyone can also mark any flag handled with a note, which becomes its `resolution`.
A stale listing that sync takes down later is resolved by sync itself, with `resolved_by` empty and the resolution "Turnstone took the listing down."

## Mock channel schemas

Each mock channel keeps its own data in its own schema, `channel_a` or `channel_b`, in the same Postgres, and signs in as a role of the same name.
The tables are defined in `api/mock_channel/tables.py` and created by the same Alembic migration as the tables above.

| Table | What it holds |
| --- | --- |
| `listings` | What sellers listed, with the seller's `external_ref` unique, the price above zero, and a status of `active`, `sold` or `ended` |
| `orders` | One per purchase, `paid` or `cancelled`, with at most one paid order per listing, and `acknowledged_at` set once the seller's app has the order |
| `controls` | One row, with the `offline` switch for the demo |

The migration creates each role with no login, grants it only its own schema's tables, and revokes the schema from everyone else.
Row-level security is on for every channel table, with one policy that lets that channel's role in, so another role reaches nothing even if a grant is added by mistake.
`api/app/channel_roles.py` turns on each role's login with a password from `CHANNEL_A_DB_PASSWORD` or `CHANNEL_B_DB_PASSWORD`, so no password is in the repo:

```sh
cd api
CHANNEL_A_DB_PASSWORD=<password> CHANNEL_B_DB_PASSWORD=<password> uv run python -m app.channel_roles
```

It skips a role whose variable is empty, and running it again sets the same passwords, so docker compose runs it on every start.

## Synthetic sales history

The dashboards read a synthetic history from these two tables, because the store has no sales history to show, and every chart drawn from them is labeled synthetic.
They are kept apart from `items`, `listings`, `sale_events` and `sync_log`, so a synthetic sale can never reach the pick list, the sync or Needs Attention.
`uv run python -m app.synthetic_sales` in `api/` replaces both tables with the history from one seed in a single transaction, and the same seed always gives the same rows.
The method, the parameters and how close the history comes to the published figures are in [synthetic-sales.md](synthetic-sales.md).

Days are `date` columns ending in `_on`, because the model runs one day at a time and has no time of day.

### `synthetic_items`

One item forwarded to Ecommerce, with the appraisal's recommendation and the staff call, which the triage funnel reads.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `integer` | Primary key, numbered by the generator in the order the items were forwarded |
| `forwarded_on` | `date` | Required, indexed |
| `store_department` | `varchar(32)` | `clothing` or `electronics_games` |
| `category` | `varchar(32)` | `apparel` or `electronics_games` |
| `department` | `varchar(32)` | `mens`, `womens` or `kids`, and empty unless the category is `apparel` |
| `condition` | `varchar(32)` | `new_with_tags`, `new_without_tags` or `pre_owned` |
| `typical_price_cents` | `integer` | More than 0 |
| `recommendation` | `varchar(32)` | `yes`, `no` or `check` |
| `outcome` | `varchar(32)` | `accepted` or `rejected` |
| `overridden` | `boolean` | True exactly when the staff call went against a yes or a no |

### `synthetic_listings`

One accepted item on one channel, which the time to sell, seasonality and triage funnel views read.

| Column | Type | Rules |
| --- | --- | --- |
| `id` | `integer` | Primary key, numbered by the generator |
| `item_id` | `integer` | Required, foreign key to `synthetic_items`, unique with `channel` |
| `channel` | `varchar(32)` | `channel_a` or `channel_b` |
| `price_cents` | `integer` | More than 0, the asking price and the sale price, because the history has no offers |
| `listed_on` | `date` | Required, indexed |
| `sold_on` | `date` | Set for a sale, on or after `listed_on`, indexed |
| `ended_on` | `date` | Set for a listing that ended unsold, at the end of its 90-day run |

Each listing has exactly one of `sold_on` and `ended_on`, so the days to sell are `sold_on - listed_on` and the sell-through is the share with a `sold_on`.

## Who may read or change what

The website never talks to the database.
Only our API does, and it connects as the owner of the tables.

| Who | Access |
| --- | --- |
| Our API | Reads and writes every table in `public` and enforces the roles in its own code, and it owns the channel schemas because it runs the migrations, but its code reaches a channel only through that channel's seller API |
| Each mock channel | Reads and writes only its own schema's tables, as its own role |
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
