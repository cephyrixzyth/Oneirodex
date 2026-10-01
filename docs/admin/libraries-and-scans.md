# Libraries & scans

> 🎬 Watch (narrated): [libraries & scans](../media/video/howto/howto-admin-libraries.mp4) · [ops health](../media/video/howto/howto-admin-ops.mp4) — [all how-to videos, with transcripts](../media/video/howto/README.md)

Admin surfaces today are **Jinja** under `base_admin` (top bar), hosted inside the admin SPA shell (LHN + thin THN).

**Libraries & scans** destinations are separate pages (not one Bootstrap tab document). The **left rail** lists Libraries, Scan, Library tools, Unmatched, Filters, Release filters, Extensions, Image queue, and Art & images. **Scan** is one LHN row; while you are on Scan, the **thin top bar** shows **Auto | Manual**. Other destinations have no sibling strip in the THN.

The Libraries page is an admin SPA **DataTable** (sort + per-column filters, themed `od-cbtn` Scan/Edit/Delete bar, sticky multi-select batch actions). Add library is reached from the Libraries page / command palette — not a THN unfurl.

## Where can a library point?

By default: anywhere under the games folder (`DATA_FOLDER_GAMES`) or the OS base
folder (`BASE_FOLDER_POSIX` / `BASE_FOLDER_WINDOWS`) — Docker mounts both at
`/storage`.

Beyond that, the operator declares extra **scan locations** in
`ONEIRODEX_LIBRARY_ROOTS`: a NAS share, a second disk, another Docker bind. Each one
becomes a starting point in the **Scan location** picker on Auto Scan and Manual,
and a row in Ops path health. The picker only renders once there is more than
one location, so single-location installs are unchanged.

**Symlinks inside a game folder are ignored.** A link such as `game.bin ->
/somewhere/else` is not hashed, bundled, zipped into a folder download, served as
a ROM or used as `cover.jpg` / `screenshot-N.png` / the `oneirodex.json` sidecar —
anything that resolves outside the game's own folder is skipped, because members can
download what the server can read. Symlinking the game folder itself (or the library
root) is unaffected; keep real files, or hardlinks, inside the folder.

A location that is configured but not currently mounted is still listed, marked
*not mounted* — see [../runbooks/remote-scan-locations.md](../runbooks/remote-scan-locations.md)
for mounting recipes per OS and for the Docker host-path-vs-container-path trap.

`GET /api/library_roots` (admin) returns the same list the picker uses:
`{ok, roots: [{id, label, path, source, default, exists, read, write}]}`.

## Add a library

1. Admin → **Libraries & scans** (`/libraries` or `/scan_management?active_tab=libraries`).
2. Point the folder at the games mount (Docker: under `/storage/...`), or pick
   another **Scan location** when the operator has declared extras.
3. Set **scan depth** on create/edit (GET seeds the form; save persists it).
4. **Update library when folders change** — per-library incremental watch (`watch_enabled`: follow global / prefer on / opt out). Global `ONEIRODEX_LIBRARY_WATCH` may still gate Unraid (Ops → Library watch).
5. Prefer a small test scan before a full library scan.

**W22-1 chrome (updated):** Library Management and Scan management share the **Libraries & scans** LHN section. Destinations are separate URLs (`/libraries`, `/scan_management?active_tab=…`). Multi-select libraries (checkbox / select all) → sticky **Scan** / **Edit** / **Delete**. Sticky **Scan** posts `POST /api/admin/libraries/batch/scan` (`library_uuids` + `queue_policy=queue`); per-row and sticky **Edit** open the shared-fields modal on this page → `POST /api/admin/libraries/batch/edit` (`scan_depth` · `watch_enabled` · `platform`; full editor for name/image stays a link inside the modal). Bulk delete offers a **Force delete** checkbox (no typing each name). Prefer the batch APIs below; soft-degrade to sequential single-library calls when a batch route 404s mid-rollout. After theme CSS/JS deploy: **Admin → Themes → Reset Themes** so `library/themes` picks up `admin_manage_libs` — [themes-reset.md](themes-reset.md).

**Library tools** (tidy names, proposals, rename, freshness, propose/import leaves): `/scan_management?active_tab=tools` (LHN). Tool views live in the **thin top bar** — **Add many** (Scan a folder | Import a list inside the pane), Tidy folder names, Review suggested fixes, Rename one game, Check for updates. `/admin/library_tools` redirects there.

## Batch library APIs (W22-1 / UID-003)

Admin-only (`@admin_required` + session CSRF as other `/api/admin/*` POSTs). Partial success on scan/edit; delete returns `ok` only when ≥1 job started.

| Endpoint | Purpose |
|---|---|
| `POST /api/admin/libraries/batch/scan` | Multi-select start/queue scan (cap **100**) |
| `POST /api/admin/libraries/batch/edit` | Shared field patch: `scan_depth` · `watch_enabled` · `platform` (cap **100**; no rename/image) |
| `POST /api/admin/libraries/batch/delete` | Multi-select delete jobs (cap **50**) with typed confirm or `force` |
| `POST /api/admin/libraries/scan` | Single-library scan (unchanged) |
| `POST /delete_full_library/<uuid>` | Single delete (background job). Optional JSON `confirm_name` / `force` — when either is sent, server enforces typed name unless `force=true`. Legacy clients that omit both keep client-only typing. |

**Common body:** `library_uuids: string[]` (aliases `uuids` or singular `library_uuid`).

**Batch scan** — optional `folder` (shared) or `folders: {uuid: path}`; same scan flags as single scan (`scan_mode`, `remove_missing`, `download_missing_images`, `force_updates_extras`, `force_parallel` / `queue_policy`). Skips libs with no `last_scan_folder` and no folder override (`error: no_scan_folder`). Response: `{ ok, started, queued, skipped, failed, count, results[] }` (`results[].status` = `started`\|`queued`\|`skipped`\|`rejected`\|`error`; may include `job_id`, `position`, `risk`, `coalesced`).

**Batch edit** — at least one of `scan_depth` (1\|2), `watch_enabled` (true\|false\|null), `platform` (enum name), or per-row `items: [{uuid, …}]`. Response: `{ ok, updated, skipped, failed, count, results[] }` (`status` = `updated`\|`unchanged`\| skipped/`not_found`). Errors: `400` missing fields / over cap; invalid platform/depth → per-row `ok: false`.

**Batch delete** — without `force`: require `confirm_names: {uuid: exactName}` (or list of `{uuid, name}`) and/or a shared `confirm_name` string applied to every uuid. With `force: true` (alias `force_delete`): skip typed names — still admin + CSRF. Response: `{ ok, started, failed, count, force, results[{uuid, job_id?, error?}], progress_hint }`. Progress unchanged: SSE `/delete_library_progress/<job_id>` · poll `/check_deletion_progress/<job_id>`. Errors: `400` `confirm_name_required` · per-row `confirm_name_mismatch` / `not_found` · cap **50**.

## Delete a library

Admin → **Libraries & scans** → **Libraries** → **Delete** (or multi-select → **Delete**) opens a Bootstrap confirm modal. Single delete: type the library name to enable **Confirm Delete**. Bulk: send exact names via `confirm_names` **or** check **Force delete** (`force=true`) to skip typing. Delete-all (if present) still uses `DELETE ALL LIBRARIES`. Confirm/Cancel must be clickable. If buttons look present but do not respond: rebuild/restart the app (page includes inline stacking CSS), hard-refresh, then optionally **Admin → Themes → Reset Themes** so `library/themes` copies pick up theme CSS/JS fixes — [troubleshooting.md](troubleshooting.md) · [themes-reset.md](themes-reset.md).

## Run a scan

- Start from library tools / scan management (**Auto Scan** / **Manual Scan** / **Refresh all libraries**), `POST /api/admin/libraries/scan`, or multi-select **Scan** → `POST /api/admin/libraries/batch/scan`.
- **Default when a scan is already Running/Stopping:** Backend **queues** the request (`ScanJob.status=Queued`, FIFO). Not silently dropped; not a hard fail. Applies to **Auto Scan**, **Manual Scan** (busy path uses `start_or_queue_scan`; idle Manual still **List Games** for identify), and library scan / refresh-all APIs.
- **Same library already Queued:** coalesce — reuse the existing Queued job (`coalesced: true` in JSON) instead of piling duplicates (matches library-watch skip honesty).
- **Force parallel (admin only):** `force_parallel=true` or `queue_policy=force` starts alongside the running job. Response includes an honest NAS/CPU risk note. Each job still respects `scan_thread_count` / `worker_caps` (do not raise UVICORN_WORKERS for this).
- **Watcher / multi-path bursts:** When optional `ONEIRODEX_LIBRARY_WATCH` (Wave 3) or Admin refresh enqueues many paths while a job is Running, prefer **Queue** over force-parallel so FIFO drains under Unraid CPU caps — [unraid-deploy.md § Library root watch](../runbooks/unraid-deploy.md#library-root-watch-gt_library_watch--unraid-honesty).
- Request fields (JSON or form): `queue_policy=queue|force` and/or `force_parallel=1`. Response: `{ status: "queued"|"started"|"rejected", job_id?, position?, message, risk?, coalesced?, coalesced_count? }` for honest toasts (`Queued · position N`, optional `· coalesced` when same-library jobs merge).
- **UI:** When a scan is already busy, Scan management opens a conflict modal — **Queue this scan** (default focus) or **Force run now (parallel)** with an Unraid/NAS load warning — on **Auto Scan**, **Manual Scan** (busy path only; idle Manual stays **List Games** identify), Refresh all, and restart-while-busy (Admin SPA Libraries / Scans also offer Refresh all + the same modal). Flask flashes Backend `message` (includes position / coalesce). JSON surfaces (Refresh all) toast `queued` / `started` / `rejected` (`Queued · position N`, optional `· coalesced`). Classic Scan management skips overlapping job polls and hidden-tab ticks. A live scan patches the progress cell in place (it does not rebuild the jobs table every 3s). Unmatched folders are fetched only while that pane is visible. The React Scans / Ops / Dashboard polls skip hidden tabs and overlapping fetches. After theme CSS/JS updates, **Admin → Themes → Reset Themes** (`GENERATOR_VERSION` **21**) so `library/themes` picks up `admin_manage_scanjobs.js` and `scanJobsDom.js`.
- `POST /api/admin/libraries/refresh_all` uses the same policy (enqueue libs as Queued + promote first when idle; force runs a sequential worker in parallel with any Running job).
- **Drain reliability:** when a job leaves Running/Stopping (Complete / Fail / Cancel), Backend promotes the oldest Queued job. The **scan scheduler** (~60s) always reclaims stale busy jobs then promotes. **`GET /api/scan_jobs_status`** and the **Ops summary** poll also drain — but **only when no job is Running/Stopping**, so a 3s Libraries & scans poll does not contend with the live worker (that contention froze admin for tens of minutes on Unraid). Idle+Queued still drains on the next poll so a missed promote recovers without waiting a minute. Worker early-exit / crash paths mark Failed so the queue cannot stick forever. Reclaim of a dead owner while a row still says Running waits on the scheduler (~60s), not on every status tick.
- **New-game toasts wait for the scan (UX-B7).** Staff get one `library_added` digest when the job finishes (or is cancelled after titles landed), not a stream of "N games added" mid-pass. Watch/import still debounce. **More than five** live toasts collapse to **N notifications**. Classic pages use the same dismissible aurora toast as the SPAs (`static/js/od_toast.js` replaces `$.notify`).
- Scan jobs / Ops glance show **Queued** rows (`scans.queued_count`, `jobs[].queue_position`, `queues.scans_queued`). `GET /api/scan_jobs_status` includes `queue_position` for Queued rows.
- **Wave 18 timing + filters (API):** `GET /api/scan_jobs_status` (and Ops `scans.jobs[]`) expose server-computed timing: `started_at` (= `last_run` ISO — run start; Queued = enqueue time), `created_at` always `null` (no create column), `folders_processed`, `elapsed_seconds` / `elapsed_label`, `eta_seconds` / `eta_label` (**null** when Queued / zero progress / total unknown / **stalled** — no fake countdown), `stalled` (no progress bump for ≥120s while Running/Stopping). Query filters (server-side): `status=` (comma list of Running|Queued|Stopping|Completed|Failed|Cancelled|Scheduled), `library_uuid=`, `q=` / `name=` (substring on `scan_folder` or library name).
- **Scan Jobs redesign:** LHN **Scan Jobs** is the full jobs table (When column, clear completed/failed/all, CSV export). Auto/Manual keep a compact **Scan jobs** modal. Schedules support Once, 8/24/48h presets, every N minutes/hours, and 5-field cron. **Cron is evaluated in UTC** (the field says so), and follows crontab day semantics: when day-of-month *and* day-of-week are both set, the job fires on days matching either one (`0 3 1 * 1` = the 1st and every Monday). An unsatisfiable expression (Feb 30) is rejected at save; an unknown schedule option is refused rather than silently armed as a one-shot. Scan mode includes **Auto** (folders vs files heuristic). After theme asset deploys: **Admin → Themes → Reset Themes**.
- **Wave 18 Scan management UI:** Scan Jobs table shows elapsed / ETA / stalled from those fields; toolbar filters by **status**, **library**, and **path/name** (`q`), persisted in **localStorage**. After CSS/JS deploy: **Admin → Themes → Reset Themes** so `admin_manage_scanjobs` picks up the new chrome.
- **Admin SPA (W28):** the React admin now has the two controls that previously only existed on the Jinja surface.
  - **Libraries** table has a **Scan** button per row. It posts `POST /api/admin/libraries/scan` with just `library_uuid`, letting the route fall back to the library's `last_scan_folder`. `GET /api/get_libraries` returns `last_scan_folder` so the button can disable itself and say why rather than posting a request the route is bound to reject ("No last scan folder — run one Auto Scan from Libraries & scans first").
  - **Scan jobs** table has **Scan again** on any job that is not Running or Queued. It repeats *that job* — its `scan_folder`, its `setting_filefolder` / `setting_remove` / `setting_download_missing_images` — rather than re-scanning wherever the library currently points, which is the difference between a retry and a new scan. A job with no `library_uuid` shows the button disabled with an explanation.
  - Both use the same busy check and the same **Queue / Force parallel** conflict modal as Refresh all, and both always send `queue_policy` + `force_parallel`.
- Watch job status on Ops / scan UI.
- Propose-only mode (when enabled) writes proposals instead of committing matches — review before apply. Toggle under **Settings → Scan / match policy** (`/admin/scan_match` — **W20-4 Done**; `GET|PUT /api/admin/scan-match/config`) or **Server Settings** (`proposeOnlyScan`). Policy page also covers dupe/match thresholds and peel profile. No mega-lib / depth-3 family walk.
- Progress (`N/total`) uses atomic counter bumps so multithreaded scans stay honest while titles land in the library.
- **Stop** sets status to Stopping, finishes in-flight folders (those still count), cancels the rest, then shows **Stopped N/total** — not a blank action cell. Cancel also clears **Queued** jobs before they start.
- **Worker starvation guard:** scan/image turbo threads are hard-capped at runtime (default **4** each) even if Admin Server Settings store a higher value. New installs default to scan threads **1**, turbo threads **4**, turbo batch **100**. Scan futures submit in chunks; brief cooperative yields between completions. Env overrides: `ONEIRODEX_SCAN_THREAD_CAP` (default 4), `ONEIRODEX_IMAGE_DOWNLOAD_THREAD_CAP` (default 4), `ONEIRODEX_IMAGE_DOWNLOAD_BATCH_CAP` (default 100), `ONEIRODEX_WORKER_YIELD_MS` (default 5).
- **Optional root-folder watch (`ONEIRODEX_LIBRARY_WATCH`, default off):** when enabled, watches each library `last_scan_folder` except `watch_enabled=false` (per-lib opt-out; null/true follow global). Scan-depth–aware game leaves only; not deep arcade ROM trees. Debounces 2–5s and **enqueues** FIFO ScanJobs (add / change with updates refresh / delete honoring last remove-missing policy). New titles emit debounced staff notification kind `library_added`. Browse/favorites expose `path_status` + `path_missing` (filter `path_status=missing`). Never starts unbounded scan threads. Ops pulse: `services.library_watch`. Details: [library-root-watch-spike.md](library-root-watch-spike.md) · Unraid mount limits: [unraid-deploy.md](../runbooks/unraid-deploy.md#library-root-watch-gt_library_watch--unraid-honesty).

## Unmatched folders

Admin → Scan management → **Unmatched Folders** tab lists rows the scanner could not auto-match, plus true duplicates and ignored entries. Each Unmatched/Pending row shows a quiet **Why unmatched?** one-liner from Backend fields (`why_unmatched` / `unmatched_reason` when present, else `match_reason` + `suggested_kind*`) — same copy on Admin Dashboard **Dupe glance**. When Backend sends `match_score`, it appears as a compact chip beside the Why label (null-safe; omitted when absent). **W20-2:** when `transforms[]` is present, a **Name transform trail** expander lists ordered Stage A0–A14 peels (`stage · before → after · reason?`); soft-degrades when the field is missing/empty (mid-rollout). **W21-UI-1:** when `stage_e_candidates[]` / `stage_e` (or nested proposal) is present, a quiet **Stage E · propose only** chip + expandable MobyGames / TheGamesDB candidates appears (catalog hints only — Identify to apply; not auto-matched); soft-degrades when Stage E fields are absent from the list API. Short `match_reason` codes stay for filters; no disk rename.

**Duplicate scope:** Duplicate means the same title already exists on the **same system (library platform) and ROM region**. Cross-system copies (NES + SNES + Switch) are intentional editions — scan imports them without sharing the unique `igdb_id`, and browse title-grouping still pairs the tiles. **Fix false duplicates** also downgrades stale cross-system / region-mismatch Duplicate rows.

**Unmatched chrome:** Actions live in the THN (`Clear Unmatched` · `Clear All` · `Fix false duplicates` · `Backfill kind hints` · one **Export** dropdown for CSV/JSON). The panel itself is filters + a compact table (Region column, Actions menu per row, library/system/region/page-size selects, pager). List API defaults stay a bare array for compatibility; the page requests `paginate=1&limit=&offset=` for faster loads. After CSS/JS deploy: **Admin → Themes → Reset Themes**.

**Wave 17 UI (classic scanjobs + Dupe glance):** filters toolbar (status · search · Why chips · suggested-kind chips), row checkboxes + sticky batch bar, inline **Search name** (label exact; secondary **On disk: {basename}**; soft `search_name` / optional `display_name` — never disk rename; formerly “Amend naming”), and **Dupe of …** on the **base table** (thumb · name · uuid · path · match_score) so operators see the library hit without opening Dupe glance. Disk tidy this wave = **Open path** only. Soft-degrades when batch/name/`matched_game` endpoints are mid-rollout (client filter + `/duplicates` enrich + per-id fan-out). **W27-C4:** Duplicate **Compare** has **Pop out** — same two-column path/size/date at readable width. After CSS/JS deploy: **Admin → Themes → Reset Themes**.

**W20-7 UI (unmatched triage filters):** Admin → **Libraries & scans** → **Unmatched Folders** adds **Layout** chips (**ROM files library** / **Folder library** — ROM/archive file vs named folder; client heuristic in `unmatchedTriage.js`; formerly labeled “leaf”) and **Triage** chips (**Platform mismatch** — path platform hint disagrees with library assignment · **Garbage** — installers/redistributables/temp scaffolding). Each row shows matching badges in the **Folder** column (under **Search name**). Sticky batch bar adds **Ignore selected** — tries `POST /api/unmatched_folders/batch/ignore` first, then falls back to per-id `toggle_ignore_status` when batch is unavailable. Scan toasts use upper-right `od-toast-host` (library-style). After deploy: **Admin → Themes → Reset Themes** (or hard-refresh) so `library/themes` copies pick up `admin_manage_scanjobs` / `admin_manage_libs` CSS/JS/HTML and `unmatchedTriage.js`.

**W21-UI-1 (Stage E propose-only chips):** Unmatched Folders + Dupe glance surface `stage_e_candidates` / `stage_e` when the list (or nested proposal) already returns them — quiet honesty, no auto-match implication. After deploy of `admin_manage_scanjobs` CSS/JS + `stageECandidates.js`: **Admin → Themes → Reset Themes**.

Per-row actions:

- **Open path** — **OpenPathModal** queues companion `open_path` via `POST /api/client/commands` (`{ action: "open_path", path, select: true, game_uuid: "" }` for unmatched). Clipboard fallback when the companion is offline. Path-info only: `GET /api/path/open?path=`. Does **not** jump to Auto Scan. The browser cannot open paths on a remote Unraid host directly.
- **Copy path** — copies the full on-disk folder path to the clipboard.
- **Fix search / Identify as game** — opens manual add/identify with the folder's basename cleaned (release-group tags, dots/underscores, scanning filter patterns stripped) and prefilled as the search query — same cleanup the auto-matcher uses. When a soft **Search name** (`search_name`) is set on the Unmatched row (Wave 17), Fix/identify prefer that over the cleaned basename. Soft Search name never renames the on-disk folder.
- **Search name (soft)** — `PATCH`/`POST /api/unmatched_folders/<id>/name` `{ search_name?, display_name?, name? }` (`name` aliases `search_name`). Stores librarian-facing search/display strings only; `folder_name` stays the derived basename; `folder_path` unchanged. Batch: `POST /api/unmatched_folders/batch/amend`. Operator label is **Search name** (not “Amend naming”).
- **Mark as Soft title / Emulator / Utility** — `POST /api/unmatched_folders/<id>/mark_kind` catalogs the folder as gaming software (custom-range Game + `item_kind` token `experience`|`emulator`|`tool`) **without** inventing an IGDB Main Game match. Success/error toasts are honest. Also available on Admin Dashboard **Dupe glance** (filter Unmatched). Prefers soft `search_name` when set.
- **Backfill kind hints** — quiet toolbar action (`POST /api/unmatched_folders/backfill_suggested_kind`) fills null `suggested_kind` from on-disk proposal sidecars for legacy rows; confirm dialog; toast shows updated/scanned counts. Idempotent.
- **Ignore / Clear / Delete** — unchanged (ignore hides from future scans, Clear drops the row only, Delete removes the folder from disk). Batch clear (DB only): `POST /api/unmatched_folders/batch/clear` `{ ids }` (cap 100; partial success).
- **Export** — `Export CSV` / `Export JSON` buttons download the currently filtered set via `GET /api/unmatched_folders/export?status=…&q=…&why=…&suggested_kind=…&library_uuid=…&format=csv|json` for offline triage.

**Duplicate glance + fix (Wave 2a shipped; Wave 17 Dupe of on base table):** Admin Scan management / Dashboard **Dupe glance** shows Duplicate / Unmatched rows with Open path, Fix search, Mark as Soft title/Emulator/Utility, Merge/Keep/Ignore, Fix false duplicates, and the same **Dupe of …** library hit as the Scan management base table. Wave 17 list/export nest `matched_game` on Duplicate (or `matched_game_uuid`) rows so the base Unmatched table can show the dupe target without opening Dupe glance.

| Endpoint | Purpose |
|---|---|
| `GET /api/unmatched_folders` | List (+ filters: `status` · `q`/`name` · `why`/`reason` · `suggested_kind` · `library_uuid`). Rows: `folder_name` (basename RO) · `search_name` · `display_name` · `match_reason` (short code) · `match_score` · `suggested_kind*` · `why_unmatched` / `unmatched_reason` · `transforms[]` `{stage,before,after,reason?}` (Stage A0–A14 peels; W20-2) · optional `stage_e_candidates[]` / `stage_e` (Stage E propose-only; **W21-BE-2b** denormalized JSON columns — soft-omitted when absent; no list N+1) · `matched_game` `{uuid,name,path,cover_url,igdb_id?}` or null |
| `GET /api/unmatched_folders/export` | Same filters + row shape (CSV flattens `matched_game_*`; omits nested `transforms`) |
| `GET /api/unmatched_folders/duplicates` | Compare payload for Duplicate rows (`titles[]` / `candidates[]` + `matched_game` + `transforms[]`) |
| `PATCH`/`POST /api/unmatched_folders/<id>/name` | Soft amend `{search_name?,display_name?,name?}` — **no** disk rename |
| `POST /api/unmatched_folders/batch/clear` | `{ids:[]}` clear rows (DB only; cap 100; partial OK) |
| `POST /api/unmatched_folders/batch/mark_kind` | `{ids:[], item_kind}` (cap 100; partial OK) |
| `POST /api/unmatched_folders/batch/fix` | `{ids:[], action: merge\|keep\|ignore}` Duplicate triage (cap 100; partial OK) |
| `POST /api/unmatched_folders/batch/amend` | Soft amend batch `{ids:[], search_name?, display_name?}` or `{items:[{id,search_name?,display_name?}]}` |
| `POST /api/unmatched_folders/backfill_suggested_kind` | One-shot fill null `suggested_kind` from proposal sidecars (`dry_run?` · `limit?`; idempotent) |
| `POST /api/unmatched_folders/<id>/fix` | `{action: merge\|keep\|ignore}` — merge clears the row (keep library game); keep → Unmatched; ignore → Ignore. Writes `duplicate_fix_logs` |
| `GET /api/unmatched_folders/fix_logs` | Queryable how-matched / how-fixed history |
| `GET /api/path/open?path=` | Path string only for Desktop OS explorer — **no** Auto Scan redirect. Queue reveal via `POST /api/client/commands` `{action:"open_path", path, select?}` (allowlisted under library roots; `game_uuid` optional). |

**PC extras on scan (Wave 2a):** PC libraries associate common under-game `DLC`/`extras` folders (+ sibling `Title DLC` sidecars). Details `extras[].on_server` is honest — missing disk presence stays false. Console/ROM DLC ingest remains deferred (GM-locked).

The unmatched table stretches with the Scan management page (`od-adminpage--xl`, ~1600px): each entry opens with a **top actions bar** (**UID-005**) — Open path / Fix search / Mark… / Ignore / Clear / Delete — and Merge/Keep/Ignore on Duplicate; long paths wrap/break, and a horizontal scroll wrapper covers narrow windows. Column headers **Folder · Status · Library · Platform** are client-sortable (click toggles asc/desc). The **Resolve Unmatched** toolbar is a single centered equal-width pill bar (Clear All / Clear Unmatched / Fix false duplicates / Backfill kind hints / Export). Dashboard **Dupe glance** mirrors actions-on-top plus Folder/Status/Library/Platform sort. **UID-016 (Done uncommitted · UI QA PASS 32/32 · BE QA PASS 13/13):** Duplicate rows use a side-by-side **Compare** — **This folder** | **Library game** (path · size · date). Soft-read UI already shipped; Backend list/`matched_game` expose null-safe `size_bytes` / mtime aliases — **Library game** size/date come from `Game.size` + dates; **This folder** size stays null until a folder-size denorm lands (honest empty, not a fake 0). After theme CSS/JS updates, **Admin → Themes → Reset Themes** (or hard-refresh) so `library/themes` copies pick up `admin_manage_scanjobs` changes.

## After scan

- **Edit game entry / Identify** groups its fields into tabs — **About** (summary, storyline, developer, publisher) · **Release** (status, release type, rating, date) · **Links & media** · **Taxonomy** (genres, modes, themes, platforms, perspectives). IGDB ID, name, provider search and disk path stay above the tabs, since those are what the page is opened for. A tab whose fields failed validation is marked and opens first, so an error can never hide behind a closed tab. The panels are still server-rendered and post to the same handler; only the tab bar is React.
- **Provider links** (Links & media tab) hold one URL per provider — Steam, GOG, Epic, itch, RAWG, MobyGames, TheGamesDB, official site, Wikipedia — stored as the same `GameURL` rows scanning writes, so a link typed here and one IGDB filled in are the same record. Previously only IGDB's URL had a field, so a Steam or GOG page found while identifying had nowhere to go. Blank removes that provider's link; non-http values are refused and the stored one is kept. Rows this form does not own (`youtube`, patch guides) are untouched by a save.
- Unmatched titles → Identify workbench (IGDB / Steam / GOG / RAWG / Epic / itch / GiantBomb / MobyGames / TheGamesDB / Meta·Quest via IGDB platforms). IGDB search is filtered by `LibraryPlatform` enum name → `platforms.id` (`igdb_platform_id_for`). Game Boy Color is 22. Unmapped leaves (CreatiVision, Adventure Vision, Studio II, Action Max, Daphne, Pinball) search unfiltered. The edit workbench used to look up the display label and miss every filter.
- **Stage D (W20-5a + W21 harden + store providers):** IGDB miss → resolve exact Steam / GOG / Epic hit → **one IGDB retry** with the store’s canonical title → still miss → custom-range Game from that store candidate. Steam App ID path only when store details + title corroborate. Wrong-namespace `(digits)` fall through (no bogus `steam_app_id`). Ambiguous or miss → Unmatched as below. Operator toggles: **Admin → Integrations → Metadata** (`GET|PUT /api/admin/integrations/metadata-providers`; defaults all on).
- **Four-source corroboration (W34):** a high-confidence IGDB hit is still checked against Steam / GOG exact title plus unique-exact MobyGames / TheGamesDB when those keys are set. If another catalog has a unique exact title that matches the **folder** but not IGDB (folder `Doom` / IGDB `Doom 3` / Moby `Doom`), the scan writes a Review proposal (`match_reason=catalog_disagreement`) and does **not** auto-create or run name-truncation fallbacks. Remaster/subtitle store titles that do not identity-match the folder are treated as no-signal, not a veto. Agreeing catalogs fill-only `steam_app_id` / `steam_url` and GameURL rows — never a DRM download URL. **Agreement floor (H1d):** `IDENTIFY_AGREEMENT_MIN` (default **1** = today) says how many sources must name the title before the scan auto-imports it — IGDB counts one, each agreeing catalogue row one more. At `2`, a title only IGDB named goes to Review with `match_reason=insufficient_agreement` (*Only IGDB named this title; the scan asks for a second source to agree before importing*) instead of importing. Raise it on a library where a wrong auto-match costs more than a review row; it needs at least one catalogue key set to be satisfiable.
- **Gaming software / emulators / tools** (not IGDB Main Game) — Steam search includes `type=software` by default (`include_software=1`). Results carry `steam_type` + `item_kind` (`game`|`experience`|`emulator`|`tool`). On IGDB miss **after Stage D miss/ambiguous**, scan writes a proposal with `software_candidates` + `suggested_kind`, and **denormalizes** `suggested_kind` + `suggested_candidate_name` (+ Stage E `stage_e_candidates` / `stage_e` when present) onto `UnmatchedFolder` at propose/log time (list API reads DB columns only — no N+1 sidecar I/O). `GET /api/unmatched_folders` (+ export CSV/JSON) returns `suggested_kind`, `suggested_kind_label`, `suggested_candidate_name`, plus `folder_name`, `match_reason`, `match_score`, **`rom_region` / `rom_languages`** when peel/path captured them (**BE-DET-4**), and a deterministic `why_unmatched` / `unmatched_reason` one-liner for UI explainers; export JSON also soft-includes Stage E fields when denormalized. Legacy rows with null hints + on-disk proposal sidecars: one-shot `POST /api/unmatched_folders/backfill_suggested_kind` (`{dry_run?, limit?}`; idempotent; sidecar reads only for null-hint rows). Unmatched UI + Dupe glance show a **Suggested …** chip when present and pre-bias **Mark as…**. Catalog via Unmatched **Mark as Experience / Emulator / Tool** (`POST /api/unmatched_folders/<id>/mark_kind` `{item_kind, name?, steam_app_id?}`) → custom-range Game (`igdb_id ≥ 2000000420`) with `item_kind` set; clears Unmatched. Library tiles/details show **EXP** / **EMU** / **TOOL** badges for non-game kinds. Member browse: `GET /browse_games?item_kind=` (comma list; alias `content_kind=`; omit = all kinds); same on `/api/favorites`. Library SPA Kind chips (Games · Experiences · Emulators · Tools) multi-select that param. Stay on **PCWIN** (no Apps platform). Never auto-treat Steam software as IGDB Main Game; no DRM download queues.
- **Meta Quest Store & Epic** are **metadata + ownership register only** — Oneirodex never downloads DRM titles from those stores. Epic can live-sync the register via unofficial device auth (or CSV). Optional Meta CSV: `POST /api/ownership/meta_quest/csv`. Identify modes via `META_QUEST_API_MODE` (`igdb` default · `csv_only` · `disabled` · `unofficial_graphql` off unless `META_QUEST_UNOFFICIAL_GRAPHQL=1`). Optional `META_GRAPH_ACCESS_TOKEN` is reserved for a future official catalog.
- Identify metadata search: `GET /api/search_metadata?name=…&source=steam|rawg|gog|epic|itch|giantbomb|mobygames|moby|thegamesdb|tgdb|meta_quest|meta|quest` · Steam: `&include_software=0` to hide software · source list: `GET /api/search_metadata/sources`.
- **MobyGames (W20-5b + W21 Stage E):** optional `MOBYGAMES_API_KEY` (or `GlobalSettings.mobygames_api_key`) — empty results when unset (honest, no 500). Manual identify + **Stage E propose-only** exact-title hints after Stage D miss (no Game create). Metadata/cover URLs only.
- **TheGamesDB (W20-5c + W21 Stage E):** optional `THEGAMESDB_API_KEY` (or `GlobalSettings.thegamesdb_api_key`) — empty results when unset (honest, no 500). Manual identify / covers + **Stage E propose-only** platform-filtered exact-title hints on console leaves after Stage D miss (no Game create). Sibling guards reject Color/Advance/Wii U/Jaguar CD/Amiga CD32/Pocket Color/PS2+/Xbox 360+ hits on the short library leaf. Leftover dump suffixes (`.sg` `.sgx` `.min` `.cpr` `.adf` `.mgw` `.ssd` `.uef` `.bbc` …) are in `PLATFORM_ROM_EXTENSIONS` and default allowed file types. A new platform suffix in that map is seeded on boot.
- **Identify is fast-path:** when a scan job creates a game, folder-size walk, Steam enrichment, cover/screenshot download, and HLTB run on a background thread after the row commits (`queue_post_identify_enrichment`). The library can show the title before size/covers finish.
- **Manual Identify taxonomy:** on save, the server re-fetches IGDB (non-custom ids) and **creates missing** Genre/Theme/GameMode/Platform/Perspective rows before attach — same upsert as scan identify, so checkbox-only names that were not yet in the DB are not dropped. Steam enrich also applies **genres** (+ mapped game modes), not only summary/VR.
- Manual identify / add still sizes the folder inline (capped ~60s) and enriches inline (or uses the existing image-refresh thread).
- Covers may also fill via missing-image tools; freshness tools mark OUT/~ titles.
- **Library health (light):** Ops `library.health` / `GET /admin/api/library/health` — deterministic cover · empty/`path_status` missing · no-IGDB/custom-range · OUT/~ · unmatched score (0–100, grades good|fair|poor; withheld when no games). Scan refreshes `Game.path_status`; Ops poll stays SQL-only — [ops-summary.md](ops-summary.md#libraryhealth-lightweight-ops-pulse).
- Members see new platforms on **Systems** (`/systems`) once platforms appear in `/api/library_platforms`.

## Scan depth

| Value | Behavior |
|---|---|
| **1** | Treat each immediate child folder of the scan root as a game |
| **2** | Unwrap letter buckets (`_a`…`_z`, `_#`) then treat *their* children as games |

**Required for letter-bucket PC trees:** if the library root is something like `…/_pc` whose children are `_a`…`_z` / `_#` (not the games themselves), set **scan_depth = 2**. Depth 1 will treat each letter folder as a “game” and miss thousands of real titles. Flat roots (`…/_software-games`, installed `…/games`) stay at **1**.

Folder → IGDB matching cleans the folder basename in Stage **A0–A14** (`parse_game_label`: scene/repack brackets + unbracketed suffixes, Incl Update / Update·Build prose, date-stamps, version/build/VR/EA junk, Steam App ID, edition/add-on peel, franchise apostrophe inject, VR re-pass after version), then expands search variants (colon subtitles, trailing bare `1` strip, `2`/`II` sequel swaps, year/pack/edition peel, Steam title as query #0 when App ID resolves, C11 bare-franchise propose-only · **C14** punctuation-light dotted acronyms). **Done (uncommitted, QA 166 PASS)** (local strategy notes). Peel aggressiveness + score thresholds are operator-tunable — [Scan / match policy (W20-4)](#scan--match-policy-w20-4).

**W22-match + BE-DET-1…8 (Done uncommitted · W22-match QA PASS 138+10 · **BE-DET-8 QA PASS 141/141** · be_det8 **14/14** · region/lang **QA PASS 118/118** · multi-disc **QA PASS 119/119** · DoD met · live skipped):** Console ROM peel gate is **GB / GBC / GBA / NES / SNES / N64 / NDS / NGC / WII / PSX / PSP / SEGA_MD / SEGA_MS / SEGA_GG / SEGA_CD / SEGA_SATURN / SEGA_DC / ATARI_2600 / NEOGEO / NEOGEO_CD / ARCADE / SWITCH** with `scan_mode=files` always, and with `scan_mode=folders` when the leaf basename (or primary dump inside the folder) looks No-Intro/GoodTools — e.g. `Super Mario Bros. (USA)`. **SWITCH** folders also gate on scene/repack brackets (A1) or unbracketed scene suffixes (A10). **ARCADE / Neo Geo AES** folders also gate on compact MAME/FBNeo set basenames; large ARCADE trees + compact set names are **propose-first** (no aggressive fuzzy auto-import); **NEOGEO** vs **NEOGEO_CD** never cross-map (AES≠CD TGDB guard). B15 strips P1 + Dreamcast forms (`.nds` `.gcm` `.rvz` `.wbfs` `.pbp` `.cso` `.nsp` `.xci` `.gdi` `.cdi` …). Fresh installs seed matching AllowedFileType defaults; existing DBs may need Admin → file types for missing extensions (incl. `gdi`/`cdi`). Plain folder names still use `parse_game_label`. PCWIN never uses console peel. Bare folder basenames `UPDATE` / `Updates` never auto-import — `match_reason=update_package_folder` + plain-language **Why unmatched?** note; `suggested_kind` stays null (**not** Soft title). Kind mark/filter labels use **Soft title** / **Utility** (API tokens still `experience` / `tool`). Default match threshold still **0.92**. **BE-DET-4:** identify/scan/rematch/custom/DAT persist peeled `rom_region` / `rom_languages`; Unmatched list + CSV/JSON export expose the same fields for triage. **BE-DET-5:** multi-disc dump sets peel `(Disc|Disk|CD N)` for the match title, collapse to one Game + `GameExtra(extra_kind='disc')`, filter cue+bin companions, persist `disc_index`/`disc_count`, and expose `is_multi_disc`/`discs[]` on browse/details (SPA disc chips UI later). **BE-DET-6:** DAT inner archive. **BE-DET-7:** Saturn / Dreamcast / Neo Geo CD gate + Redump fixtures + SWITCH A1∪B16. **BE-DET-8 Done (uncommitted · QA PASS 141/141 · be_det8 14/14):** Arcade / Neo Geo AES set-folder peel · propose-first large ARCADE · AES≠CD. **Next:** **BE-DET-9** fandom. After ship: rescan gated files-mode leaves + dump-shaped folders-mode leaves (incl. disc/late + Arcade/AES).

**UI-W22-M7 + UID-004 (Done uncommitted · QA PASS):** Member SPA Kind chips + admin Unmatched / Dupe glance / mark-kind copy show **Soft title(s)** / **Utility(ies)**; Library tile badges keep short **EXP** / **TOOL** text with tooltips **Soft title** / **Utility**. **UID-004 Done** (Kind Soft title/Utility + Amend → **Search name** residual cleared · **QA PASS 33/33**). **QA PASS** member **32/32** · DupeGlance **21/21** · DoD met · live skipped. Post-deploy: **Reset Themes** for `admin_manage_scanjobs` (SPA Kind chips ship with member-app dist rebuild — Reset Themes alone does not refresh SPA).

**Stage D (W20-5a + W21 App-ID harden + Epic + provider toggles):** After IGDB high-confidence miss (and not C11 / propose-only), scan resolves an exact Steam / GOG / Epic store candidate (App ID path only when Steam details + title corroborate). If the store title was not already searched, scan runs **one more IGDB pass** with that title before creating a custom-range Game (`igdb_id ≥ 2000000420`, register-only store links — Steam / GOG / Epic `GameURL`, no fuzzy auto-import). Wrong-namespace folder `(digits)` no longer stamp a bogus `steam_app_id` on details miss. Ambiguous or miss → Unmatched + software proposal as today. Disable individual stores under **Integrations → Metadata** (also skips them in the PC enrichment cascade).

**Stage E (W21-BE-2, uncommitted):** After Stage D miss → propose-only MobyGames (PC) / platform-filtered TheGamesDB (console) exact-title hints on proposal sidecar + `suggested_candidate_name` — **no** Game create. Keys optional (skip silently when unset). **DAT unique-hash (W21-BE-DAT + BE-DET-6):** after Stage D miss, unique CRC/MD5/SHA1 vs uploaded reference sets may auto-create a custom Game before Stage E; when the outer zip/7z/rar digest misses, optional inner dump hashing (`DAT_HASH_INNER_ARCHIVE`, default ON) identifies only on exactly one unique DAT title; ambiguous/missing DAT stays Unmatched. **Hash identify (INSP-31, v11 H1a):** when no uploaded DAT knows the file (outer digest, then the inner dumps), the same digests are asked of a keyless community hash service (`HASH_IDENTIFY_BASE_URL`, default `https://hasheous.org`; `ENABLE_HASH_IDENTIFY=false` or the **Integrations → Metadata → Hash identify** switch turns it off). A named answer creates the same custom-range Game the DAT path would, with a summary that names the service and the matched digest (and the IGDB id it proxied, when it did); any miss, error or unparseable answer is a miss and the title stays Unmatched. Identity only — never enrichment, never a download; off under pytest.

**MobyGames (W20-5b, uncommitted):** Manual identify source (`source=mobygames|moby`) + Stage E propose-only. Optional `MOBYGAMES_API_KEY` — empty results when unset. Not Stage D auto-import. **Ops:** app restart for `mobygames_api_key` · set key for live hits.

**TheGamesDB (W20-5c, uncommitted):** Manual identify source (`source=thegamesdb|tgdb`) + Stage E propose-only on console. Optional `THEGAMESDB_API_KEY` — empty results when unset. Not Stage D auto-import. **Ops:** app restart for `thegamesdb_api_key` · set key · **Reset Themes** for identify JS.

Depth does not recursively walk whole trees per title; per-game stalls were from sync folder-size walks on large NAS volumes (now deferred on scan).

## Scan / match policy (W20-4)

**Done (uncommitted):** Admin → **Settings → Scan / match policy** (`/admin/scan_match`) + Settings hub · React `ScanMatchSettingsPage` · vitest **7/7** claimed · BE `GET|PUT /api/admin/scan-match/config` live (scoring / dupe / peel wired · pytest claimed **13+21**). Persists on `GlobalSettings` (`settings.scan_match` JSON + `propose_only_scan`). Unset keys use defaults: `match_high_threshold` **0.92**, `match_ambiguous_gap` **0.08**, `dupe_title_threshold` **0.85**, peel `conservative`.

| Knob | Effect |
|---|---|
| Propose-only scan | Never auto-import (proposal sidecars even on high confidence) |
| Dupe title threshold | Same-IGDB collision → Duplicate vs Unmatched |
| High-confidence / ambiguous gap | `match_scoring` classify / `select_best_match` |
| Peel profile | `conservative` (shipped A0–A14) · `aggressive` (extra edition display peel + looser A10) |
| Safe Stage C toggles | Year-drop · pack peel · edition peel · sequel numeral (default on) |

**Not offered:** mega-lib / depth-3 family walk (API refuses). `scanThreadCount` remains under Server Settings / worker caps. **Post-ship:** Reset Themes **not** required for this API (UI shell already shipped).

## Identify sources deferred (documented, not built)

Two register items from the capability harvest were sized in H1 and deliberately **not** built. Each has a trigger; until it fires, the pipeline above is the whole story.

| Item | What it would add | Why not now | Trigger that would schedule it |
|---|---|---|---|
| **INSP-33 — offline hash index** | A signature file (No-Intro / Redump class, hashes → title + platform) fetched once or shipped, so a **first scan on a disconnected box** still identifies console dumps with no provider reachable. Same lookup interface as `try_dat_hash_identify`, so it would slot in beside the uploaded DATs and before the keyless hash service (INSP-31, shipped H1a). | The uploaded-DAT path already gives an offline identify for any set the operator owns; the hash service covers the rest when the box is online. A bundled index is tens of MB per platform family and a redistribution question for the signature groups; a fetched one is INSP-31 with a cache. | A user report of a first scan on an air-gapped box, **or** the hash service going away. Then: `HASH_INDEX_PATH` pointing at an operator-supplied DAT bundle folder, walked by the existing parser — no new format. |
| **INSP-7 — community ROM metadata as a Class D source** | Region art, manuals and arcade-era metadata from a community database with an operator account, for titles where IGDB is thin (arcade, obscure home computers). | Class D (account, ToS-bound) sources are opt-in only and each one is a `SourceSpec` plus a key to place; the hash service already proxies an IGDB id for most dumps, and the Art Studio stock packs cover the art gap for the themed rooms. Nothing in the current inventory is blocked on it. | An operator with the account asking for it, with the ToS read (scrape-free API, key in hand). Then: one `SourceSpec` in `metadata_cascade.py`, `CONSOLE_ORDER` only, plugin + inventory rows, `None` on any failure — the H1a shape. |

## Scanning filters

Admin → Scan management → **Scan Filters** (also legacy `/admin/edit_filters`). One list, two behaviors:

| Kind | How you enter it | What it does |
|---|---|---|
| **Name tag** | Plain text (e.g. `GOG`) | Matcher strips `-tag` / `.tag` from folder basenames before identify — does **not** hide folders |
| **Skip folder** | Prefix `dir:` (e.g. `dir:_MyTools`, `dir:OpenVR*`) | Folder listing skips matching basenames (case-insensitive **fnmatch**). Built-in emu/FE/tool + scaffolding + mod/repack defaults already apply; Admin rows add extras |
| **Skip folder (regex)** | Prefix `re:` (e.g. `re:\[Demo\s+Build\]`) | Folder listing skips basenames matching the regex (case-insensitive). Built-in generic `[… Repack]` bracket-tag regex already applies |

**UI:** How-it-works copy, examples, Kind column, and **Quick add** chips that fill the modal (Name · GOG / Open Source / Public Domain; Skip · `_MyTools` / `OpenVR*` / `Tools*` / `_Extras`). Type toggle auto-prefixes `dir:` for skip rows. Prefer **prefix** globs (`dolphin*`, `GOD v*`) over substring (`*dolphin*`, `GOD*`) so real titles are not skipped.

Skip-dir is **defense-in-depth only** — still create per-leaf libraries; do not point a lib at a family root and rely on skips. There is no separate filter-kind API column; kind is encoded by the `dir:` or `re:` prefix on `filter_pattern`. Case sensitivity is stored as `'yes'|'no'` on `filters.case_sensitive` (String); both Scan management and legacy Edit filters write that form, and the scan loader accepts legacy bool / `1|0` / true-false strings. After theme CSS/JS updates, **Admin → Themes → Reset Default Themes** so `library/themes` picks up `admin_manage_scanjobs` changes.

**Quality profiles (P1-12):** Active profile `blocked_groups` + `excluded_terms` are merged into the same name-clean strip patterns as Name-tag filters during scan. Preferred groups/patterns + size bands score / prefer-exclude *arr search hits (`GET /api/arr/search`; disallowed hits omitted unless `include_disallowed=1`). Admin → **Quality profiles** SPA `/admin/quality_profiles` (list · set active · new · delete · edit · score probe) via `/api/quality-profiles`.

**Batch refresh images:** Librarian+ Library sticky **More → Refresh covers** · `POST /api/games/batch/refresh_images` `{ uuids }` (max **20**, 202 `{ queued, skipped, errors }`) enqueues the same IGDB refresh path as single-game refresh; ACL per title; skips missing / forbidden / no `igdb_id`.

## After A0–A14 ship — Library A PCWIN rescan

**When:** Stage A0–A14 name-resolution is on **origin** and the Unraid image is rebuilt from that commit (human ship). Do **not** run a live full rescan from an agent Task alone.

**Library:** Library A — platform **PCWIN**, folder = letter-bucket PC root under the games mount (container path under `/storage/.../_pc` with children `_a`…`_z` / `_#`).

**Path rule:** Operators and agents edit the live checkout (`Z:\_projects\Oneirodex` / `/mnt/user/example-share/_projects/Oneirodex`). Games stay on `/mnt/user/example-share/_software/_games` — library `folder` paths and host mounts stay as configured. `/mnt/user/isos/oneirodex/` is retired.

### Exact operator steps

1. **Preflight** — Host disk free (not ~99%); stack healthy (`/awake`); Admin → Themes → **Reset Default Themes** + confirm member-app dist in View Source — [unraid-deploy.md § Deploy gates](../runbooks/unraid-deploy.md#deploy-gates-operator-checklist).
2. **Confirm depth** — Admin → Libraries → Library A (PCWIN): **`scan_depth = 2`**. Save if wrong.
3. **Propose-only first** — Start a scan with propose-only enabled (writes proposals / unmatched without committing low-confidence matches). Watch Admin → Scan jobs / Ops `scans.jobs[]`. Stop if overlapping full jobs exist.
4. **Review** — Admin → Scan management → Unmatched Folders (+ any proposal review UI). Spot-check letter buckets; Fix search / Identify as needed.
5. **Full rescan** — After propose-only looks sane, run a **full** Library A scan at `scan_depth=2`. One full job at a time on this tree.
6. **Sign-off** — Ops glance healthy; unmatched count trend down vs pre-A0–A14; no games-RO false alarms on Ops issues.

Games mount stays **`:ro`**. Rescan identifies and enriches metadata; it does not rewrite the games share.

## Console / emulator trees (`_console-gaming`)

Do **not** create one library on a mixed console root (families + emulator installs + tools). Prefer **one library per platform ROM/game leaf** with the correct `LibraryPlatform`, `scan_mode` **files** (flat dumps) or **folders** (folder-per-game), and `scan_depth` **1** (or **2** only if that leaf uses letter buckets).

Never library-root: `_Emulators`, named emu installs, Pegasus/CRU/tools, archive-only parents. Document typo paths as-is (e.g. `Ninentdo Entertainment System`).

**Propose leaf libraries (W20-1):** Admin → **Libraries & scans → Library tools** (`/scan_management?active_tab=tools`) → **Add many: scan a folder**. Enter a root path under allowed bases → **Propose** → multi-select candidates (platform, mode, depth, path, reason) → **Confirm create**. Uses existing `POST /admin/library/add` per selected leaf, then queues a first scan via `POST /api/admin/libraries/scan` so `last_scan_folder` remembers the leaf — **never** auto-creates on Propose; never suggests family mega-lib roots. Pointing at the games mount (`/storage`) walks `_console-gaming` (skip-dir name, still a family tree) and proposes `_pc` as **PCWIN** `folders`/`2`; walkthroughs and emu installs stay out. Soft-degrades if `GET|POST /api/library_tools/propose_leaf_libraries` returns 404 mid-rollout. API returns `{ path, suggested_name, platform, scan_mode, scan_depth, reason }` with `auto_create: false`. Heuristics: flat ROM files → `files`/`1`; title dirs → `folders`/`1`; letter buckets → `folders`/`2`. Switch leaves → `SWITCH` + `folders`/`1` (catalog honesty — no WebRetro CTA invent). `MAME` zip dumps propose as **ARCADE** `files` (not a family parent).

**CSV/JSON bulk import (W20-1b):** Admin → **Libraries & scans → Library tools** → **Add many: import a list**. Paste JSON/CSV or upload `.json`/`.csv` → **Preview** → multi-select candidates (row `errors[]` shown separately) → **Confirm create**. API: `POST /api/library_tools/import_leaf_libraries/preview` (JSON body, multipart file, or form `csv`/`text`). Same candidate fields as propose (`path`, `suggested_name`/`name`, `platform`, `scan_mode`, `scan_depth`). Returns `{ auto_create: false, candidates[], errors[], count, error_count, create_hint }`. Hard rejects: family mega-lib parents (`NINTENDO`/`Sega`/`Sony`/…), invalid `LibraryPlatform`, path outside allowed bases. **Never auto-creates** — confirm-create reuses the propose path (`POST /admin/library/add` per selected row + first scan). Soft-degrade UI if the preview route 404s mid-rollout; UI refuses if `auto_create === true`.

**Empty shelves (systems with no dumps yet):** Systems tiles come from Library rows, not from the enum list. A leaf with 0 games still shows. Household placeholders (VB / Wii / Wii U / 3DS / Pokémon Mini / Vita / Xbox siblings / Commodore 8-bit / CD-i / Pico / Jaguar CD / Amiga CD32 / MSX / ZX Spectrum / Amstrad CPC / Atari ST / Apple II / Atari 8-bit / X68000 / PC-98 / BBC Micro / Game & Watch) are on the games share as of 2026-08-30. Import [empty-shelf-import.csv](empty-shelf-import.csv) via **Add many: import a list**, then confirm create (never auto). Propose-from-tree is the secondary path. Do not point at a missing path and hope scan invents files. Full folder table + remaining enum-gap list: console-gaming-libraries.md (local-only reference). Oneirodex never fetches ROMs.

**Skip-dir (defense-in-depth, W20-7 handoff #4):** folder listing ignores built-in emu/FE/tool **prefix** globs (`_Emulators`, `yuzu*`, `ryujinx*`, `dolphin*`, `bsnes*`, `pegasus*`, `cru-*`, `GOD v*`, `xenia*`, `zinc*`, `mame0*`, …), emulator scaffolding (`Config`, `Lang`, `Plugin`, `ROMs`, `docs`), scan-root leaks (`_console-gaming`, `_pc`), walkthrough trees, MOD/VR-mod markers, and generic `[… Repack]` bracket-tag folder names (built-in regex). Patterns are mostly **prefix** globs so titles like *God of War* or *Ecco the Dolphin* are not skipped. Operators add extras via Admin → Scan management → **Scan Filters** — **Skip folder** (`dir:` fnmatch, e.g. `dir:_MyTools`) or **Skip folder (regex)** (`re:`, e.g. `re:\[Demo\s+Build\]`) — see [Scanning filters](#scanning-filters). No API route change; kind is encoded by the `dir:`/`re:` prefix on `filter_pattern`. This does **not** replace per-leaf libraries — do not point a lib at a family root and rely on skips. There is no `scan_depth=3` family walker.

## Image queue

Admin → Scan management → **Image Queue** tab manages artwork downloads (kinds below).
Prefer **Admin → Settings → Art studio → Pick & queue** (`/admin/art_studio#images`) for the React artwork picker + mass queue chrome.
For library hero / site-wide fallback variety, use **Art studio → Backup & stock** (`/admin/art_studio#stock`) — platform packs + stock motifs. Library create/edit forms include a **Choose image** link to that tab.

**Image kinds (BE-DET-10):** persisted on `Image.image_type` as `cover` · `screenshot` · `box` · `cart` · `disc` · `logo` · `hero` · `fanart`. Existing cover/screenshot rows map 1:1. Queue list accepts `?kind=` or `?type=` (rejects unknown). Game list: `GET /api/game_images/<uuid>?kind=`. Singular kinds keep one primary row per game; screenshots stay multi. UI Edit Images filter chrome lands later (Art/UI).

- **Preview** column shows a thumbnail once a file is downloaded and still present on disk; a striped placeholder shows for pending/failed rows.
- **Group by game** toggle clusters rows by title with a per-group Failed/Pending count badge, instead of one flat paginated list. Group headers include **Open picker** (Art studio Pick & queue) and **Classic edit**.
- **Status** is `Pending` / `Downloaded` / `Failed` / `File missing` (marked downloaded but the file is gone from `IMAGE_SAVE_PATH` — re-download to fix). Hover a Failed badge for the recorded reason (network error, HTTP status, disk permission, blocked URL). Queue JSON also returns `failure_reason` and `image_save_path` (`exists` / `writable` / `error`) so Unraid operators can see a read-only images volume immediately. React **Pick & queue** shows `failure_reason` on each row and banners `image_save_path.error`.
- **Retry failed** re-attempts every image with a recorded failure in one click (`POST /admin/api/download_images` with `retry_failed: true`); per-row Retry does the same for one image.
- **Auto-pick best** → `POST /admin/api/covers/batch/apply` with `policy=sgdb_then_igdb_then_generate` (optional library / platform / service from identify sources).
- **Mass cover search** → `POST /admin/api/covers/batch/search` with the same filters.
- **Mass / single cover selection** (admin):
  - `POST /admin/api/covers/search` — `{ game_uuid?|query, providers?, limit? }` → candidates across SteamGridDB / IGDB / GiantBomb
  - `POST /admin/api/covers/apply` — `{ game_uuid, url, provider }`
  - Identify chips (SPA picker): `GET /api/search_metadata/sources` + `GET /api/search_metadata?source=meta_quest|epic|itch|giantbomb|mobygames|thegamesdb`
  - `POST /admin/api/covers/batch/search` — filter `library_uuid` / `platform` / `service` / `missing_cover`
  - `POST /admin/api/covers/batch/apply` — same filters or `game_uuids` + `policy` (`sgdb_then_igdb_then_generate` | `provider:igdb` | `generate_only` | …)
- Failures are recorded on the `Image` row (`last_error`, `last_attempt_at`) by every download path (batch, single, turbo, and the eager cover/screenshot fetch during scan/identify) so a permissions or network problem on `IMAGE_SAVE_PATH` shows up in the UI instead of silently leaving images stuck "pending".
- A cover that HTTP-200s but is a 1×1, a tiny stub, or a near-solid wash is replaced with titled studio art on download (scan, queue, turbo, retry). Screenshots and other kinds are not inspected — a dark loading screen is real content.
- Identify/match accepts bare IGDB image ids **or** expanded `{id, url}` objects for cover and screenshots (`store_image` normalizes int-or-dict — expanded cover dicts used to be dropped, leaving screenshots-only / branded **No cover art**). Cover is queued whenever IGDB provides one; until the local file lands, browse/details resolve the remote `download_url` instead of the branded placeholder.

## Deploy note

Games volume is often **read-only** in Compose (`/storage:ro`). Scans identify and enrich metadata; they do not rewrite the games share unless you mount RW and use tools that allow it.

Related: [themes-reset.md](themes-reset.md) · [settings-modules.md](settings-modules.md) · [unraid-deploy.md](../runbooks/unraid-deploy.md)
