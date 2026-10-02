# Library root-folder incremental watch (Wave 3 + path-health / per-lib)

> **Doc status:** Active

**Status:** Implemented (optional; **default off**).  
**Owner:** Backend (+ Ops for Unraid mount-event honesty)

## Today

When `ONEIRODEX_LIBRARY_WATCH=1`, Oneirodex starts a watchdog Observer over each library’s `last_scan_folder` **except** libraries with `watch_enabled=false` (per-library opt-out). Events are scan-depth–aware (game-leaf + one immediate child only — not deep arcade ROM trees), debounced (2–5s, default 3), and **only enqueue** FIFO `ScanJob`s via `scan_queue` (cooperative with `worker_caps`; watcher never runs scan threads itself).

Unset / `0` → no watcher (scan-driven discovery only: manual / scheduled / refresh-all). Per-library `watch_enabled=true` does **not** bypass the env master switch (Unraid FUSE safety).

## Env

| Var | Default | Meaning |
|---|---|---|
| `ONEIRODEX_LIBRARY_WATCH` | off | `1` / `true` / `yes` / `on` enables the watcher |
| `ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC` | `3` | Debounce window; clamped to **2–5** |
| `ONEIRODEX_LIBRARY_ADD_NOTIFY_DEBOUNCE_SEC` | `5` | Staff digest debounce when titles are identified; clamped **2–30** |

Also documented in `.env.example` and [unraid-deploy.md](../runbooks/unraid-deploy.md#library-root-watch-gt_library_watch--unraid-honesty).

## Per-library `watch_enabled`

| DB value | Meaning |
|---|---|
| `null` (default) | Follow global — watch when env on |
| `true` | Prefer watch (still requires env on) |
| `false` | Opt out — never watch this library |

Admin create/edit form + `GET/PUT /api/library/<uuid>/watch` (`watch_enabled`, `watch_effective`, `watch_global_enabled`).

## Path health (browse)

Browse / favorites / discover / details card payloads include:

| Field | Meaning |
|---|---|
| `path_status` | `ok` \| `missing` \| `empty` \| `null` (scan-persisted) |
| `path_missing` | `true` when `path_status === 'missing'` |

Optional filter: `GET /browse_games?path_status=missing` (comma list OK). When remove-missing is off and a folder disappears, scan keeps `path_status=missing` and browse surfaces it for UI badges.

## Incremental messaging

When scan/identify adds titles, staff (admin + librarian) get one **debounced** in-app notification per library:

| Field | Value |
|---|---|
| `kind` | `library_added` |
| title | `{library}: {n} game(s) added` |
| link | `/library?library_uuid=…` |
| payload | `library_uuid`, `library_name`, `count`, `game_uuids` |

Also logged as a `SystemEvents` row (`event_type=library`). No Discord.

## Behavior

1. Roots = libraries with a readable `last_scan_folder` that pass `library_should_watch` (env on ∧ not opted out).
2. Depth filter uses the same letter-bucket rules as scan (`scan_depth=2` → `_a…_z` / `_#`).
3. Events:
   - **add** (new game-leaf folder) → enqueue folders scan for that library root; if a library game was scan-flagged `path_status=missing` and the folder exists again, clear **missing→ok** immediately (no wait on scan-end refresh)
   - **change** (leaf or immediate child) → enqueue with `force_updates_extras_scan` so updates/extras refresh; same missing→ok clear when the leaf path matches
   - **delete** (game-leaf removed) → enqueue with `remove_missing` **only when** the library’s most recent ScanJob had `setting_remove=True` (Admin remove-missing policy); otherwise scan sets/keeps `path_status=missing`
4. Coalesce per library across the debounce window; skip enqueue when a Running/Stopping/Queued job already covers the same `scan_folder` (no unbounded full-tree overlap). Restore `path_status` clear still runs even when enqueue is skipped.

## Ops field map

`GET /admin/api/ops/summary` → `services.library_watch`:

| Field | Meaning |
|---|---|
| `enabled` | Env flag on |
| `running` | Observer started |
| `roots` | Watched library root count |
| `pending_libraries` | Libraries waiting on debounce flush |
| `debounce_seconds` | Active debounce |
| `last_event_at` / `last_enqueue_at` | ISO timestamps (nullable) |
| `note` | Human hint when disabled / not started |

**Admin UI:** Ops Services row + strip tile render `enabled` / `running` / `roots` / `pending_libraries` (honest **off** when disabled).

## Unraid note

Docker volume / FUSE mounts may miss host-side renames unless the watch runs where the mount is visible. Prefer bind-mount honesty notes in the Unraid runbook — Ops. Keep `ONEIRODEX_LIBRARY_WATCH` off unless you accept best-effort events.

## Non-goals (still)

- Full product redesign of scan jobs UI
- Watching every nested ROM file on arcade sets
- Auto-enable on new installs / enabling watch while env is off
- Discord / external webhooks

## Code

- `oneirodex/utils/library_watch.py` — controller + classify + ops pulse + per-lib filter
- `oneirodex/utils/library_health.py` — `path_status` + `path_health_fields`
- `oneirodex/utils/notifications.py` — `library_added` digests
- Started from `create_app` alongside the scan scheduler
- Tests: `tests/test_library_watch.py`, `tests/test_browse_path_status.py`
