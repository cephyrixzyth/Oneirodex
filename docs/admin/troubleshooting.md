# Troubleshooting (admins)

## Container / boot

See [container-wont-start.md](../runbooks/container-wont-start.md) for SECRET_KEY, bash, DB.

| Symptom | Check |
|---|---|
| App unhealthy | `curl -f http://localhost:5006/awake` · `docker compose logs app` · DB healthy? Compose probes **`/awake`** (not `/`) |
| Liveness only | `curl -f http://localhost:5006/pulse` — process up; does not prove DB |
| Sidecars / queues look wrong | **Admin → Ops** (or Dashboard) observability console — status + two-fold `issues.items` (**Action required** = path/DB/awake; **Warning** = soft problem signals; **Info** = disk capacity even ≥95% — never Warning/Action) · silent ~15s poll + manual Refresh · load/RSS/db_ping/awake · LiveKit · malware · library watch (`ONEIRODEX_LIBRARY_WATCH`, default off) · companions by kind · queues · game servers; then `/awake` — field map: [ops-summary.md](ops-summary.md) |
| Need server logs URL | **Admin → Ops** → **Full log** (or `/admin/ops?open=full-log`; old `/admin/server_logs` redirects) — [ops-summary.md](ops-summary.md) |
| Ops tiles show **n/a** for load / RSS / db_ping | Expected when OS denies load averages (Windows), psutil unavailable, or DB unreachable — not a broken UI |
| Ops flags `DATA_FOLDER_GAMES` / `BASE_FOLDER_POSIX` / `BASE_FOLDER_WINDOWS` `not writable` | Expected on Unraid `:ro` games mount (and its base folder) only on **older** builds — current Ops treats games + base folder as read-OK; rebuild/restart app if still bad. `UPLOAD_FOLDER` / library must stay RW |
| Scan progress looks stalled / want live counters | **Admin → Ops** **Scans** tile (polls `/admin/api/ops/summary` ~15s) shows processed (`success+failed`) / `total`, plus failed count, `current_processing`, status, elapsed/ETA when present (**ETA blank when stalled/unknown**) — [ops-summary.md](ops-summary.md#scans-key) · **Scan management** for status/library/path filters + Stop/detail |
| Schema errors | Startup builds schema in `init_manager` Phase 2 (`create_all` + frozen `updateschema.py`); Alembic then owns forward change and a pre-Alembic DB is stamped at the baseline on first boot (`Stamped existing schema at Alembic baseline` in init logs). Verify a fresh DB with `python -m alembic upgrade head` · [alembic-baseline-notes.md](../dev/alembic-baseline-notes.md) · [local-postgres-pytest.md](../runbooks/local-postgres-pytest.md) for local tests |
| App loops waiting for DB: `no pg_hba … no encryption` | Postgres rejects non-SSL from Docker bridge — [container-wont-start §3b](../runbooks/container-wont-start.md#3b-postgres-up-but-pg_hba-rejects-app-no-encryption); recreate `db` with current Compose `pg_hba` mount |

## Frontend dist missing

Rebuild so `oneirodex/static/dist/member-app` and `admin-app` exist:

```bash
docker compose build --no-cache && docker compose up -d
```

## SPA navigates but pages/admin hang (Discover stuck on Loading)

Default Docker uses **`UVICORN_WORKERS=1`**. A long-lived sync SSE on `/api/activity/stream` used to run through WsgiToAsgi and **starve** Discover, Library APIs, and Jinja admin on that same worker. Symptoms: shell/nav works, CSS/JS 200, `/api/activity/stream` 200, then **no** `/api/discover/sections` (or admin never finishes).

**Fix (current code):** ASGI serves `/api/activity/stream` and `/api/events/stream` natively (non-blocking); Flask WSGI handlers return **503** if reached. The Friends companion only opens activity SSE when the dock is open. Rebuild/restart the app container after pull:

```bash
docker compose build app && docker compose up -d app
```

Confirm in logs that after `/discover` you also see `GET /api/discover/sections` (or Admin HTML) completing. Keep `UVICORN_WORKERS=1` unless you accept split in-process SSE/schedulers — see [docker-compose-deploy.md](../runbooks/docker-compose-deploy.md).

## Features / modules

Product toggles live under **Admin → Features** (and setup → Features). Env flags in `.env` / Compose still win for safety locks. See [settings-modules.md](settings-modules.md).

| Symptom | Check |
|---|---|
| Malware scan never runs | `ENABLE_MALWARE_SCAN` off — check Admin → Features |
| Library scan skips suspicious names | Expected when `MALWARE_SCAN_BLOCK_ON_HIT=true` (heuristic or ClamAV match) |
| ClamAV unreachable | Start `docker compose --profile clamav up -d` or set `CLAMAV_SOCKET` for host clamd — heuristics still apply when scan module is on |
| LiveKit “on” but no voice | Flag alone is not enough — need `LIVEKIT_*` + compose `--profile livekit` |
| OIDC button missing | `OIDC_ENABLED` stays **off** until env + Integrations toggle |
| Help / Trailers missing on Systems (or Chat / Collections) after a full reload | Older build: `member_bp` never injected Server Settings into the SPA shell, so Jinja treated the flags as off. Current tree bakes `showHelpButton` / `showTrailers` into every `render_member_spa()` page. Restart the app after the Python hotfix. |

## Security headers / uploads

Baseline headers (`nosniff`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`) are always
sent and need no configuration. CSP **enforces** by default (`CSP_ENFORCE=true`).

| Symptom | Check |
|---|---|
| Console full of “Content Security Policy … would block” | A leftover inline handler or `eval`. Classic pages use `data-gt-*` + `od_dom_actions.js`. Set `CSP_ENFORCE=false` only to report without blocking |
| Set `CSP_ENFORCE=true` and browser play broke | Unexpected: WebRetro is `/static/*` with **no CSP**. Check that you did not put a CSP on the native static handler. Flask `script-src` is `'self'` only |
| Classic button does nothing after upgrade | `onclick=` was removed. Confirm `od_dom_actions.js` loads from `base.html` / `base_admin.html` |
| Site pinned to HTTPS and now unreachable by IP | HSTS. It is only sent when `SESSION_COOKIE_SECURE=true`; set `HSTS_SECONDS=0` and clear the browser's HSTS entry |
| Large firmware upload rejected with 413 | Global ceiling is `MAX_UPLOAD_MB` (default 128). Raise it *and* `EMULATOR_BIOS_MAX_BYTES` together — the per-route firmware limit is the tighter of the two |
| Firmware folder scan says the path is outside allowed directories | The folder must be under a library root or the path in `BIOS_IMPORT_SOURCE`. Set that env to the dump pack (and its subfolders) then Scan collection again — [emulator-bios.md](../runbooks/emulator-bios.md) |
| A connector (qBittorrent, SABnzbd, Prowlarr, Ollama, ambient lighting…) fails with `URL host could not be resolved` | The server dials the address a host name resolves to and refuses a name it cannot resolve, so DNS from *inside the container* must answer for it (a compose service name needs the same network; a LAN name needs `extra_hosts` or the IP). It can still be saved while DNS is down. Acquire shows "Could not reach the download service" and the log has the exception type and host, never the URL's query string |
| Firmware scan finds fewer files than the folder holds, or a game's NFO text or `version.txt` version is empty | Symbolic links inside the collection / game folder are skipped on purpose (see [libraries-and-scans.md](libraries-and-scans.md)); keep real files or hardlinks there |
| A folder download stops part-way and the browser reports it failed or incomplete | A file in the game folder was removed, became unreadable or was replaced by a link after the download started, and the server cuts the transfer off rather than finish a damaged zip. Look for `ZIP download aborted mid-stream` in the log, check what is rewriting the share, then download again. (Older builds finished such a download as a corrupt zip with a clean 200, and a file dated before 1980 failed the whole download) |
| Cheat upload refused with 409 and "Cheat storage on this server is full" | Total `.cht` storage reached `CHEAT_STORAGE_MAX_BYTES` (default 256 MB). Delete unused cheat files, or raise the limit |
| Cover uploads suddenly smaller on disk | Expected. Covers over 1200×1600 are now stored resized; previously the resize ran and the original was saved anyway |
| Companion stopped authenticating after an upgrade | Not expiry — tokens created before `expires_at` existed are NULL, which means never. Check Admin → the token was not revoked |
| Metadata art stopped downloading from one provider | The provider may be answering with a redirect to a private/link-local host, which is now refused. Look for `http_retry blocked` / `download_image blocked` in the log |
| Browser play dead after upgrading; companion Play fine | The libretro cores are no longer shipped in the image — they are fetched on first boot. Give it a minute, then check the log for "Fetched N WebRetro core(s)". If the fetch is off or failed: `./scripts/fetch-webretro-cores.sh --defaults` — [webretro-cores.md](../runbooks/webretro-cores.md) |
| Air-gapped box, browser play never works | Expected. Set `FETCH_WEBRETRO_CORES_ON_BOOT=false` and provision with `--from-dir`; boot logs a warning naming the missing cores rather than failing quietly |
| "Get the source code" link missing from Help / admin footer | `ONEIRODEX_SOURCE_URL` is empty. It renders only when set, because a dead source link is worse than none. **Running a modified build? Point it at your fork** — AGPL §13 obliges you to offer your users your source, not upstream's |

## Integrations

| Integration | Notes |
|---|---|
| GOG / Epic / Amazon sync 401 | Token expired or unofficial API changed | Re-paste a refresh token / device-auth / Nile JSON. CSV still works. Oneirodex does not download those stores |
| Ownership poller skipped GOG, Epic, or Amazon | No per-account credential and no household env | Save a token on Ownership, or set `GOG_REFRESH_TOKEN` / `EPIC_DEVICE_AUTH` / `AMAZON_REFRESH_TOKEN` |
| Connector or provider calls fail only behind `HTTP(S)_PROXY` | A proxy applies by the **host name** in the URL, and the name (not a pinned IP) goes to the proxy. Add LAN connector hosts (`nas.lan`, `.lan`, or an IP/CIDR) to `NO_PROXY`; see [settings-modules.md](settings-modules.md#outbound-proxies-and-url-forms). Through a proxy, DNS-rebinding protection rests with the proxy |
| Connector URL refused as `Invalid URL` | Backslash, space or other characters RFC 3986 does not allow in the host part, or an impossible port. Percent-encode special characters in an embedded password (`@` → `%40`) or use the username/password fields |
| Community chat | BYO Stoat/Matrix URL only |
| Discord | **Removed** — use Support inbox + in-app admin alerts |
| LiveKit | [livekit-unraid.md](../runbooks/livekit-unraid.md) · Plugins → `rtc.livekit` |
| SMTP help (?) unclickable after open | Same stacking trap as library delete — help modal is hoisted to `document.body` + inline z-index on Integrations. Hard-refresh; optional **Reset Themes**. |

## Support tickets not on GitHub

Expected if `SUPPORT_GITHUB_TOKEN` unset (`github_sync=skipped`). Ticket + admin notification still work — [support-inbox.md](support-inbox.md).

## Voice

| Symptom | Fix |
|---|---|
| Status disabled | `ENABLE_LIVEKIT=true` + URL/key/secret on **app** |
| Browser can’t connect | `LIVEKIT_URL` must be reachable from the **browser** (not only Docker DNS) |
| Child screenshare 403 | By design |

## Libraries / admin UI

> **"Hard-refresh" in the rows below is no longer the fix for stale theme CSS.** Until 2026-08-16 a
> completed **Reset Themes** could stay invisible for up to an hour — static files were served
> `public, max-age=3600` with no validator, and a reset rewrites theme files *in place at the same
> URL*, so the browser had no reason to re-fetch. Theme URLs are versioned by mtime+size now and
> `/static/library/themes/` serves `no-cache`, so a reset takes effect on a normal reload. Treat a
> hard refresh as a diagnostic, not a step: **if it changes anything, that is a bug worth reporting**,
> not the expected workflow. The rebuild/Reset-Themes halves of these rows still apply —
> [themes-reset.md](themes-reset.md).

| Symptom | Check |
|---|---|
| Admin Settings hub looks broken (four stacked glass cards, unstyled On/Off text, titles clipping) | Hub layout lives in `admin-app.css`, not theme volume CSS. Rebuild the image so `frontend/admin-app` dist refreshes. **Reset Themes does not restyle this page.** Server Settings overflow was the same bundle (`min-width: 800px` + nested cards). — [settings-modules.md](settings-modules.md) |
| Admin rail / top bar / pages hidden — only the decade-room wallpaper shows | Decade-room atmosphere is `position: fixed; z-index: -1` with `isolation: isolate`. Admin `#admin-app-root` / `.od-admin-shell` are `display: contents`, so a z-index on those wrappers never lifts chrome. Current `od-era.css` stacks `.od-rail` / `.od-topbar` at z-index 2 and `.od-admin-main` / `#admin-legacy-content` at z-index 1. Rebuild/restart (boot syncs default theme CSS). If a colour-cabinet preset still hides chrome, **Reset Default Themes**. Member Library backdrop is `position: absolute; z-index: -1` inside the content column. |
| Delete library Confirm/Cancel unclickable | Theme CSS under `static/library/themes/` can pin `.modal` under `.modal-backdrop`. Current Libraries page ships **inline** stacking CSS + moves the modal to `document.body` (works after **app rebuild/restart** without Reset Themes). Also run **Admin → Themes → Reset Themes** so library theme CSS/JS match the image. Hard-refresh Admin → Libraries. |
| Any Bootstrap admin modal unclickable (Filters, Extensions, Scans Add Filter, Discovery shelves, Users, Downloads, SMTP help) | Same stacking trap: glass/`backdrop-filter` parents. Admin + member shells load `js/od_modal_stack.js` which hoists every `.modal.fade` to `document.body` (also on `show.bs.modal`). Rebuild/restart app; hard-refresh; optional Reset Themes. |

## Scans / identify

| Symptom | Check |
|---|---|
| **Browse** does nothing on Scan management — no folder list, no spinner, no error | **Fixed 2026-08-25.** Not a permissions or mount problem: the button had no click handler at all. The page activated its tab strip by ids the current chrome (`ENABLE_NEW_CHROME`, **on** by default) no longer renders, which threw and aborted the rest of the page's startup script before the Browse wiring ran. The scan-location picker staying hidden and the active tab not surviving a reload are the **same** fault, not separate ones. Rebuild/restart, then **Admin → Themes → Reset Themes** so `admin_manage_scanjobs.js` refreshes. Still dead afterwards? Open the browser console and look for `TypeError … reading 'closest'` — if it names a *different* script, that page has the same class of bug. — [themes-reset.md](themes-reset.md) · [remote-scan-locations.md](../runbooks/remote-scan-locations.md) |
| Listing finds many games but each identify takes forever | Fixed: scan identify no longer walks the whole game tree for size before commit; size fills in background. Restart app / re-run scan after upgrade. |
| Size shows `0.00 KB` briefly after scan | Expected until deferred size job finishes (large Unraid trees). |
| Progress stuck at 1 while library keeps growing | Fixed: multithreaded counter races + Stop early-exit. Redeploy app; counters use atomic bumps and Stop drains in-flight work. |
| Stop button looks empty / Cancelled shows `-` | Fixed: Stopping shows “Stopping…”; Cancelled shows `Stopped N/total`. Hard-refresh scan management after upgrade. |
| Admin Libraries & scans hangs / freezes during a live scan (buttons and tab switches dead; `/awake` may also be slow) | Two layers. **Server:** status poll used to run `drain_scan_queue` on every 3s tick — skip-drain-while-Running shipped 2026-08-30. **Client:** a live scan still rebuilt the jobs table (and the unmatched list, even on Libraries) every 3s because progress ticks changed the skip signature; the scan motif SVG remounted each poll. **Fixed 2026-08-31:** patch progress in place, fetch unmatched only on that pane, 3s poll only while Auto is visible and a job is running. Rebuild/restart, then **Reset Themes** (`GENERATOR_VERSION` **21**) so `admin_manage_scanjobs.js` and `scanJobsDom.js` refresh. |
| Admin account menu is a horizontal strip of links, not a dropdown | Member dropdown layout lived only in `TopNav.css` (member SPA) and `od-chrome.css` (`.member-spa-content` only). **Fixed:** `od-shell.css` + admin `AdminTopNav.css`. Rebuild admin SPA **and** **Reset Themes** (`GENERATOR_VERSION` **21**). |
| **Every scan says "queued" and never starts** | Fixed (2026-08-24). A scan orphaned by a restart or a crash stayed `Running` in the database, so `is_scan_busy()` reported busy and new scans queued behind a job no thread was working on — for up to **6 hours**, until the stale sweep aged it out. Scan jobs now record the process that owns them, and a job whose owner is gone is reclaimed on sight: at boot, on the **scan scheduler** (~60s) and before any new scan is accepted. Status/Ops polls no longer reclaim on every tick while a job is Running (that froze admin). If you are still on an older build, restarting the app clears it. |
| **A scan says only "Failed" with no reason** | Fixed (2026-08-25). The scan jobs table translated two specific failure messages into friendly statuses and showed every other one as a bare "Failed" — including the message the ownership sweep writes when it reclaims an orphaned job. Any failed job now shows its reason under the status. Needs a restart or **Admin → Themes → Reset Themes**, since the table's JS/CSS ship from the theme volume. |
| Scan progress changes the moment the page refreshes | Fixed (2026-08-25). First paint counted only successful folders; the poll counts successes + failures. A job with any failed folder showed one number on load and another two seconds later. Both now count processed the same way. |
| Stuck jobs / unmatched / freshness | [libraries-and-scans.md](libraries-and-scans.md) |
| Scan unmatched table cramped / no Open path after deploy | Theme CSS/JS under `static/library/themes/` can lag the image. Rebuild/restart, then **Admin → Themes → Reset Themes** so `admin_manage_scanjobs` CSS/JS refresh; hard-refresh Scan management. — [themes-reset.md](themes-reset.md) · [libraries-and-scans.md#unmatched-folders](libraries-and-scans.md#unmatched-folders) |
| Libraries & scans missing LHN destinations / Scan Auto\|Manual after chrome deploy | Volume copies of `admin_manage_scanjobs` + `od-shell.css` lag the image. Rebuild/restart, then **Admin → Themes → Reset Themes**; hard-refresh `/libraries` and `/scan_management`. — [themes-reset.md](themes-reset.md) · [libraries-and-scans.md](libraries-and-scans.md) |
| Library tools is still a separate page | It is an LHN destination under Libraries & scans (`/scan_management?active_tab=tools`). `/admin/library_tools` redirects there. If the row is missing after deploy, **Reset Themes** so templates refresh. |
| Unmatched Compare has no **Pop out** | Theme-volume `admin_manage_scanjobs.js` / `.css` are stale. **Reset Themes**, then reload Unmatched. |
| Admin pages still look 1100px / nested glass after densify deploy | Theme volume copies lag. **Admin → Themes → Reset Themes**, hard-refresh. See [themes-reset.md](themes-reset.md) P1 densified-admin row. |
| Images stuck "Pending" forever, or covers missing after scan/identify despite `IMAGE_SAVE_PATH` being writable | Fixed: the eager cover/screenshot download run during scan/identify was discarding its result (and, for covers, downloading twice) instead of recording success/failure. Every download path now sets `is_downloaded`/`last_error` on the `Image` row — check Admin → Scan management → **Image Queue**, filter **Failed Only**, hover the red badge for the reason, then **Retry failed**. |
| Matched game shows branded **No cover art** placeholder but screenshots/IGDB summary are present | Cover ref shape bug: expanded IGDB `cover` objects (`{id, url}`) were passed into `where id={dict}` and the cover row was never stored, while screenshot id lists still worked. Identify/match now normalizes int-or-dict refs, reuses embedded URLs, and keeps `download_url` for remote display until the local file lands. If `IMAGE_SAVE_PATH` is not writable, `last_error` records that and the remote URL still resolves. Retry from Image Queue or re-run identify image refresh. |
| Cover tile is a blank / near-solid hole even though Image Queue says Downloaded | IGDB (and other CDNs) sometimes 200 a 1×1 or a wash. Download now inspects covers and replaces those with titled studio art. Re-download from Image Queue or **Refresh covers** on the selection. Screenshots are not rewritten. |
| Art studio generate/apply returns a blank error or "Unexpected error" | Check the JSON `error` message in the red banner — disk permission/space problems on `IMAGE_SAVE_PATH` or the generated-pack folder are now returned as text instead of a bare 500 page. |
| Password reset email never arrives (SMTP is configured and other mail works) | **Fixed 2026-09-02.** Not an SMTP fault: the reset link was built against `main.reset_password`, an endpoint that does not exist, so `url_for` raised `BuildError` and the send aborted after the token had already been written. Nothing was queued and nothing bounced, which is why SMTP logs looked clean. Invite mail was unaffected — it builds its URL differently. Rebuild/restart; no Reset Themes needed. |
| Reset / invite link in an email points at the wrong host | The origin comes from **Admin → Settings → Site URL** when that is set to a real non-loopback address — set it, and every emailed link is stable. With Site URL unset, Oneirodex falls back to the host the browser actually used, but only when that host is private (loopback, `192.168.x.x`, `.local`, `.lan`, a dotless LAN name). A public hostname is refused unless you list it in `TRUSTED_LINK_HOSTS`, because an unauthenticated caller can put anything in a `Host` header and a poisoned reset link leaks a working token. Published on a real domain? Set `TRUSTED_LINK_HOSTS=games.example.com` (comma separated, port optional) — or just set Site URL. |

Deep ops still use Jinja admin pages behind the React top bar.
