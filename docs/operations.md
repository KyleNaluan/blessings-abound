# Hosting and operations

This page covers running the hosted demo, keeping it awake for judging, and changing the API.
How to run and reproduce the project on your own machine is in the [README](../README.md#reproducing-the-results).

## Hosted demo

The demo is at https://blessings-abound.pages.dev, with the API at https://blessings-abound-api.onrender.com.
[demo-script.md](demo-script.md) is the script for showing it at judging, with the demo items, the fallback to the offline demo and a backup video, and a shot list for that video.

| Part | Where | Settings |
| --- | --- | --- |
| Web app | Cloudflare Pages project `blessings-abound`, built from `main` | `VITE_API_URL`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` in the production environment variables |
| API | Render free web service `blessings-abound-api`, Docker from `api/` on `main` in Ohio, deployed on every merge | The list below |
| Mock channels | Render free web services `blessings-abound-channel-a` and `blessings-abound-channel-b`, Docker from `api/` on `main` in Ohio, deployed by hand | [Mock channels on Render](#mock-channels-on-render) |
| Database, photos and sign-in | Supabase | Auth site URL set to the web app's address, and its `/choose-password` address in the redirect list |

To set the API up again, create the Render service with those details and a health check path of `/health`, then set these from [.env.example](../.env.example):

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

[keep-alive.yml](../.github/workflows/keep-alive.yml) calls `/health/db` every 10 minutes, because Render stops a free service after 15 idle minutes and Supabase pauses a free project after about a week.
It runs on our self-hosted CI runner, so it stops while that PC is off and can wait behind a CI job, and GitHub can also start scheduled runs late.
A sleeping service still answers, after about a minute, so a missed ping costs time rather than the demo.
Render's free plan allows 750 hours a month across a workspace, which covers one service running all month but not three, so the mock channels should be kept awake only in the days around judging.

### Mock channels on Render

The mock channels run as two more Render free web services in the same workspace and region as the API, so the extension in [demo-script.md](demo-script.md) runs on the hosted demo with the real vision model.
Channel A's storefront is at https://blessings-abound-channel-a.onrender.com and Channel B's is at https://blessings-abound-channel-b.onrender.com.
Each one is Docker from `api/` on `main`, with a health check path of `/health`, and these settings:

| Setting | Channel A | Channel B |
| --- | --- | --- |
| Service | `blessings-abound-channel-a` | `blessings-abound-channel-b` |
| Start command | `uvicorn mock_channel.channel_a:app --host 0.0.0.0 --port $PORT` | `uvicorn mock_channel.channel_b:app --host 0.0.0.0 --port $PORT` |
| `CHANNEL_DATABASE_URL` | Supabase's session pooler with the user `channel_a.<project ref>` and the `postgresql+psycopg://` scheme | The same with `channel_b.<project ref>` |
| `CHANNEL_KEY` | A long random key | A different long random key |
| `CHANNEL_WEBHOOK_URL` | `https://blessings-abound-api.onrender.com/channels/channel_a/sales` | `https://blessings-abound-api.onrender.com/channels/channel_b/sales` |

The start command replaces the image's own, so a channel service never runs migrations.
Enter it as it is, without wrapping it in `sh -c "..."`, because Render already runs it in a shell that fills in `$PORT`, and a quoted command fails to start with status 127.
Auto-deploy is off for the channels, so a merge rebuilds only the API, and a change to `api/mock_channel/` needs a manual deploy of both channel services.
After the API has applied the migration, run `uv run python -m app.channel_roles` in `api/` once with `DATABASE_URL` pointing at Supabase and `CHANNEL_A_DB_PASSWORD` and `CHANNEL_B_DB_PASSWORD` set, so the two roles can sign in.
Then set `CHANNEL_A_URL`, `CHANNEL_A_KEY`, `CHANNEL_B_URL` and `CHANNEL_B_KEY` on the API service, with each key matching that channel's `CHANNEL_KEY`, and redeploy it.

A channel gets no traffic of its own, so it sleeps when the API sleeps.
While the API is awake, it polls each channel every 30 seconds, which keeps both channels awake.
The first call to a channel that is still asleep times out after 10 seconds and is retried, so a listing can take about a minute to go live right after the channels wake.
Suspending the two channel services in the Render dashboard stops their hours and keeps their settings, and resuming them brings the extension back.

### Wake checklist

Do this the day before judging, and again 15 minutes before it starts.

1. Check that `curl https://blessings-abound-api.onrender.com/health` answers `200` with the commit at the top of `main`, allowing a minute for a cold start.
2. Check that `curl https://blessings-abound-api.onrender.com/health/db` answers `200`. If it answers `503`, restore the project if the Supabase dashboard shows it paused, then try again.
3. Check that `curl https://blessings-abound-channel-a.onrender.com/health` and `curl https://blessings-abound-channel-b.onrender.com/health` each answer `200`, allowing a minute for a cold start, so the extension's first listing doesn't wait on a sleeping channel.
4. Check that the latest Keep the demo awake run in GitHub Actions passed within the last 15 minutes.
5. On a phone, open https://blessings-abound.pages.dev, sign in as `demo.staff`, check that each card on the home page shows its count or a line such as "No sold items to pick", with no "Can't reach the API" notice, and sign out.
6. Do the same as `demo.manager`.
7. Check on the SerpApi dashboard that searches are left this month.
8. On the laptop, run the [offline demo](../README.md#offline-demo)'s `up` command once, sign in, and leave it ready in case the network fails.

## Changing the API

After changing a route or a request or response model, regenerate the web app's typed client and commit it with the change:

```sh
cd web
npm run gen:api
```

Schema changes go through Alembic migrations, as described in [CONTRIBUTING.md](../CONTRIBUTING.md#database).
The tables are described in [database.md](database.md), which also covers creating the first manager account, seeding the demo accounts and the manager routes for adding people.
