# Architecture (maintainer map)

> **Doc status:** Active

Oneirodex is one Flask app (`oneirodex/`) plus three React SPAs and a typed HTTP client. This page is the map, not a rewrite of [ADR 0005](../adr/0005-api-client-is-the-requester.md) or [agent-locks.md](agent-locks.md).

## Runtime

| Piece                   | Role                                                                           |
| ----------------------- | ------------------------------------------------------------------------------ |
| Flask (`oneirodex/`)    | Session cookie, Jinja shells, `/api/**` + `/admin/api/**`, scans, play, social |
| member-app              | Household SPA (`frontend/member-app`)                                          |
| admin-app               | Operator SPA (`frontend/admin-app`)                                            |
| ops-glance              | Ops pulse widgets (`frontend/ops-glance`)                                      |
| `@oneirodex/api-client` | One requester, two transports (Bearer `gt_…` / browser cookie + CSRF)          |
| `@oneirodex/ui`         | Shared chrome, envelope helpers, CSRF lookup                                   |
| Desktop companion       | Tauri client on the Bearer transport                                           |

JSON errors go through `api_ok` / `api_error` (`oneirodex/utils/api_response.py`). Eleven sites stay off that helper on purpose — [api-envelope-keeps.md](api-envelope-keeps.md).

## SPA fetch

Admin, member, and ops sit on `createBrowserRequester`: `credentials: 'include'`, `X-CSRFToken` on mutating verbs, `onUnauthorized` → `/login`. Wrappers keep their exported names. Member collections CRUD now calls `createCollectionsApi` through that same requester (`memberResource`); search still uses `getJson` on `/api/search`. Other resource groups still call `getJson`/`postJson` directly.

Member leftovers that are not JSON verbs:

- `preferences.ts` — HTML `POST /settings_panel` (FormData)
- Activity / scan toasts — `EventSource` (`/api/activity/stream`)

Request bodies adopt `@validate_body` **file-by-file** — [pydantic-adoption.md](pydantic-adoption.md). Partial-success batch routes use `@validate_batch_body` so the 422 keeps `updated` / `skipped` / `errors` / `limit`. Do not wrap those with the flat helper.

## Browse filters (INSP-3)

Two faces, **one vocabulary**. The flat chip params (`is_vr`, `freshness_behind`,
`new_import`, `path_status=`, `name=` …) and the nested tree both compile through
`FIELDS` in `oneirodex/utils/filter_tree.py`, so a field has exactly one clause
builder and the two cannot drift apart.

| | |
|---|---|
| Tree shape | `{"op": "and"\|"or"\|"not", "nodes": [...]}` groups; `{"field": …, "value": …}` leaves |
| Vocabulary | **only** the fields in `FIELDS` — a tree cannot reach a column the chip row cannot, join a new table, or express a comparison nobody shipped |
| Bounds | `MAX_DEPTH` 6, `MAX_NODES` 60 |
| On browse | `GET /browse_games?filter_tree=<json>` — a **conjunct beside** the chips, never a replacement |
| Bad tree | `400` naming the offending part (`detail.path`, e.g. `root.1.0`), never silently dropped |
| Negation | `NOT` folds SQL's third value away (`coalesce(expr,false)`), so *not behind* includes rows the field was never set on |

Adding a field is a deliberate edit to `FIELDS` — it is not a side effect of the
model gaining a column.

Named filters are per-member (`SavedFilter`, Alembic `c3d4e5f6a7b8`):
`GET|POST /api/filters/saved`, `PUT|DELETE /api/filters/saved/<id>`,
`POST /api/filters/preview` (count + optional sample, through the member's own
access filters), `GET /api/filters/fields` (what a builder may offer). The
`is_collection` flag is what makes the same row a smart collection (INSP-29)
rather than a second table. No admin view, no sharing surface.

## Identifiers (ADR 0003)

Runtime env is **`ONEIRODEX_*` only**. `GT_*` is not read. `LEGACY_NAME = 'GameTheca'` stays so stock themes authored by older versions are still recognised. On-wire API tokens keep the `gt_` prefix. Danger-zone confirm is `RESET ONEIRODEX` (no legacy alias).

## Frozen / do not drive-by

- `oneirodex/updateschema.py` — historical SQL; Alembic is the migrator
- Shims: `oneirodex/utilities.py`, `oneirodex/utils/functions.py`, `oneirodex/utils/game_core.py`
- Envelope keep-list of 11
- Mega pages (GameDetails, Library, Chat, Discover) stay typed in place — no decomposition PRs
