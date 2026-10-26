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

`data/` holds `settings.json`, `dishes.json`, `planning_runs.json`,
`fridge.json`, `prompt.json`, `shopping_list.json`, plus `data/recipes/`,
`data/fridge_images/` and `data/icons/`. It is created on first run and is never committed.

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ (for the frontend)

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
