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
| Auth | Supabase Auth, with a plain UUID login ID, display name and role in `profiles` | The API enforces the two roles, staff and manager, and row-level security blocks all other access. Accounts are invite-only, see [docs/database.md](database.md#accounts). |
| Mock channels | Two separate FastAPI services on Render, each with its own database role and schema, `channel_a` and `channel_b` | They stand in for real platforms behind an adapter interface, and they keep their data in Postgres, so it survives restarts on free hosts. |
| Background work | An in-process scheduler and a `jobs` table in Postgres | It handles polling, retries and AI calls without a separate worker to host. |
| Photo storage | Local folder or Supabase Storage | One interface in `api/app/storage.py`, with the backend picked by settings. |
| Hosting | Cloudflare Pages for the frontend, Render for the API and mock channels, Supabase for the database and photos | Each has a free tier that fits a student demo. |
| Keeping the demo up | A scheduled GitHub Actions ping on our self-hosted runner, and an offline `docker compose` demo with a local stand-in and fixture responses | An idle free service stops polling and can miss webhooks, and the offline demo works with no keys or Wi-Fi. |
| Python tooling | ruff and pyright | Fast lint, format and type checks with little configuration. |
| Frontend tooling | ESLint, Prettier, `tsc` and Vitest | The standard checks for a Vite and React project. |
| Checks | pre-commit hooks and GitHub Actions | The same lint, type checks and tests run on every commit and every pull request. |

## Environments

| | Development and tests | Shared demo |
| --- | --- | --- |
| Database | Postgres 17 in Docker Compose | Supabase Postgres 17 |
| Photo storage | Local folder | Supabase Storage |
| API | `docker compose up` on each laptop | Render, one service today, up to three with the two mock channels |
| Frontend | `npm run dev` on each laptop | Cloudflare Pages |

Development and tests use a local database, so each of us can reset data and run migrations without touching the shared demo or needing a network connection.
CI starts its own Postgres for the same reason.
The demo reads its connection details from environment variables, so the code is the same in both places.

The Cloudflare Pages project `blessings-abound` builds the frontend from `main` with root directory `web`, build command `npm run build` and output directory `dist`, and serves it at https://blessings-abound.pages.dev.
Every pull request gets its own preview link from Pages, and nobody needs a Cloudflare account to open it.
The build uses the Node version in `web/.nvmrc`, and `VITE_API_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are in the Pages project's production environment variables.
The API runs as the free Render service `blessings-abound-api` at https://blessings-abound-api.onrender.com, and the steps are in the [README](../README.md#hosted-demo).
Each site's `/choose-password` address must be in the Supabase Auth redirect list for reset and invite links to work.
Pages serves `index.html` for any path without a file, because the build has no `404.html`, so the app needs no rewrite config.

The hosted demo follows these steps:

- Connect to Supabase with the session pooler on port 5432, which works over IPv4, because the transaction pooler needs prepared statements disabled for psycopg (`prepare_threshold=None`).
- Start each Render service with `alembic upgrade head && uvicorn ...`, which is the command in `api/Dockerfile`, so Supabase receives migrations only after merge.
- Before judging, reset the demo data with a rerunnable seed script, compare the structure with `pg_dump --schema-only`, and back up Supabase the day before.
- Wake Supabase and every Render service before judging, because free Supabase projects pause after about a week of inactivity.

## Pricing pipeline

Each step is a board issue, and so far step 1, the item card in step 2 and steps 3 to 9 are built, and `POST /items/{id}/appraisals` runs steps 3 to 10 through `price_item` in `api/app/pipeline.py`.
The item card in step 2 is read, edited and confirmed by staff, and the SerpApi lookup in step 4 is the active Buy It Now search with its 7 day cache and the drop-a-word fallback.
Steps 5 to 9 are built as pure functions in `api/app/comp_filter.py` and `api/app/pricing.py`, with their numbers in `PricingRules` in `api/app/settings.py`.
The worth-listing threshold, the fees and the ask-to-sale factors start from those numbers, and an appraisal reads them from the manager-only Settings page, described in [settings.md](settings.md).
Step 10's language model is not built, so the explanation is the code template it falls back to.
The other steps are not built yet.
The language model never produces a price, and every number comes from code over comps, which are similar items for sale on eBay.

1. Staff upload 1 required photo and up to 4, and a code-only blur and brightness check prompts a retake.
   Staff enter the store department the item came from, the condition grade, using eBay's values, and any flaws, plus the department, size and size type for apparel and shoes, or tested and working, complete-in-box and accessories for electronics and games.
   Those come from staff, never from the model.
   `POST /items` reads each photo's type from its own bytes, takes JPEG, PNG and WebP up to 15 MB, refuses anything else with a message that names the photo, and stores a SHA-256 hash of each one.
   A photo that matches an item whose latest triage call was a rejection gets a 409 with that item's SKU, reason and destination, and nothing is stored, so staff check the item and send it again with `allow_repeat` to take it in anyway.
   Before that check, `photo_retake_reason` in `api/app/pipeline.py` measures each photo for blur and brightness, as [Photo check](#photo-check) describes.
   A photo that fails gets a 409 that names each photo and what is wrong with it, and nothing is stored, so staff take it again or send it again with `keep_photos` to use it anyway.
   The item then gets its SKU, as [`sku_sequences`](database.md#sku_sequences) describes.
2. The vision model turns the photos and staff entries into an item card with the category, brand, product, any visible text, a search query and its own confidence, and it proposes the color, material, exact model and platform for staff to confirm.
   Staff can edit the card before any search is spent, with `PATCH /items/{id}/card`, which also confirms it.
   Once the card is read, and again if staff change its brand or product, the appraisal page asks `GET /items/{id}/kept-off-matches` for earlier items that are `not_listed_online` and share a photo with this one or have the same brand and product, ignoring case and spaces at the ends.
   Each match shows in a warning in the same place and style as the rejected photo warning, with who kept it off online, when and their note, and a manager gets a link to its review.
   The warning never stops the item, so staff choose Carry on and keep going, and an item a manager has put back for review no longer matches.
   The appraisal step refuses a card with no brand or with a model confidence below `ITEM_CARD_MIN_CONFIDENCE`, default `medium`, until staff confirm it.
   Any staff entry the model sends back is dropped, and photos go to the model as upright JPEGs at most 960 pixels on the long side.
3. Code builds the eBay search from the card's search query, with condition ids for the card's condition and for whether it is a video game.
   A pre-owned item searches `3000`, or `2750|4000|5000|6000` for a video game, new with tags searches `1000`, and new without tags searches `1500`, or `2750` for a video game.
4. SerpApi's eBay engine returns active Buy It Now listings filtered by condition, and if fewer than 8 survive the filters, code drops the last query word and searches again, at most twice.
5. Code filters the listings by title, dropping accessories, lots, parts and similar matches unless the item itself is one of those.
   Department, tall, plus and petite sizes, and complete in box are judged against the staff entries, a plain size never drops a listing, and each dropped listing keeps its reason.
   A listing returned more than once is dropped by its item id with reason DUPLICATE, so one listing cannot weigh twice in the percentiles.
6. Code trims outliers with Tukey fences on log price, skipped when fewer than 4 listings remain, and takes the low, typical and high price from the percentiles.
   Apparel uses the 25th, 50th and 75th, and games and hardware use the 15th, 50th and 85th.
7. Asking prices run higher than sale prices, so code multiplies the range by an ask-to-sale factor from the Settings page, which is one value per category rather than one per channel, because comps always come from eBay.
   Apparel's 0.645 is labeled an assumption, because it comes from Poshmark data with ratios from 1.21 to 2.93, and a re-measure on eBay is a stretch item done by hand.
   The 0.94 for games and hardware is also labeled an assumption, because it comes from 18 items in [evaluation.md](evaluation.md).
8. Confidence is high with at least 10 listings left after the trim and a ratio of at most 2 between the 75th and 25th percentiles, medium with at least 5 and a ratio of at most 3, and low otherwise.
9. The worth-listing rule says "yes" when the typical sale price is at least $30, "no" below it, and "check" when confidence is low or there are no comps, and the threshold, fees and supplies are set on the Settings page.
   The net after eBay's fees, which are 13.6% for most categories plus $0.40 per order, and $1.50 for supplies is shown beside it.
10. The language model writes a 2 to 3 sentence explanation from the computed numbers only, and code rejects the text if it contains any number that is not in those facts and falls back to a template.

When the budget is spent, the search fails, no key is set or no usable comps remain, the appraisal is still saved, with no prices, confidence low, the recommendation "check" and an explanation that says which of those happened.

Staff see the range, the comps as links, the confidence and the recommendation, and they make the final call, which the app saves.
Each appraisal keeps the listings it was priced from in its `comps` column, cheapest first, with each one's title, asking price, condition, link and whether the trim left it out, so the screen shows the same evidence later that staff saw on the day.
The screen shows 6 of them spread from the cheapest to the dearest, and staff can open the rest.
If they disagree with the recommendation they choose a reason from a dropdown and may add a note, and "Something else" needs the note.
A call disagrees when the recommendation is yes or no and staff choose the other, while a "check" has no side, so any call on it agrees.
The reasons for a yes against a no are that the listings aren't the same item, that it's in better shape than the listings, that the store knows it sells for more, or something else.
The reasons for a no against a yes are that the listings aren't the same item, that it's in worse shape than the listings, that the store knows it sells for less, that it's too big or heavy to ship for the price, that it may not be genuine, or something else.
They are the ways the price can be wrong that staff can see and the code can't, which is the wrong comps, a condition the photos don't show, the store's own sales, shipping, and fakes.
A no needs a reason and a destination, which is the store floor, seasonal storage, or discard or donate onward, and a no against the recommendation gives its dropdown reason, or its note for "Something else", as the triage log's reason.
Every yes and no is written to the triage log with the person who took the item in, its store department, the date, and for a no the reason and destination.

Comps come through SerpApi rather than eBay's own API, because eBay's API license does not allow using its content to suggest or model prices.
SerpApi's free plan allows 250 searches a month and 50 an hour, so every response is cached in a `comp_searches` table, keyed by the engine, query, condition and buying format, and reused for 7 days.
Tests read committed fixture responses and never call SerpApi.

## Photo check

The blur and brightness check in `api/app/photo_check.py` is plain code with Pillow and makes no model call.
It scales each photo to 640 pixels on the long side and turns it gray.
Sharpness is the variance of the Laplacian, which is large across a sharp edge and near zero on a smooth area, taken on the sharpest of 8 by 8 pieces of the photo, so a plain backdrop around a sharp item doesn't count against it.
Brightness is read from the brightest and the darkest 5% of pixels, so a few glints or shadows don't decide it.
A photo is too dark when even its brightest 5% is below 100 out of 255, washed out when even its darkest 5% is above 210, and blurry when its sharpness is below 100.
Brightness is checked first, because a dark photo shows no edges and would also read as blurry.
The numbers are `PhotoChecks` in `api/app/settings.py`, each with its reason.

Checked on 2026-11-05 with 53 photos, which are the 48 in [evaluation.md](evaluation.md) and the 5 in [Vision model check](#vision-model-check), each measured as it is and with blur and darkness added in code.

| Version of each photo | Lowest and highest sharpness | Brightest 5% | Darkest 5% | Prompted to retake |
| --- | --- | --- | --- | --- |
| As it is | 129 to 13,606 | 163 to 255 | 6 to 183 | 0 of 53 |
| Blurred by 1 pixel | 25 to 589 | 158 to 255 | 6 to 183 | 14 of 53 |
| Blurred by 1.5 pixels | 10 to 136 | 155 to 255 | 7 to 183 | 48 of 53 |
| Blurred by 2 pixels | 6 to 55 | 153 to 255 | 7 to 183 | 53 of 53 |
| At 35% of its light | 19 to 1,695 | 57 to 89 | 2 to 64 | 53 of 53 |
| At 20% of its light | 8 to 639 | 32 to 51 | 1 to 36 | 53 of 53 |

- The blur is a Gaussian blur with its radius measured at the 640 pixel size, and the darker versions scale every pixel's light down.
- The sharpness line of 100 sits between the lowest sharp photo at 129 and the highest 2 pixel blur at 55, so a 1 pixel blur passes on most photos and the prompt is kept for a photo that is clearly blurry.
- Most of the photos are studio shots with white backdrops, and the highest darkest 5% among them was 183, so a white item on white stays below the washed-out line of 210.
- Brightening the photos 1.8, 2.5 and 3.5 times in code prompted only 4, 9 and 12 of 53, because brightening clips the light parts to white but leaves the darkest 5% below the line on most photos, so the washed-out line catches a photo that is light all over rather than one with a bright patch.
- None of the photos is from a thrift store floor, so the lines are a starting point to check against the store's own photos.

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

## Channel and timing recommendation

After a yes decision, `GET /items/{id}/channels` says which channels can take the item, whether to list it now or hold it for its season, and why in one sentence.
Code in `api/app/channel_timing.py` decides the channels and the timing, and the model only words the reason.
Staff then choose the channels on the item screen, and the recommendation only suggests.

The channel rules are:

- A channel takes an item when it has listing categories for the item's category in `CHANNEL_CATEGORIES` in `api/app/listing_drafts.py`, so Channel A takes every item and Channel B takes apparel only.
- A channel refuses an item when the card leaves out a field the channel needs, in `CHANNEL_REQUIRED` beside it, so Channel B refuses an item with no brand, as its mock service does.
- Every channel that can take the item is recommended, and a channel that can't is shown with the reason, and staff can't choose it.

The timing rules read the seasonal calendar from [Settings](settings.md#seasonal-calendar) on every request:

- A season matches when one of its words is on the card's brand, product, exact model, material or visible text, as a whole word or phrase, with a plural allowed, so "boot" matches "Boots" and "flip flop" matches "flip-flops".
- Only a season for the item's category can match, the first one in the calendar that matches is used, and an item that matches none is listed now.
- When today's month, in UTC, is one of the season's months, the item is listed now.
- Otherwise it is held until the first day of the season's next month, which is in the next year when the season starts after today's month, so a jacket in March is held until August.

The reason is written by the same pair of models as the listing drafts, through `complete_json` in `api/app/ai.py`.
The prompt is `PROMPT` in `api/app/channel_timing.py`, and it holds the item, each channel's answer, the season and the timing, and a fixed sentence that says the same, which the model rewords in at most 200 characters.
The reply is refused when it has a month or a number the facts don't, or more than one line.
When there is no model set up, when both models fail or are refused, or when no reply comes in 8 seconds, the screen shows the fixed sentence instead, with a note saying why, so the recommendation always shows.
The reason is worked out again on each request and not stored.

`POST /items/{id}/drafts` takes the channels staff chose and refuses with a 422, and the reason, any channel that can't take the item.
The first drafting also sets the item's `release_month` from the timing, so an item held for its season becomes `held_for_season` when a manager approves it, as [Manager approval and storage](#manager-approval-and-storage) describes, and an item listed now has none.
Where the hint says to hold the item, the appraisal page also offers Don't list online, which takes the item out of online selling until a manager puts it back for review, as [Held for season](#held-for-season) describes.
Once an item has drafts, asking again returns them, whatever channels the request names, so the choice is made once.

## Listing drafts

After staff choose the channels, `POST /items/{id}/drafts` writes a title, description and category for each chosen channel, `PATCH /items/{id}/drafts/{channel}` saves staff's edits, and `POST /items/{id}/drafts/submit` sends the drafts on to manager approval.
A draft is stored in `listing_drafts` with the state `draft`, and sending it sets `awaiting_approval`, which is the state the [manager approval](#manager-approval-and-storage) step reads.

The model is the same pair as the item card, Groq `qwen/qwen3.8-27b` with Gemini `gemini-3.5-flash` as the fallback, through `complete_json` in `api/app/ai.py`.
It asks for a JSON object, retries a bad reply once on the same provider and falls back at once on an HTTP error.
The prompt is `PROMPT` in `api/app/listing_drafts.py`, sent as one user message, and it holds:

- a line on the channel, plain and searchable for Channel A and relaxed for Channel B,
- the facts, which are the card's fields and the staff entries, leaving out anything nobody recorded,
- rules that forbid any brand, number, size, condition, flaw, working or box claim the facts don't support, built per item, so an item tested as working may say so and one with no record may not,
- the banned words, and
- the JSON keys, with the channel's own categories to copy one from.

The rule-based checker in `api/app/claims.py` reads the model's title and description apart, so a "not" in one can't excuse the other, and flags:

- a banned word, such as rare, authentic, antique, vintage, mint or official, unless it is on the card,
- a brand, system or product line the card doesn't name, where a product line counts for its maker, so "Switch" is fine on a Nintendo card,
- a letter size, a size after the word "size", a fit such as slim or oversized, or a department, that the card doesn't give,
- a number or number word that isn't on the card, and
- a condition claim the card or staff entries don't support, such as new, sealed, tested, complete in box or a flaw, where a "not" or "no" up to three words before it in the same clause makes it a statement the card allows, except for grades such as "no flaws".

Words in double quotes that are on the card, such as the text printed on the item, are read as a copy of the card and not as a claim, and the prompt asks the model to quote that text after "It reads".

A flagged draft, or no usable reply from either model, falls back to the fixed template in `template_draft`, which only restates the card, and the stored row keeps the checker's flags so staff can see why.
Staff can edit either one, and the API checks the text again on every read, so the item screen shows the flags as they stand and sending is refused while any remain.
On the 48 evaluation items, which are all games and hardware for Channel A, 46 of the model's drafts passed the checker, 95.8%, measured once on 2026-11-03.
The 2 flagged drafts said "sold as is" and "no record of it being tested", which the card doesn't say either.
[listing-drafts.md](listing-drafts.md) has each draft and the limits of that sample.

## Manager approval and storage

`api/app/approval.py` holds the manager's step after the listing drafts and the storage step after approval, and the web pages are `/app/approvals`, `/app/approvals/{id}` and `/app/pick-list`.
Every route except the pick list is for managers only, and staff get a 403 with "Only a manager can do this."

1. `GET /approvals` lists the items whose drafts staff sent on, oldest first, the approved items that have no shelf or bin yet, and the items held for their season, soonest release month first.
2. `GET /items/{id}/review` shows each channel's listing with its typical sale price, its listing price and the net after that channel's fees, worked out in integer cents from the Settings fees on every read.
3. `PUT /items/{id}/listings/{channel}/price` sets a channel's price in place of the typical price, or clears it, while the listing waits for approval.
4. `PUT /items/{id}/storage` saves the package weight and a box size from Settings, before or after approval, and the shelf or bin once the item is approved.
   The weight is held to the Settings shipping weight limit, and the review shows the weight the label is billed at.
   Saving the shelf or bin of an `approved` item lists it on the channels, as [Mock channels and sync](#mock-channels-and-sync) describes.
5. `POST /items/{id}/approve` approves every listing, and is refused with the reasons while a listing has a flag or no price, or while Channel A has no weight and box size.
   An item whose release month is still to come becomes `held_for_season` and keeps that month, and any other item becomes `approved`.
6. `POST /items/{id}/reject` needs a reason, marks the listings `rejected`, records a manager's no in `decisions` and sets the item to `declined`, so it never needs a package or shelf.
   Staff can say yes again from the appraisal page, which puts the rejected listings back to `draft` with their text kept, so staff can fix them and send them on again.
7. `GET /pick-list` lists the sold items for staff and managers, grouped by box in the order Settings lists the boxes, then by shelf or bin, so A2 comes before A10, and `POST /items/{id}/picked` takes one off.

The full SKU is the intake SKU, a space and the box code, such as `RT10272601 12x12x6`, and the API builds it from the two columns rather than storing it.
The intake SKU is the lister's initials, the store's date and a daily sequence, as [`sku_sequences`](database.md#sku_sequences) describes.
An item reaches the pick list once its status is `sold`, which only `mark_sold` sets.
A sale that the channel sync records calls `mark_sold`, as [Mock channels and sync](#mock-channels-and-sync) describes.

### Held for season

An item `held_for_season` stays out of every channel until a manager looks at it again, because its price was approved months before it can sell.
Nothing moves it on a timer.
`back_for_review` in `api/app/approval.py` works it out on each read, and it's true once the item's release month is this month or earlier.
The item keeps its `held_for_season` status until a manager acts on it.

1. Before its release month, the item is in the queue's held list and the review page offers List now and Don't list online.
   Approving, repricing and rejecting it are refused with a 409 until it's back for review.
2. `POST /items/{id}/list-now` brings it back early by setting its release month to this month, and records a yes in `decisions` with the month it had.
3. Once it's back for review, the queue lists it with the items waiting for approval, and the review page calls `POST /items/{id}/fresh-comps`.
   That runs the same comparable sales lookup as an appraisal, `price_item` in `api/app/pipeline.py`, and saves the result as a new appraisal next to the approved one.
   The listings keep their approved prices, because each decision still points at the appraisal the item was approved on.
   Asking again returns the same lookup rather than searching again.
4. The manager can change a channel's price, then approve it with `POST /items/{id}/approve`, which sets it to `approved`, records a yes with the prices, and publishes it if it already has a shelf, as an `approved` item is published.
   An item with no shelf yet goes to the storage queue and is published once a manager saves its shelf.
   Rejecting it works as for any other listing.
5. `POST /items/{id}/not-online` takes the item out of online selling, with a note of up to 200 characters, and sets it to `not_listed_online`, which only a manager putting it back moves on from.
   It records a no with "Not listed online" and the note.
   Staff can do it from the timing hint on the appraisal page, where the item is still `appraised`, and a manager can do it from the review page or the held list.
   A held item needs a manager.
   The approvals page lists the latest 50 of these items under Not listed online, newest first, with who kept each one off, when and why.
6. `POST /items/{id}/put-back` lets a manager undo Don't list online, right after or any time later, from that list or the item's review page.
   It needs a note of up to 200 characters, records a yes with "Put back for review" and the note, and sends the item back to Waiting for approval, so nothing is published until a manager reviews it again.
   An item whose listings were already approved goes back to `held_for_season` with this month as its release month, so it comes back for review with a fresh comparable sales lookup made after it was put back, and approving it publishes it as step 4 does.
   An item kept off before approval goes back to `appraised`, with its listings still waiting, and is approved as usual.
   An item kept off before staff sent its listing goes back to `appraised` with no listings, and the manager writes and sends the listing from the review page before approving it.

Every one of these choices is a row in `decisions` with who made it and when, and the review page shows them all in a History panel, oldest first.

## Mock channels and sync

Channel A is an eBay-style marketplace that takes clothing, electronics and games, and Channel B is a Depop or Poshmark-style resale app that takes clothing only and needs a brand.
Each is a small FastAPI service in `api/mock_channel/`, built from one shared app in `service.py`, with its own database role and schema, as [database.md](database.md#mock-channel-schemas) describes.
Each channel takes the categories in `CHANNEL_CATEGORIES` in `api/app/listing_drafts.py`, which are the names the drafts choose from, and a test keeps the two lists the same.
Each channel has a seller API under `/api` that the main app calls with the channel key, a storefront at `/` where anyone can buy a listing, and an `/admin` page behind the channel key that switches the channel offline for the demo.

The main app talks to a channel only through the `ChannelAdapter` interface in `api/app/channels.py`, and `MockChannelAdapter` is the one implementation, so a real platform would be a second adapter.
The sync rules are in `api/app/sync.py`, and they work like this:

1. Saving the shelf or bin of an `approved` item calls `publish_approved` in `api/app/approval.py`, which builds a listing from the approved draft for each channel set up on the server, at the price on the review page, and `publish_item` in `api/app/jobs.py` adds one `pending` listing per channel and one `publish_listing` job each.
   The scheduler runs those jobs within seconds, and the first confirmed listing moves the item to `listed`.
   An item `held_for_season` gets its shelf but isn't published until a manager approves it again in its release month, as [Held for season](#held-for-season) describes.
   A channel that refuses the listing, such as Channel B with no brand, leaves it `rejected` with the channel's reason, and a channel that is down gets the job retried.
2. A purchase on a storefront sends a webhook to `POST /channels/<channel>/sales`, signed with HMAC-SHA256 over the body with the channel key, and a 2xx answer marks the order acknowledged on the channel.
3. A scheduler thread in the API polls each channel every 30 seconds for orders not yet acknowledged and for its live listings, so a webhook that never arrived is caught by polling.
4. `record_sale` keeps each order once in `sale_events`, marks the item sold with `mark_sold`, which puts it on the pick list, and queues an `end_listing` job for every other live listing of that item.
5. The same thread runs due jobs every 2 seconds, and a failed try waits 5 seconds, then 10, 20 and so on up to 5 minutes, for at most 10 tries.
6. A second sale of an item that has already sold, a listing still live after Turnstone took it down, and a listing or sale Turnstone has no record of are each flagged in `sync_log` for the Needs Attention screen, in the shape [database.md](database.md#needs-attention-flags) describes.

Every change goes in `sync_log`, along with every flag.
Turnstone's own records change only on what a channel has confirmed, so a listing being taken down stays `active` until the channel answers.

The review page shows where each approved listing is on its channel, and asks again every 2 seconds while one is still `pending`.
`POST /items/{id}/listings` sends a `rejected` or `failed` listing again and runs its job before answering, and the review page offers it for a `failed` one, because a channel that was down may be back.
`api/app/jobs.py` holds only what adds rows to `jobs`, so the approval step can queue a publish while the sync calls back into `mark_sold`, with no import cycle.

## Needs Attention

The Needs Attention screen at `/app/attention` lists the open flags from `sync_log`, newest first, and the latest 20 that someone or sync resolved, through `GET /attention` in `api/app/attention.py`.
Staff and managers both see it and can fix a flag, as [requirements.md](requirements.md#users-and-roles) lists, because a double sale or a stale listing needs settling before a manager is next in.
Missing required information isn't a check here, because the listing form won't send a draft for approval until it is filled in.

Code finds every conflict and decides what to do about it, and `template_text` in `api/app/flag_explanations.py` puts that in fixed sentences.
The model only rewords those sentences for staff, and it is the same pair as the drafts, through `complete_json`.
The prompt is `PROMPT` in the same file, sent as one user message, and it holds the kind of problem, the item, the channels, and the fixed sentences as the "Problem" and "Fix" it must keep, with no prices, times or order numbers.
A reply with a number the facts don't have, a failed or slow call, or no model set up all fall back to the fixed sentences, and `flag_explanations` records which one was shown and why.
A flag shows the fixed sentences until its explanation is written, so a flag is never hidden by the model.
The explanations are written on a second scheduler thread every 2 seconds, so a slow model never holds up polling or a delist.

A double sale is fixed in one click with `POST /attention/{id}/fix`.
The order the buyer paid for first, by the channels' own sale times, keeps the item, and the later order is cancelled through `cancel_order` on the `ChannelAdapter`, which refunds that buyer on the mock channel.
The cancel is a `cancel_order` job, run before the reply so the screen shows what the channel said, and a channel that is down gets it retried like any other job while the screen shows each try.
A channel that refuses the cancel stops the job at once, and the button comes back so someone can try again.
Any flag can also be marked handled with `POST /attention/{id}/resolve` and a note on what was done, which becomes the flag's resolution in `sync_log`.

## Sales dashboards

The Dashboards page at `/app/dashboards` is for managers, and it gets every number from one call, `GET /dashboards` in `api/app/dashboards.py`, which refuses staff.
It has four views, and each one puts the synthetic history and the live test sales on separate charts.

1. Time to sell gives the middle days to sell of each category and price band in the synthetic history, with how many listings sold, and the middle hours from a confirmed listing to its first standing sale on the mock channels.
2. Seasonality gives each month's synthetic sales for every 100 listings up a week, which divides by the days listings were up rather than counting sales, so the months when the history was filling up or running out don't look slow.
3. The triage funnel follows each synthetic item from forwarded to accepted, listed and sold within the 90-day run, and each real item from intake to its newest triage call, a confirmed listing and a sale.
   Under each funnel is how often staff went against a yes or a no from the appraisal, with a check left out because it has no side.
4. Sync health counts what `sync_log` recorded for publishing, hearing about sales and taking listings down, and agreement counts the open and settled flags of each kind, the items with two standing orders, and the jobs waiting or given up.

Every chart says where its numbers come from in its caption.
A chart from the history says "Synthetic history." and a chart from the mock channels says "Synthetic, live.", because those sales are test events on fictional channels and not real buyers.
A view with nothing to draw says so in a sentence, so an empty table never looks like a slow month.
The charts are bars and one line chart drawn in `web/src/pages/dashboards/charts.tsx`, with every bar's number as text beside it and the line chart's numbers in a table under it.

## Sales insight chat

A manager can ask a sales question in plain English in the "Ask about sales" section at the top of the Dashboards page, which sends it to `POST /dashboards/ask` in `api/app/insight.py`, and staff get a 403.
The model never writes a query or a number of its own, and each question takes two model calls on the same providers as the item card.

1. The model picks one function from a fixed set, with its inputs, or answers that none covers the question.
   The functions are `time_to_sell`, `time_to_sell_by_band`, `seasonality`, `triage_funnel`, `live_sales` and `sync_health`, and each one calls the same queries as the dashboards in `api/app/dashboards.py`.
   An input the function doesn't take is dropped, and a price band out of range counts as a bad reply, which gets a retry like any other.
2. Code runs the function and returns its numbers as labeled facts and a sentence of its own.
3. The model words an answer from those numbers alone.

The number check then takes every number in the model's wording, and any that the function's call and facts don't contain makes the answer fall back to code's own sentence, with the refused numbers shown under it.
A number from the question counts against the wording too, because a manager could ask about a figure the history doesn't have.
If the wording call fails, code's sentence stands in with a note saying so, and a question no function covers gets a fixed sentence listing what the chat can answer, without a second model call.

Each answer shows the function call it came from, such as `time_to_sell(category="apparel", price_band=2)`, with the facts in a table under "Show the numbers".
An answer from the history is labeled "Synthetic history." and one from the mock channels "Synthetic, live.", with the same caption component as the charts.
The answers live only on the page, so nothing is stored and no migration was needed.

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
- 2026-10-29: Keep one ask-to-sale factor of 0.645, labeled an assumption, instead of one per channel, because comps always come from eBay. Games and hardware got their own factor on 2026-11-01, see below.
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
- 2026-11-01: Make saving the card with `PATCH /items/{id}/card` the confirmation, with no separate route, because staff have read what they save and one call is all the screen needs.
- 2026-11-01: Treat a card with no brand like one with low confidence, because a search without a brand spends quota on a vague query, and keep one `model_confidence` rather than one for the brand and one for the model, because the schema has one and the prompt defines it over both.
- 2026-11-01: Resize photos with Pillow before the vision call, because the 2,300 tokens per photo in the vision check assumes 960 pixels and a full-size phone photo would hit the provider's limits.
- 2026-11-01: Keep an item `appraised` after a yes and set it to `declined` after a no, because no status means "staff said yes" and `approved` belongs to the manager step.
- 2026-11-01: Add a new `comp_searches` row on every refresh instead of overwriting the cached one, so the rows of the current month are the count of searches spent against `SERPAPI_MONTHLY_BUDGET` (default 240 of the free plan's 250), and the lookup refuses cleanly once that is spent.
- 2026-11-01: Skip a listing that shows a from-to price in `parse_comps` instead of averaging the two ends, because that range spans different variants and no one is asking the midpoint.
- 2026-11-01: Let plain sizes such as 34x32 or Large keep their comps and drop only tall, plus and petite cuts that staff did not enter, because a page of 60 listings spreads across many sizes and matching one exactly would leave too few comps to price.
- 2026-11-01: Tell a game from a console by the card's product and platform, because both share the `electronics_games` category and a console's comps must drop games while a game's comps must drop consoles.
- 2026-11-01: Show the net beside a "check" whenever comps gave a typical price, and leave it empty only with no comps, so staff can still see what a low-confidence item might clear.
- 2026-11-01: Save an appraisal with no price and a "check" when the budget is spent, the search fails or the key is missing, rather than answering with an error, so staff can still make and record a call, and appraising again costs nothing for the searches already cached.
- 2026-11-01: Give no price when a fallback search fails even if an earlier search found a few comps, because a retry reuses the cached searches and a price from a search cut short would look like a finished one.
- 2026-11-01: Search new items with their own condition ids, because the used id `3000` returns only listings the condition filter drops for a new item, which would leave every new item with no price.
- 2026-11-01: Cache a SerpApi response only when its status is `Success`, and turn every search failure into `SerpApiError` with no URL in its message, because a cached failure would last 7 days and the request URL carries the key.
- 2026-11-01: Score pricing against PriceCharting's loose price for games and hardware, with items fixed before the first run, and accept hand-recorded sold prices for apparel, because no other sold-price source we checked could be used, see [evaluation.md](evaluation.md).
- 2026-11-01: Save evaluation cards and slimmed search responses in `api/eval/` and roll back the `comp_searches` rows of a run, so a rerun spends nothing and can't count against the app's budget, and a test fails when the saved results no longer match the code.
- 2026-11-01: Restart a `findBy` or `waitFor` that failed while the test process was frozen, instead of raising its deadline, because the deadline timer runs before the render already due when the process wakes, so a longer freeze beats any limit, and a wait that ran undisturbed still fails at the normal 1s.
- 2026-11-01: End the session before leaving the sign-out button's page, and hold `RequireAuth`'s redirect to sign-in with a signing-out mark on the auth context while the session clears, because the router's low priority navigation to the landing page otherwise loses to that redirect; clear the mark when the protected page unmounts so a later visit while signed out still redirects, and keep a failed sign-out on the page with a visible error rather than swallowing it.
- 2026-11-01: Sign in by username through `POST /auth/sign-in` on the API rather than through a lookup in the browser, which replaces the plan to keep it in `web/src/auth/accounts.ts`, because a lookup the browser can call would hand out anyone's address and tell a stranger which usernames exist.
- 2026-11-01: Find the Auth address from `auth_user_id` at sign-in rather than from `profiles.email`, so local profiles with no email and people with a hidden placeholder address can all use a username.
- 2026-11-01: Keep the sign-in failure count per username, because Auth sees every username sign-in as coming from the API's address. It first lived in the API process and now lives in `sign_in_attempts`, see the later entry.
- 2026-11-01: Store `must_change_password` in `profiles` rather than in Auth's user metadata, because a signed-in person can write their own metadata from the browser and would be able to lift the block on a temporary password.
- 2026-11-01: Change a person's own password by forwarding their token to Auth from `POST /me/password` and clearing the flag in the same request, so Auth still applies its own password rules and the browser can't clear the flag without really changing the password.
- 2026-11-01: Treat sign-up as closed by the code, with no route or form and a 403 for an Auth user with no profile, so nothing depends on the hosted Supabase setting being right.
- 2026-11-01: Deactivate by banning in Auth first and marking the profile second, and keep the profile row, because a failure between the two leaves the person locked out rather than still able to sign in, and their decisions still point at that row.
- 2026-11-01: Lock the active manager rows with `FOR UPDATE` before deactivating or demoting a manager, because two managers deactivating each other at the same moment would otherwise leave none.
- 2026-11-01: Stop the web build if a `VITE_` variable is named for the service role key or holds its value, because every `VITE_` value ends up in the public JavaScript.
- 2026-11-01: Change the pricing rules for games and hardware after the first evaluation, where the pipeline lost to raw asking prices on 18 items, because asking prices before the factor were a median 1.06 times the sold reference, so a factor of 0.645 from Poshmark apparel was too strong for them. This replaces the earlier call to leave the rules alone, whose worry about only fitting those 18 items is now answered by scoring fresh items that had no part in the tuning, and the 18 are labeled as tuning data.
- 2026-11-01: Set the factor for games and hardware to 0.94, one over that median, rather than the value that scored best, because a value picked for its score would fit the 18 items more closely and say less about the next item.
- 2026-11-01: Widen the range for games and hardware to the 15th to 85th percentiles and leave the comp filter alone, because a 25th to 75th band holds about half of what it measures by design, and the report shows the width and a like-for-like row, so a wider range can't pass as better pricing.
- 2026-11-01: Keep confidence on the 25th to 75th percentiles in every category, so widening the range doesn't turn a high-confidence item into a "check" with no new evidence about the item.
- 2026-11-02: Read and write every text file as UTF-8 and pass `newline="\n"` on each write, and check the repo out with LF through `.gitattributes`, so the evaluation report and saved results compare equal and the tests pass on Windows, where the default encoding is cp1252 and checkout would otherwise introduce CRLF.
- 2026-11-01: Leave apparel's factor and percentiles as they were, because none of the tuning evidence comes from apparel.
- 2026-11-01: Keep the fresh evaluation items in their own file, `api/eval/fresh_items.json`, so `git log` on that file shows the list came before its first score.
- 2026-11-01: Count username sign-in failures in the `sign_in_attempts` table instead of the API process, so the count survives a restart and holds across processes. Each attempt is counted under a short per-username advisory lock before Auth is asked, because counting afterwards would let requests arriving together all pass, and the username is hashed because people sometimes type a password into that box.
- 2026-11-01: Answer a wrong password, an unknown username and a turned-off account with one message, and count a turned-off account's tries like any others, because a different message or a limit that never arrives would show whether a password was right or an account exists.
- 2026-11-01: Refuse a token issued before `temporary_password_issued_at` on every signed-in route, and take that time from Auth's own reply rather than the API's clock, because the token's issue time is on Auth's clock. Auth 2.197.0 already ends old sessions when an admin changes a password, so this is a second check rather than the only one.
- 2026-11-01: Grow the fresh set to 30 games and hardware items with 15 picked to be harder, and report each batch beside the total, so the first batch's easier items can't hide the harder ones and the total can't be read as a random sample. The factor and percentiles stayed frozen even though asking prices ran a median 1.16 times the reference on the 30.
- 2026-11-01: Run the keep-alive ping as a scheduled GitHub Actions job on the self-hosted runner rather than an outside pinger service, because it needs no new account and spends no paid minutes, and accept that it stops while that PC is off, since a sleeping service still wakes in about a minute.
- 2026-11-01: Point the offline demo at a local stand-in for Supabase, the vision model and SerpApi rather than adding an offline switch to the app, so no setting in the deployed code can turn sign-in off.
- 2026-11-01: Report the deployed commit on `/health` from Render's `RENDER_GIT_COMMIT`, so anyone can check from outside which commit is live.
- 2026-11-02: Score vision accuracy from the saved evaluation cards rather than a new model run, because they came from the current prompt and providers and a rerun spends nothing, and count a near miss as wrong so the accuracy never gives partial credit, see [vision-accuracy.md](vision-accuracy.md).
- 2026-11-03: Work out the claim checker's flags whenever a draft is read rather than storing them, and store only the flags that sent the model's draft to the template, because a staff edit or a card edit would leave stored flags out of date.
- 2026-11-03: Allow a banned word or a claim when the card's own text has it, such as "vintage wash" in a product name, because the checker's job is to stop claims the card doesn't make, and refuse grades such as "mint" or "no flaws" even after a "not", because the card has no field for them.
- 2026-11-03: Refuse to send drafts for approval while any of them has a flag, rather than warning, because a manager approving a flagged claim is the mistake the checker is there to stop, and staff can always reword or fall back to the template text.
- 2026-11-03: Write a draft only for an item whose latest decision is yes, and draft a missing channel again rather than replacing one, so a lost response can be retried without overwriting staff's edits.
- 2026-11-03: Share `complete_json` in `api/app/ai.py` between the item card and the drafts, so both retry and fall back the same way.
- 2026-11-03: Read quoted words that are on the card as a copy of the card, and have the prompt quote the item's printed text, because the first live run passed 40 of 48 drafts, and 4 of its 7 flags came from the model describing that text with "includes" or "with" while the other 3 used "includes" for parts the card already names, so the prompt also bans "includes" when nothing extra was recorded.
- 2026-11-03: Keep each Settings section's default in code and seed the migration with a frozen copy of it, so a section with no row reads the same as a fresh database, and a later change to the code can't change what an old migration does. A test fails when the two differ.
- 2026-11-03: Make every field of a Settings section required on a save, rather than defaulted, so a save that leaves a field out is refused instead of quietly putting the starting value back.
- 2026-11-03: Send the `updated_at` a Settings section was read with on each save and refuse it with a 409 when the row has changed since, so one manager's save can't undo another's. The API stamps the time itself, because `now()` is the same for every statement in a transaction.
- 2026-11-03: Read the worth-listing threshold, the fees and both ask-to-sale factors from Settings on every appraisal, so `PRICING` in the environment no longer changes those six, and the evaluation clears the `settings` rows in its rolled-back transaction so it always scores the values in code.
- 2026-11-03: Write the seasonal calendar and the box sizes from published sources and label the choices that go beyond them as assumptions, see [settings.md](settings.md), and build only the read routes the timing hint in #20 and the box dropdown in #42 will use.
- 2026-11-04: Model Channel B's fees on Poshmark's published fees, 20% from $15 and a flat $2.95 below that, with the buyer paying the label, and keep them in their own Settings section, because Channel A's per-order fee and share don't fit a flat small-sale fee. The values come from a third-party guide and are labeled an assumption, see [settings.md](settings.md#channel-b-fees).
- 2026-11-04: Read "box section" on the pick list as the order the boxes have in Settings, with a box since taken out of Settings after them and no box last, then the shelf or bin in natural order, because the store has no map of where each box size is kept, and a manager can reorder the Settings list to match the shelves.
- 2026-11-04: Copy the box code onto the item rather than reference the Settings list, so taking a size out of Settings can't change the SKU of an item already packed in it, and check the code against Settings only when it is saved.
- 2026-11-04: Add the shelf or bin only after approval and refuse it before, so an item that is rejected never has a location, while the weight and box can be entered before approval because Channel A needs them to approve.
- 2026-11-04: Upper-case shelf and bin codes and close up the spaces around a dash, so `b12 - 2` and `B12-2` are saved as one code and sort together on the pick list.
- 2026-11-04: Add `release_month` and `mark_sold` as the narrowest seams for #20 and #21, a column nothing sets yet and a function nothing calls yet, each tested directly, so the held state and the pick list work now without building the timing hint, the channels or the sales sync.
- 2026-11-03: Run each mock channel as its own service with its own Postgres role and schema, with row-level security and a policy for that role only, so a channel can't read Turnstone's tables or the other channel's, and the main app reaches a channel only through its seller API, as it would a real platform.
- 2026-11-03: Send every channel update through a `jobs` table in Postgres, claimed with `FOR UPDATE SKIP LOCKED` and a 60 second lease, rather than calling the channel inside the request, so a channel that is down gets the update later and a runner that dies mid-call leaves no job stuck.
- 2026-11-03: Run polling and the jobs on a thread inside the API rather than as a separate worker, because Render's free plan has no free background workers, and the lease and `SKIP LOCKED` keep two API processes from running the same job.
- 2026-11-03: Sign sale webhooks with HMAC-SHA256 over the raw body using the channel key, and treat a 2xx answer as the acknowledgment, so polling asks only for orders that are not acknowledged and a missed webhook is still caught.
- 2026-11-03: Use the `listings.id` as the `external_ref` each channel stores and make publishing with the same one return the existing listing, so a publish retried after a timeout can't list the item twice.
- 2026-11-03: Keep a double sale as two `sale_events` rows and a flag rather than cancelling an order automatically, so a person decides before any buyer is refunded.
- 2026-11-03: Flag a stale listing and queue another `end_listing` job in the same poll, and let sync resolve the flag once the channel confirms, so a channel that was down only briefly doesn't leave a manager a flag to clear by hand.
- 2026-11-03: Make each open flag's `conflict_key` unique with a partial index and add flags with `ON CONFLICT DO NOTHING`, so a conflict that polling sees every 30 seconds is flagged once.
- 2026-11-03: Change a listing's status only on what the channel has confirmed, so Turnstone never shows a listing as ended while it is still for sale.
- 2026-11-04: Publish when a manager saves the shelf or bin of an approved item, rather than with a separate button, because an item is ready to sell once it is on a shelf to pick from, and hold back an item `held_for_season` until its release month.
- 2026-11-04: Leave the publish jobs to the scheduler rather than run them in the storage request, so saving the shelf answers at once even when a channel is slow or down, and the review page follows the listings as they go live.
- 2026-11-04: Give the mock channels the same category names the drafts choose from, and test that the lists match, so a draft's category is one the channel takes.
- 2026-11-04: Move the job queueing into `api/app/jobs.py`, so `approval.py` can queue a publish and `sync.py` can call `mark_sold` without one importing the other in a cycle.
- 2026-11-04: Keep the 15s limit for a whole web test and the 10s limit for a hook in a custom Vitest runner that counts only the time the test process ran, and turn off Vitest's own limits, because those limits are plain timers and the shared CI runner freezes every test process at once for 15s or more, which failed whichever tests were running even though each wait already restarts after a freeze.
- 2026-11-04: Let the first buyer keep a double-sold item, by the channels' sale times, and cancel the later order, because that buyer paid first, and the later buyer paid for an item that was already gone. Ties go to the order Turnstone heard of first.
- 2026-11-04: Let staff as well as managers fix Needs Attention flags, as requirements.md lists, because a buyer waiting on a double sale shouldn't wait for a manager to come in.
- 2026-11-04: Have the model only reword fixed sentences that code wrote for each flag, and refuse its text when it has a number the facts don't, so the explanation can't change what happened or what to do.
- 2026-11-04: Write flag explanations on their own scheduler thread, so a slow model never delays polling or a delist.
- 2026-11-04: Decide the channels and the timing in code and have the model only word the reason, and refuse a reason with a month or number the facts don't have, so the model can't change the advice, and show the fixed sentence when the model is missing, fails or takes more than 8 seconds.
- 2026-11-04: Work out the channel reason on each request rather than store it, because the calendar and the card can change before staff choose, and a stored sentence would then say something the rules no longer do.
- 2026-11-04: Recommend every channel that can take the item and let staff untick one, rather than pick a single best channel, because the rules know which channels can take an item but not which one will sell it.
- 2026-11-04: Refuse Channel B for a card with no brand, from `CHANNEL_REQUIRED` in `api/app/listing_drafts.py`, which a test keeps the same as the mock channel's required fields, so the screen doesn't offer a channel that would refuse the listing.
- 2026-11-04: Set the hold's release month from the timing hint when the listing is first drafted, rather than add a hold button, so the approval step holds the item as it already did, and a manager who wants a different hold changes the calendar in Settings.
- 2026-11-04: Match a season word on the card's brand, product, exact model, material and visible text, as a whole word with plurals, so "fleece" in the material and "Chiefs" in the brand match, while "coat" doesn't match "coated".
- 2026-11-04: Number SKUs from a counter row per initials and date in `sku_sequences`, bumped with `INSERT ... ON CONFLICT DO UPDATE`, rather than from a count of the day's items, because the row lock makes two intakes at once wait for each other instead of taking the same number, and a failed intake gives its number back.
- 2026-11-04: Let two people with the same initials share a prefix and its daily count rather than add a letter or digit to tell them apart, so every SKU keeps the same shape, and `lister_id` already says whose item it is.
- 2026-11-04: Take the SKU date from the store's time zone, `America/Chicago`, rather than UTC, so an item taken in during the evening is numbered with the day staff see on the calendar, and depend on `tzdata` so the zone loads on Windows, which has no zone files of its own.
- 2026-11-04: Ask for the store department at intake as `clothing` or `electronics_games`, the two kinds of item the app prices, as an assumption until the store gives its own list of departments, and keep it apart from the card's category, which the model sets.
- 2026-11-04: Answer a photo that matches a rejected item with a 409 and store nothing, and take it in only when staff send it again with `allow_repeat`, so a repeat is a choice staff make and the warning can't be missed by a client that ignores a flag on a success.
- 2026-11-04: Match a repeat photo only against items whose latest triage call was a rejection, so an item staff said no to and then yes to doesn't keep warning.
- 2026-11-04: Give the walking skeleton's placeholder SKUs real ones in the migration and leave their photo hashes empty, because their photos were never fingerprinted and a made-up hash could only match by mistake.
- 2026-11-04: Write no triage row for a manager's reject on the approval screen, because triage is the staff call on an item forwarded to Ecommerce, and that item was already accepted there.
- 2026-11-05: Answer a photo that fails the blur and brightness check with a 409 that names each photo, and take it in only when staff send it again with `keep_photos`, the way a repeat photo works, so the retake is a prompt staff can step past but can't miss. The check runs before the repeat check, so staff answer one prompt at a time.
- 2026-11-05: Judge sharpness on the sharpest of 8 by 8 pieces of the photo rather than the whole photo, because most item photos are an item on a plain backdrop, and the backdrop would make a sharp item read as blurry.
- 2026-11-05: Keep the listings behind each price in a `comps` column on `appraisals`, rather than read them again from the cached search, because a cached search is reused for only 7 days, and the evidence should be the listings the price was made from rather than a search run again later.
- 2026-11-05: Keep the disagreement reasons as fixed values checked by the API, with no check constraint in the database, because the manager approval screen writes its own words into `override_reason`. A call on a "check" never asks for one, since a check has no side to go against.
- 2026-11-05: Show the appraisal as one screen that goes to two columns from 52rem, with the item and its card on the left and the price and the call on the right, so on a desktop staff can see the card while they read the price, and a phone shows the same parts in order.
- 2026-11-05: Keep the synthetic sales history in its own `synthetic_items` and `synthetic_listings` tables rather than mark rows in `items` and `sale_events`, so a synthetic sale can never reach the pick list, the sync or Needs Attention, and number the rows in the generator so that loading the same seed again gives identical rows, see [synthetic-sales.md](synthetic-sales.md).
- 2026-11-05: Add a Weibull curve over the days of a listing's run to each channel's baseline, falling on Channel A and rising on Channel B, because FlowLister's 5.8% within a week against 12.2% within 30 days needs early sales on eBay, and Closo's 59-day average inside a 90-day run needs late ones on Poshmark. The rise on Channel B is a fit to that figure, which covers a trailing year, not evidence about how Poshmark sells.
- 2026-11-05: List each synthetic item on one channel, unlike the app, which lists it on every channel that takes it, because each published figure is for one marketplace and a sale on one channel would cut the other's sell-through.
- 2026-11-05: Read the synthetic history's parameters from `SyntheticSales` in code rather than the environment, so the history in the database and the calibration report always describe the same numbers.
- 2026-11-05: Compare Closo's figures for tops with women's apparel, because the app has no category for tops, and leave the eBay hold-out's miss at 19.9% against 28% unfixed, because tuning to it would stop it being a check.
- 2026-11-05: Judge the time to sell shape check on Channel A only, because the Mercari study is of a general marketplace like eBay and Channel B's rising curve puts its sales late by design.
- 2026-11-05: Check the commit and pull request rules in CI with a standard library Python script in `.github/scripts/` rather than a third-party Action, so it runs on the self-hosted runner with nothing to install, and it reads the section headings from the pull request template so the two can't drift apart. It checks the commits on the branch that aren't on the base branch, so older commits on `main`, including the ones a merge of `main` brings into the branch, don't fail it.
- 2026-11-05: Draw the dashboard charts with HTML bars and one SVG line chart rather than a chart library, because the four views need only bars and a line, and drawing them keeps the bundle the same size and every number readable as text by a screen reader and on a phone.
- 2026-11-05: Label the charts from the mock channels "Synthetic, live." rather than leave them unlabeled, because the issue asks for every chart to be labeled synthetic and those sales are test events, and keep them on their own charts with their own label so they are never mixed with the generated history.
- 2026-11-05: Read "agreement" in the sync view as whether Turnstone and the channels agree, counted from the conflict flags and items with two standing orders, and show staff against the recommendation under the triage funnel, where the call is made.
- 2026-11-05: Look up a username's email for a reset link in the API with `POST /auth/password-reset` rather than in the browser, so the browser never learns which usernames exist or their emails. It answers the same when nothing is sent, but a failure to send to a real address is reported, because hiding it would leave the person waiting for an email that never comes.
- 2026-11-05: Answer insight questions by having the model pick one of six tested functions and word the answer from what code returned, rather than write SQL, and fall back to code's own sentence when the wording has a number code didn't return, so every number a manager reads came from a tested query.
- 2026-11-05: Keep the insight chat's answers on the page only rather than save them, because nothing reads them later, which keeps the feature free of a table and a migration.
- 2026-11-06: Work out whether a held item is back for review when it's read, from its release month and today's date, rather than move it with a scheduled job, because the free Render service sleeps and a missed run would leave an item stuck, while a read can never miss its month. The item keeps the `held_for_season` status until a manager acts, so no second status is needed for "back for review".
- 2026-11-06: Record each held item's choices as rows in `decisions`, with the wording as the reason, rather than add a history table, because the review page already reads who decided what and when from there. The cost is that these rows count as the item's latest call in the dashboard's against-recommendation figure, as a manager's rejection already did.
- 2026-11-06: Add the status `not_listed_online` for an item taken out of online selling, rather than reuse `declined`, because staff can say yes again to a declined item and this choice should need a manager to undo.
- 2026-11-06: Save the fresh comparable sales for a returning held item as a new appraisal, rather than show them without saving, so the page doesn't search eBay again on every visit and the lookup stays on record. This spends one SerpApi search per returning item when the cached search is more than a week old.
- 2026-11-06: Make List now set the release month to this month and send the item through the same review as an item whose month has come, rather than publish it straight away, so a manager always sees the fresh sales before an old price goes live.
- 2026-11-06: Send an item put back for review to the status the approvals queue already reviews it from, rather than add a status, so it goes through the same review and price check: `held_for_season` with this month as its release month when its listings were approved, which brings it back with fresh comparable sales, and `appraised` when they weren't, which leaves it waiting with its listings. Only a manager can put it back, because staff can't approve it either.
- 2026-11-06: Count a fresh comparable sales lookup for an item put back for review only when it was made after the put back, so an item put back months after its season gets prices from now rather than from its last review.
- 2026-11-06: Warn at intake about an earlier item kept off online, by a shared photo or the same brand and product read off the card, without stopping the item, unlike the rejected photo check, because staff often take in a second of the same product on purpose and only need to know what happened to the first. The earlier item is a link only for a manager, because only a manager can open its review.
- 2026-11-06: Read each apparel reference as the median of up to 10 recent matching sold listings, from eBay's sold filter first and Mercari's when eBay has fewer than 5, and leave out an item short on both, because no automated source gives apparel sold prices and a person recording a fixed rule is the most checkable source left. The rule was written before any price was recorded.
- 2026-11-06: Keep the vision accuracy and listing draft checks to games and hardware for now, because no apparel label or draft has been written yet, and their reports already say apparel is not measured, so adding the apparel items to the pricing evaluation does not make them fail.
- 2026-11-07: Replace the USWDS blues with the Grove look, a cream page with deep green actions and a dark green band on the header and footer, and round the corners, because the app read as plain for the demo. It mixes the dark green of the round 3 landing mockup with a light page, drops the mockup's mustard because it clashed with the green, and keeps the USWDS status colors and the blue and orange chart colors so warnings and categories still read the same. Every text pair passes WCAG AA.
- 2026-11-07: Replace the hang tag mark with a turnstone tipping over a stone, in the header and the favicon, because the bird ties the mark to the name and turning over a stone matches the app turning over donations to find what's worth selling online. It draws in the text color so it sits on the dark header band, and the favicon turns cream in a dark browser theme.
