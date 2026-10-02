# Why 11 JSON sites stay off `api_ok`

> **Doc status:** Active

The SPA error component needs **one** failure shape. `api_ok` / `api_error` is that shape. A ratchet (`scripts/api_envelope_lint.py`) stops new `jsonify({error|message|status|success|ok})` call sites from growing.

Eleven remaining hits are **not** leftover sloppiness. Wrapping them would change the meaning of a field the caller already treats as data.

| Keep | Field that collides | If we wrapped it |
|---|---|---|
| `GET /pulse` | `status: "ok"` is the **probe contract** (Compose / Unraid / kube) | Envelope would add keys probes ignore, and `status` would stop being the liveness flag |
| Batch favorite / status / freshness / wishlist / library delete | `ok` means **every item succeeded** (partial batches are HTTP 200) | `api_ok` stamps `ok: true` and the SPA would hide the failures |
| `GET /api/ai/status` | `error` is **why Ollama is unreachable**, on HTTP 200 | `api_ok` **pops** `error`, so the status page would go blank |
| Hardlink preview | `ok` means **would this link work**, not “did the request work” | A preview of “no” would become “yes” |
| Game-details play / freshness payloads | `status` is **play/freshness state**, not HTTP | Envelope `status` would collide with the game’s state |
| `GET /api/oidc/status` | `message` is the **operator checklist sentence** | Envelope `message` is for failures; wrapping would nest or overwrite the report |

Do **not** `--update` the ratchet to hide these. Do **not** wrap them to make the number zero. Zero would be a lie.

New routes still must use `api_ok` / `api_error`. Classic admin JS that needs a body `status` uses `body_status=` on `api_error`.

## The crash path is covered too

`api_ok` / `api_error` only shape responses a route **chooses** to return. An
uncaught exception, an `abort(404)`, a CSRF rejection — none of those pass through
a route's return statement, and they used to come back as Flask's HTML error
page. `create_app` now registers catch-all `HTTPException` / `Exception` handlers
(`oneirodex/__init__.py`, helpers in `oneirodex/utils/error_envelope.py`) that
return `api_error(...)` for any request `wants_json_error()` recognises (an
`/api/` path, `Accept: application/json`, or an XHR header). The HTTP status is
preserved; only the body shape changes. HTML routes keep Flask's default pages.
The uncaught-`Exception` message is fixed text — `str(exc)` can carry paths, SQL,
or secrets — and the real error is logged with a traceback server-side.
