# Admin Ops summary (`services` contract)

> **Doc status:** Active

**Audience:** Admins / operators reading Admin → Ops  
**Endpoint:** `GET /admin/api/ops/summary` (admin session)  
**UI:** `/admin/ops` and Dashboard poll ~15s (**silent** auto-refresh — no toast spam). On Dashboard, manual refresh is the **reset icon beside Updated** in the status banner (no duplicate footer timestamp). Dashboard widgets are a 12-column board: drag a widget (not its buttons) to move — the tile follows the pointer via transform and commits on release; drag the **bottom-right corner** to resize (~1.85× a cell of travel per step). No grab bar. **Reset layout** sits in the thin top-bar trail as a `od-cbtn` (library-style), beside account. Layout persists in `localStorage` key `od-admin-dashboard-layout-v3` (a key bump also clears sticky bad layouts). Metric tiles fill the row width; panel titles (Host meters, Companions by kind) match metric-label type. A first poll that fails uses the shared status block (Retry) rather than empty host panels. Services table scrolls when the list is long. **Grafana-style observability console** (Member UI + Ops wave Pass A–F): status strip + `issues.items` in **two folds** — **Action required** and **Warning / Info** (empty folds hidden). Banner label/tone follows items: any action-fold item → Action required; else soft items only → Warning / Info; else healthy. Dense metric tiles (load / RSS / db_ping / awake / companions / **library watch** / **library health**), host meters, services/scans/errors tables. Library watch shows **off** + env note when `ONEIRODEX_LIBRARY_WATCH` is unset (default). Library health shows compact score · grade + top factors (honest **n/a** / “not scored yet” when `library.health` absent or thin); the tile border/value tones by `grade` (`good`/`fair`/`poor`, muted **na** when thin/null); when `grade` is **poor**, the factors list gets a light danger-edged cue; when **fair**, a warn-gold left edge (good/na unmarked). Null metrics render as **n/a** (e.g. `load_avg` on Windows). Backend enrichments: `host.load_avg` · `host.process` · `host.db_ping_ms` · `services.awake` · `services.library_watch` · `library.health` · companions `by_kind` + `last_seen`. **Device list (TC-4):** the Companions panel also renders `GET /admin/api/ops/devices` — one row per heartbeat-registered seat (status · kind · name · member · version · last seen), newest first, `online` judged on the same 3-minute window as the tile; *Device list unavailable* when that call fails, an explanatory empty state when no seat has ever checked in.

**Server logs:** live on **Ops → Full log** (`/admin/ops?open=full-log`). Bookmarks to `/admin/server_logs` / `/admin/system_logs` redirect there.

Top-level keys include `as_of`, `host`, `network`, `issues`, `scans`, `library`, **`services`**, `recent_errors` (plus `*_error` when a section fails).

## `library.health` (lightweight Ops pulse)

Cheap SQL counts on every Ops poll — **not** a filesystem re-scan. Also available at `GET /admin/api/library/health` (same payload). Shape: `{ score: 0–100|null, grade: good|fair|poor|null, factors[{id, label, count, weight, ratio, deduction}], games, thin, note?, checked_at }`. Factors: `missing_cover` · `missing_path` (empty `full_disk_path` **or** scan-flagged `Game.path_status` = `missing`/`empty` — no live `path.exists` on poll) · `no_igdb` (null or custom-range ≥ 2000000420) · `stale_freshness` (OUT/~ = `behind` / `heuristic_behind`) · `unmatched`. Scan/identify refreshes `path_status` (`ok`|`missing`|`empty`); library watch / scan-existing-path also clears `missing`→`ok` when a folder is restored (without waiting on a separate full rescan). When `games == 0`, `score`/`grade` are **withheld** (`thin: true`) so an empty library is not shown as healthy. Legacy per-game detail remains at `GET /api/health/library` (sampled; may `path.exists`).

`issues` shape: `{ overall, items[{id, severity, category?, message, href?}] }`.

| Field | Meaning |
|---|---|
| `overall` | Backend worst-of hint in `{good, warn, bad}` (`info` items do not elevate). UI may re-tone the banner from item folds when present. |
| `items[].severity` | `bad` \| `warn` \| `info` |
| `items[].category` | UI bucket — `action` \| `warning` \| `info`. UI prefers `category`; when absent, maps `bad`→Action required, `warn`/`info`→Warning / Info. Disk capacity (`disk_*_high` / `disk_*_critical`) is **`info`** only — not Warning or Action required. |

**Two-fold policy** (UI + Backend)

| Bucket | When |
|---|---|
| **Action required** (`bad` / `action`) | Stability or service breakers — critical path missing/unreadable, DB unreachable, awake fail |
| **Warning** (`warn` / `warning`) | Soft signals that may indicate a real problem — scan job failures, recent SystemEvents errors |
| **Info** (`info`) | Capacity soft signals (disk % even ≥95% / near-full) and companions stale |

Disk pressure alone never forces `overall: bad`/`warn` or `category: action`/`warning`.

## `host` key (Grafana-style enrichments)

| Field | Meaning |
|---|---|
| `cpu` / `memory` / `disk_*` / uptimes | Existing host pulse |
| `load_avg` | `{1, 5, 15}` load averages when OS exposes them; **`null` on Windows / denied hosts** |
| `process` | App process `{pid, rss_bytes}` via psutil; **`null` when unavailable** |
| `db_ping_ms` | Cheap `SELECT 1` latency (ms); **`null` when DB unreachable** |
| `gpu` | INSP-44: `{source: 'nvml' \| 'reader', gpus: [{name, util_percent, mem_used, mem_total, temp_c}]}` — NVIDIA's own library when the optional `pynvml` package and a device exist, else a BYO LibreHardwareMonitor / HWiNFO-class JSON reader at `TELEMETRY_READER_URL` polled read-only; **`null` when neither answers** and the **GPU** tile reads *n/a*. Nothing bundled, no driver |

## `build` key — what is running, and is it what shipped

| Field | Meaning |
|---|---|
| `version` | The product version, read from the tracked `VERSION` file (one source; a test asserts `app_version` agrees with it) |
| `commit` / `built_at` | The commit the image was built from and when, stamped at build time by `scripts/ops/unraid_ship_update_now.py`. **`null` for a hand-built image** — the tile reads *no build stamp* rather than guessing |
| `schema_revision` | What the database is actually stamped at (`alembic_version`) |
| `schema_head` | What *this code* expects, read from the migration scripts. `null` when the chain has branched, which is worth seeing rather than hiding behind `heads[0]` |
| `migration_pending` | `schema_revision != schema_head`. **`null` means "could not tell"**, which is deliberately not `false` — the one wrong answer here would be a reassuring one at the moment an operator is checking |
| `generator_version` | `GENERATOR_VERSION`, the theme-asset counter that decides whether Reset Themes has work to do |

Collected by `oneirodex/utils/build_identity.py` and **memoised for the process lifetime** — none of it can change while the process runs, since `init_manager` applies migrations at startup, so a migration implies a restart. Every field degrades to `null` and nothing raises: an Ops tile reading *n/a* is honest, one that takes the 15-second poll down with it is not.

Rendered by the **Build** tile on both Admin → Dashboard and Admin → Ops (`BuildTile` in `frontend/admin-app/src/components/opsWidgets.tsx` — one component, because two copies of the thing whose job is to be authoritative is two places to disagree).

## `scans` key

Built by `oneirodex.utils.ops_summary._scan_snapshot`. Poll-friendly (~15s) glance for Unraid library scans — counters come from atomic `bump_scan_job_progress`.

| Field | Meaning |
|---|---|
| `active_count` | Jobs in `Running` or `Stopping` |
| `queued_count` | Jobs in `Queued` (FIFO waiting for Running to finish) |
| `jobs[]` | Active jobs first, then Queued (with `queue_position`), then up to 5 recent `Completed` / `Cancelled` / `Failed` (24h) |
| `jobs[].id` / `id_short` | Full UUID · first 8 chars |
| `jobs[].status` | Enum casing: `Running` / `Stopping` / `Queued` / `Cancelled` / `Completed` / `Failed` |
| `jobs[].queue_position` | 1-based FIFO position when `status=Queued` |
| Drain note | Ops poll best-effort promotes next Queued **only when idle** (same `maybe_drain_scan_queue` gate as `GET /api/scan_jobs_status`). Skip while Running/Stopping so a 15s poll does not contend with the live worker. Scheduler still drains ~60s. |
| `jobs[].folders_success` / `folders_failed` / `folders_processed` / `total_folders` | Live folder counters (`processed` = success + failed) |
| `jobs[].current_processing` | Latest label from the scan coordinator (nullable) |
| `jobs[].last_progress_update` | ISO timestamp of last counter bump (nullable) |
| `jobs[].started_at` | ISO of `last_run` (run start; Queued = enqueue). `created_at` always null |
| `jobs[].elapsed_seconds` / `elapsed_label` | Server-computed elapsed; terminal = start→last progress |
| `jobs[].eta_seconds` / `eta_label` | Honest estimate from throughput; **null** when Queued / zero progress / total unknown / **stalled** / done (no fake countdown) |
| `jobs[].stalled` | True when Running/Stopping with no progress bump for ≥120s |
| `jobs[].library` | Library name when joined cheaply |
| `jobs[].progress` / `errors` | Compat aliases (`%` of done folders · `folders_failed`) |

List/poll with filters: `GET /api/scan_jobs_status?status=Running,Queued&library_uuid=&q=` — see [libraries-and-scans.md](libraries-and-scans.md#run-a-scan).

**Ops UI (`/admin/ops` Scans table):** renders processed (`success+failed`) / `total`, with a `· N failed` suffix when failures > 0 (same honesty as Scan Jobs). Timing fields paint elapsed/ETA when present; ETA stays blank when null/stalled. Full filter chrome (status · library · path, localStorage) lives on **Scan management** — see [libraries-and-scans.md](libraries-and-scans.md#run-a-scan).

## `services` key

Built by `oneirodex.utils.ops_summary._services_snapshot`. Brief field map:

| Field | Meaning |
|---|---|
| `livekit` | Flag + config presence + best-effort TCP reachability (`enabled`, `configured`, `url_set`, `keys_set`, `reachable`, `error`, `note`) |
| `malware` | Module on/off, block-on-hit, ClamAV reachability/version/error, heuristics bag |
| `companions` | Heartbeat pulse — `online` / `registered` within `window_minutes` (default 3) |
| `companions.by_kind` | Per-`device_kind` `{registered, online}` map |
| `companions.last_seen` | Breakdown — `newest` (ISO), `within_1h`, `within_24h`, `stale` (`registered − online`) |
| `queues` | `scans_active`, `scans_queued` (FIFO Queued), `scans_scheduled` (recurring), `scans_pending` (= queued + scheduled), `scans_failures_24h`, `downloads_open` — honest depths from ScanJob / DownloadRequest |
| `game_servers` | Household registry pulse — `count`, `reachable`, per-server `display_name` / TCP or HTTP probe |
| `awake` | In-process readiness snippet — `status`, `http_status`, `checks` (same shape as `/awake`), `check_ms`; **`null` when probe fails** |
| `malware_module_enabled` | Convenience bool mirroring malware module enable |
| `jobs[].error_message` | Why a job stopped, or `null`. Added 2026-08-25 — the payload carried counts, current folder, elapsed, ETA and `stalled` and dropped the one field explaining a failure, so Ops could report that a scan failed and never why. Normalised to `null`: `ScanJob` defaults it to an empty string |
| `library_watch` | Optional root-folder incremental watch (`ONEIRODEX_LIBRARY_WATCH`, default off) — `enabled`, `running`, `roots`, `pending_libraries`, `debounce_seconds`, `last_event_at`, `last_enqueue_at`, `note` |

No Discord / webhook sinks — alerts stay in-app SystemEvents / optional SMTP digest.

**Path issues:** `DATA_FOLDER_GAMES` / `BASE_FOLDER_POSIX` / `BASE_FOLDER_WINDOWS` need **exist + read** only (Compose Unraid often mounts `/storage:ro`, and the base folder that contains it inherits the same RO mount). Uploads / image paths still require write — a RO games/base mount must not appear as `not writable` in `issues`.

## Related

- [troubleshooting.md](troubleshooting.md) — Services tile symptoms  
- [docker-compose-deploy.md](../runbooks/docker-compose-deploy.md) — smoke + workers  
- [challenge-solver-unraid.md](../runbooks/challenge-solver-unraid.md) — TRAWL sidecar (CH-2)  
- [observability-profile.md](../runbooks/observability-profile.md) — in-app vs Prometheus stub  
- [unraid-deploy.md](../runbooks/unraid-deploy.md) — checklist step 0b  

## Danger zone — reset this install

Bottom of **Admin → System (Ops)**. Clears Oneirodex's *database* and returns the
install toward first-boot state.

**It never deletes files.** Scanned games, artwork you supplied, firmware on the
BIOS volume and the theme tree are all left exactly as they are. That is
structural, not a promise: the reset path in
`oneirodex/utils/system_reset.py` has no filesystem access at all, so a rescan
rebuilds the catalog from the media still sitting on disk.

| Scope | Clears | Keeps |
|---|---|---|
| `catalog` | Games, matches, unmatched folders, scan jobs, artwork records, reference sets | Library definitions — rescan immediately |
| `libraries` | The configured libraries, their filters and access grants. **Implies `catalog`** | — |
| `users` | Members, invites, favorites, collections, playtime, chat, saves | **Your own admin account**, so you stay signed in |
| `settings` | Server settings, IGDB/SMTP/API credentials, themes, discovery sections, announcements | — |

Two steps, enforced by the API rather than by the UI:

1. `POST /admin/api/system/reset` with `{"scopes": [...]}` returns the **plan** —
   every table it would empty, including those reached by cascade — and changes
   nothing. This is the default: a call that omits the phrase gets a description
   of the damage, not the damage.
2. Repeat with `"confirm": "RESET ONEIRODEX"` to perform it. `"RESET ONEIRODEX"` still works.

Tables are emptied in one `TRUNCATE ... RESTART IDENTITY CASCADE`, so the reset
is a single transaction — it lands whole or not at all, with no half-cleared
database to unpick.

> **Cascade reaches further than the scope names.** A `catalog` reset also clears
> the per-member rows that point at games — favorites, playtime, saves, owned
> titles. The plan lists them under `cascaded` before you confirm; read it.

Every table in the schema is assigned to exactly one scope, and
`tests/test_system_reset.py` fails if a new model is added without one — so the
reset cannot silently start leaving rows behind as the schema grows.
