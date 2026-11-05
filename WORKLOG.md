# Worklog

A log of what each developer has changed in the project, newest first.
Every pull request adds its own entry under its author's section, in the form `date, PR, one-line summary`.

## KyleNaluan

- 2026-11-04, [#43](https://github.com/KyleNaluan/blessings-abound/issues/43), Add the Needs Attention screen for staff and managers, with a plain explanation and fix for each flag that falls back to fixed text when the model fails, a one-click cancel of the later order of a double sale that is retried while the channel is down, and a note for marking any flag handled
- 2026-11-04, [#21](https://github.com/KyleNaluan/blessings-abound/issues/21), Add the two mock sales channels as their own services, publish an approved item to them once it has a shelf, and keep them in step after a sale with a webhook, polling, retried jobs, a sync log and flags for double sales and stale or unknown listings, with a sale putting the item on the pick list
- 2026-11-04, [#68](https://github.com/KyleNaluan/blessings-abound/issues/68), Stop the web tests timing out when the shared CI runner freezes, by counting only the time a test ran against its 15 second limit
- 2026-11-04, [#42](https://github.com/KyleNaluan/blessings-abound/issues/42), Add the manager approval step with per-channel prices and nets, the package and shelf step with the box size from Settings and the suffixed SKU, and the pick list by box then shelf, with sales left to #21 and the box dropdown part of #41 done
- 2026-11-03, [#41](https://github.com/KyleNaluan/blessings-abound/issues/41), Add the manager-only Settings page and its `settings` table, seed the seasonal calendar and box sizes from published sources, and price appraisals from the saved worth-listing price, fees and ask-to-sale factors, with the timing hint and box dropdown left to #20 and #42
- 2026-11-03, [#19](https://github.com/KyleNaluan/blessings-abound/issues/19), Draft the listing for each channel with the model, check it with the rule-based claim checker, fall back to the fixed template when flagged, and let staff edit and send it for manager approval
- 2026-11-02, [#25](https://github.com/KyleNaluan/blessings-abound/issues/25), Follow the README from a fresh Windows clone: add the clone and Git steps, read and write files as UTF-8 so the evaluation tests pass on Windows, and check files out with LF line endings
- 2026-11-02, [#39](https://github.com/KyleNaluan/blessings-abound/issues/39), Label the 48 evaluation photos with brand, category and product, and score the saved item cards against them, with the person check of the labels still to do
- 2026-11-01, [#11](https://github.com/KyleNaluan/blessings-abound/issues/11), Add 15 harder fresh games and hardware items, score them once with the rules frozen, and report each batch beside the total of 30
- 2026-11-01, [#31](https://github.com/KyleNaluan/blessings-abound/issues/31), Refuse a session from before a temporary password was issued, answer a turned-off account the same as a wrong password, and keep the failed sign-in count in the database
- 2026-11-01, [#22](https://github.com/KyleNaluan/blessings-abound/issues/22), Deploy the API to Render and write up the hosted demo, with a keep-alive ping, a wake checklist and an offline demo that needs no keys or network
- 2026-11-01, [#31](https://github.com/KyleNaluan/blessings-abound/issues/31), Add invite-only accounts: username sign-in, manager routes for invites, temporary passwords, roles and deactivation, and seeded demo accounts
- 2026-11-01, [#11](https://github.com/KyleNaluan/blessings-abound/issues/11), Give games and hardware their own ask-to-sale factor and a wider price range, and score them on fresh items that had no part in the tuning
- 2026-11-01, [#56](https://github.com/KyleNaluan/blessings-abound/pull/56), Stop the web tests failing when the shared CI runner freezes, by restarting a wait that a freeze cut short, and make sign-out land on the landing page
- 2026-11-01, [#11](https://github.com/KyleNaluan/blessings-abound/issues/11), Add the evaluation set and scoring script for games and hardware, with apparel not scored yet
- 2026-11-01, [#14](https://github.com/KyleNaluan/blessings-abound/issues/14), Price appraisals from the comps lookup and the pricing core in place of the placeholder, and save an honest check when there is no price
- 2026-11-01, [#12](https://github.com/KyleNaluan/blessings-abound/issues/12), Filter comps to the same kind of item, turn them into a price range and confidence, and add the worth-listing rule (also #15 and #16)
- 2026-11-01, [#10](https://github.com/KyleNaluan/blessings-abound/issues/10), Read the item card from the photos with the vision model, and let staff edit and confirm it before any search
- 2026-11-01, [#7](https://github.com/KyleNaluan/blessings-abound/issues/7), Check Groq and Gemini on sample photos and add the item card JSON check with retry and fallback
- 2026-11-01, [#30](https://github.com/KyleNaluan/blessings-abound/issues/30), Add the walking skeleton from photo to saved decision, with a placeholder item card and price
- 2026-11-01, [#14](https://github.com/KyleNaluan/blessings-abound/issues/14), Add the SerpApi eBay comps lookup with a 7 day comp_searches cache, a monthly search budget and the drop-a-word fallback
- 2026-11-01, [#40](https://github.com/KyleNaluan/blessings-abound/issues/40), Rename the app to Turnstone in the API title and package description
- 2026-11-01, [#4](https://github.com/KyleNaluan/blessings-abound/issues/4), Check SerpApi's eBay search for apparel and electronics and save the responses as test fixtures
- 2026-10-30, [#46](https://github.com/KyleNaluan/blessings-abound/pull/46), Update the requirements, README and architecture docs to the 2026-10-29 plan and the Turnstone name
- 2026-10-30, [#36](https://github.com/KyleNaluan/blessings-abound/pull/36), Add item, decision and profile tables, the first manager setup script and migration checks in CI
- 2026-10-30, [#35](https://github.com/KyleNaluan/blessings-abound/pull/35), Add the landing page and the Supabase sign-in pages
- 2026-10-26, [#34](https://github.com/KyleNaluan/blessings-abound/pull/34), Add requirements document with tiers, roles and assumptions
- 2026-10-25, [#29](https://github.com/KyleNaluan/blessings-abound/pull/29), Add WORKLOG.md and the worklog rule
- 2026-10-25, [#28](https://github.com/KyleNaluan/blessings-abound/pull/28), Add project skeleton for api and web with CI and conventions
- 2026-10-16, no PR, Add contributing guide

## halleepham

- No merged work yet.

## Manan151179

- No merged work yet.
