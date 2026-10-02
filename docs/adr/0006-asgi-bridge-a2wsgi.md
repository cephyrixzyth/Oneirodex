# ADR 0006: Flask behind an ASGI server, bridged by a2wsgi

> **Doc status:** Active

**Date:** 2026-09-16 (records decisions taken 2026-07 → 2026-09-06)
**Status:** Accepted
**Owners:** `agent-backend` · `agent-ops` · `agent-platform`

## Context

Oneirodex is a Flask application, and Flask is WSGI. Two things it serves do
not fit a synchronous worker model:

- **Large file streams** — ROM and disc downloads, zip packs, and the SPA
  bundles under `/static/dist/**`. A WSGI worker holding a 4 GB download is a
  worker the household cannot use for anything else.
- **Long-lived connections** — the activity stream (`/api/events/stream`, SSE)
  and the ops pulse. These must outlive a request/response cycle.

The first bridge was asgiref's `WsgiToAsgi`. It submits each call into a
`CurrentThreadExecutor` that can already be shut down when the client
disconnects mid-request, so a cancelled request died as a 500 the operator then
had to explain (UID-051 / UID-052). The fault was never reproducible on demand
— ~30 attempts across sequential, concurrent and mid-flight-abort patterns —
which is exactly why it needed a structural answer rather than a retry.

## Decision

**Keep Flask. Run it under uvicorn through `a2wsgi`'s `WSGIMiddleware`, and
route the two exceptions around the bridge entirely.**

- `asgi.py` is the entrypoint (`startweb.sh` / `startweb_windows.cmd`, never
  `python asgi.py`). It builds the Flask app with `create_app()` and wraps it
  in `WSGIMiddleware`, which runs WSGI on its own thread pool and treats
  `http.disconnect` as a disconnect, not a broken executor.
- **`/static/*` bypasses the bridge** (`_handle_static`): streamed with
  `aiofiles`, owning its own cache-control and security headers. The reason
  outlives the bug — a static stream should not hold a WSGI thread.
- **SSE bypasses the bridge** (`_handle_sse`): a long-lived sync stream holds
  a bridge thread whichever bridge it is.
- Background workers (scan scheduler, pollers, library watcher) start from the
  ASGI **lifespan** hooks via `oneirodex/background.py`, not from
  `create_app()` — construction stays pure, and pytest gets an app with no
  threads (`ONEIRODEX_ENABLE_BACKGROUND_WORKERS`).
- `UVICORN_WORKERS=1` is the documented default; multi-worker shared state
  (theme-asset version memo, deletion-progress dict) is per-process.

`tests/test_asgi_bridge.py` pins the bridge identity and asserts a pre-body
disconnect completes without raising; `tests/test_asgi_static.py` covers the
static path. Both are in the CI core list.

## Consequences

| Pros | Cons |
| --- | --- |
| No framework rewrite — Flask, Jinja shells, and every route survive | Two code paths for HTTP: the bridge and the two bypasses must stay behaviourally aligned (headers, auth) |
| Client disconnects no longer surface as operator-visible 500s | `a2wsgi` is a small dependency with a smaller community than asgiref |
| Downloads and SSE stop starving the request pool | There is no red-to-green test for the original fault; ops 500s are the field signal |
| Lifespan-started workers make `create_app()` cheap and test-safe | Anything that assumes one process (in-memory memos) needs revisiting before `UVICORN_WORKERS>1` is the default |

## Related

- `docs/dev/ui-debt-log.md` — UID-051, UID-052
- `docs/dev/architecture.md` — runtime map
- ADR 0007 — the SPAs this serves
