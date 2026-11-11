# Food Planner

A small meal-planning tool that runs on a household's own network. See
[`spec.md`](spec.md) for the full specification.

This is the **walking skeleton**: a FastAPI backend with a JSON-file
persistence layer, a React shell that talks to it same-origin under `/api`, and
the four test fixtures every later test starts from.

## Layout

```
src/food_planer/    FastAPI app, JSON store, external-service clients
tests/              pytest suite driving the HTTP seam (TestClient)
frontend/           React shell (Vite + TypeScript)
data/               gitignored; one JSON file per entity type, created on first run
```

`data/` holds `users.json`, `sessions.json` and `invites.json`, the shared
`data/recipes/` and `data/icons/`, and one directory per household under
`data/users/<household id>/` with its `settings.json`, `dishes.json`,
`planning_runs.json`, `fridge.json`, `prompt.json`, `shopping_list.json`,
`my_week.json`, `model.json`, `appearance.json`, `fridge_images/` and
`run_logs/`. It is created on first run and is never committed.

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (for the frontend)
- A model, picked under ⚙ → Model:
  - **OpenAI**: an API key, pasted there or set as `OPENAI_API_KEY` in `.env`.
  - **Claude**: [Claude Code](https://code.claude.com) on the machine running
    the app, signed in with a Pro/Max plan (`claude auth login`), or a token
    from `claude setup-token` pasted into the Model card. Calls run on that
    subscription through the Claude Agent SDK. This is for personal use on
    your own machine: don't use it to give other people access through your
    plan.

Keys and tokens saved in the app are kept in plain text in `data/model.json`.

## Run it (production-style, single origin)

Build the frontend once, then start the backend — a single Uvicorn worker
serves the built shell and the API from the same origin:

```bash
(cd frontend && npm install && npm run build)   # emits frontend/dist/
uv run food-planer                               # http://localhost:8000
```

A single worker is required: the persistence layer keeps one in-memory cache
per file, so a second worker would read stale data. `data/` is resolved
relative to the process's working directory.

## Households and invites

Someone who signs up on their own starts a household of their own. To share
one — the fridge, dishes, My week, the shopping list and every setting — open
⚙ → Household → **＋ Invite someone** and send the link (Share… or Copy link).
Whoever opens it picks a username and lands in your household; someone who
already has a user signs in and is asked whether to move. A link works for a
week, for anyone it's sent to, and can be revoked from the same card. The
server keeps only a digest of it, so it is shown once, when it's made.

Invite links use the address the app was opened on, so make them from the
address the others will use (the https one below, not `localhost`).

Everyone in the owner's household — the first user and whoever they invite —
plans on the server's own `OPENAI_API_KEY` and Claude Code login. Someone who
started a household of their own saves a key or token under ⚙ → Model
instead; it belongs to their household, so everyone in it uses it.

⚙ → Household → **Personalize** gives the household a name, a mark and an
accent colour, shown to everyone in it. The home-screen icon stays the carrot.

## Install as an app (Android & iOS)

The planner is a web app: added to the home screen, it opens full-screen with
its own icon. The same steps are in ⚙ → Household → Install on your phone.

**iPhone / iPad (Safari)**

1. Open the planner's address in **Safari**.
2. Tap **Share** (the square with an arrow) — at the bottom on an iPhone, top
   right on an iPad.
3. Scroll down, tap **Add to Home Screen**, then **Add**.
4. Open it from the new icon and **sign in again**: the home-screen app keeps
   its own sign-in, separate from Safari's. If you joined through an invite
   link in Safari, sign in with the same username.

**Android (Chrome)**

1. Open the planner's address in **Chrome**.
2. Tap **Install the app** under ⚙ → Household, or the **⋮** menu →
   **Install app** (on some phones **Add to Home screen** → **Install**).
3. Open it from the home screen or app drawer.

**Serve it over https for a real install.** Chrome only installs a full-screen
app from an https address (or `localhost`); over plain `http://<ip>:8000` it
adds a shortcut that opens in a browser tab, and Copy link needs https too.
iOS adds to the home screen either way. The simplest route on a home network
is [Tailscale](https://tailscale.com) on the server and each phone:

```bash
tailscale serve --bg 8000    # https://<machine>.<tailnet>.ts.net → :8000
```

Any reverse proxy with a certificate (Caddy, nginx) in front of port 8000
works the same.

## Logs

Every planning run logs, to the server's stdout: the settings it used, how
many tilbudsavis offers were found and shown to the model (per shop), the full
prompt, the model's raw output, and a summary (status, offers cited by the
model vs. matched by ingredient name). `FOOD_PLANNER_LOG_LEVEL` sets the level
(`INFO` default; `DEBUG` adds offer-cache hits; `WARNING` quietens it).

Each run also writes the same detail as one JSON file to
`data/run_logs/<run id>.json` — the first place to look when a plan looks
wrong. Running in the background, keep stdout too:
`nohup uv run food-planer > food-planer.log 2>&1 &`.

## Develop

Run the API and the Vite dev server side by side. The dev server proxies
`/api` to the backend, so the frontend still talks to a same-origin API:

```bash
uv run food-planer                 # API on :8000
cd frontend && npm run dev         # shell on :5173, proxying /api → :8000
```

## Test & typecheck

```bash
uv run pytest                      # backend suite (the HTTP seam)
cd frontend && npm run typecheck   # frontend TypeScript check
```

The backend suite is the seam every behaviour is pinned at: tests drive a
FastAPI `TestClient` against a temp `data/`, with fake OpenAI and Tjek clients
injected through `dependency_overrides`. Per the spec there are no frontend
unit/component tests — screens are verified by using them.
