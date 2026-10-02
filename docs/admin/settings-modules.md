# Settings & modules

Admin settings use **grouped rows** at `/admin/settings` (one sheet, section headings, whole row → destination; `?section=` redirects). Chrome is the React admin top bar (`frontend/admin-app`); many forms remain Jinja until migrated. Live React bodies include Dashboard, Libraries/Scans hubs, Themes, Plugins, Announcements, **Support inbox**, and the **Integrations hub** (grouped cards for IGDB · Artwork & secondary metadata · SMTP · OIDC · LiveKit · Community · Acquire/Arr · Ownership · Remote play · Export packs · Support, with deep links into classic forms).

**Integrations inventory API:** `GET /api/admin/integrations/inventory` (admin) returns `{integrations[{id,name,category,status,configured,enabled,admin_href,settings_href,notes}], count, hub_href}` covering IGDB, SteamGridDB, Giant Bomb, HLTB, Meta/Quest, SMTP, OIDC, Support, community chat, LiveKit, Arr connectors, and ownership register links — so the hub is not IGDB-only. The React Integrations page renders a **Provider inventory** grouped by category (with status + notes) under the hub cards. Classic `/admin/integrations` artwork tab anchors (`#steamgriddb`, `#giantbomb`, `#hltb`, `#meta_quest`, `#ownership`, `#livekit`, `#support`, `#indexers`, `#community`, `#email`, `#igdb`) deep-link the same surfaces.

**Browser play engine (BP-0 / BP-1):** `GET`/`PUT /api/browser-player-settings` stores admin defaults under `GlobalSettings.settings.browser_player`. The only selectable default today is `webretro`; `emulatorjs` is reserved until that shell ships. Optional bool `nostalgist_nes_pilot` (default off) points **NES only** at `/static/vendor/nostalgist/play.html` (vendored Nostalgist + WebRetro `nestopia` WASM). Toggle it on **Admin → Emulators**. Browse payloads include `browser_player` / `browser_players_available` / `nostalgist_nes_pilot`. See [browser-play.md](../user/browser-play.md) and [browser-play-engines.md](../dev/browser-play-engines.md).

**Export packs:** Admin → Integrations → **Export packs** (and member Systems secondary section) download ES-DE `gamelist.xml` (`/api/export/esde`) and Pegasus metadata (`/api/export/pegasus`). Paths are portable under library roots — NAS/home mounts are not leaked.

**Server logs:** Admin → Ops → Full log (`/admin/ops?open=full-log`). Legacy `/admin/server_logs` redirects.

**Worker caps (scan/turbo):** New installs default scan threads **1**, turbo threads **4**, turbo batch **100**; runtime hard-caps via `ONEIRODEX_SCAN_THREAD_CAP` / `ONEIRODEX_IMAGE_DOWNLOAD_THREAD_CAP` / `ONEIRODEX_IMAGE_DOWNLOAD_BATCH_CAP` — not Compose `SCAN_*` env vars. See [libraries-and-scans.md](libraries-and-scans.md) · [unraid-deploy.md](../runbooks/unraid-deploy.md#cpu--scan-load-unraid-safe-defaults).

## Scan / match policy (W20-4)

- **Done (uncommitted):** Admin → Settings → **Scan / match policy** (`/admin/scan_match`) — React `ScanMatchSettingsPage` (Jinja SPA shell) + Settings hub card · admin vitest **7/7** claimed · BE `GET`/`PUT` `/api/admin/scan-match/config` live (scoring / dupe / peel wired · pytest claimed **13+21**).
- **Persist:** `GlobalSettings` (`settings.scan_match` JSON + `propose_only_scan`). Unset keys use defaults below.
- **Defaults:** `match_high_threshold` **0.92** · `match_ambiguous_gap` **0.08** · `dupe_title_threshold` **0.85** · `peel_profile` `conservative` · Stage C safe variant toggles **on** (`enable_year_drop_variant` · `enable_pack_peel_variant` · `enable_edition_peel_variant` · `enable_sequel_numeral_variant`).
- **Honesty:** propose-only never auto-imports (even high-confidence). API refuses mega-library / depth-3 family walk keys. `scanThreadCount` stays on Server Settings / worker caps.
- Propose-only also remains on **Server Settings** (`proposeOnlyScan` / `propose_only_scan`) with a link to this page.
- **Post-ship:** Reset Themes **not** required for this API (UI shell already shipped). Details: [libraries-and-scans.md](libraries-and-scans.md#scan--match-policy-w20-4).

## Hub badges

Settings hub shows On/Off (and Storage “Apply off”) as pills beside the module title so you can see state without opening each page. Badge CSS ships in `admin-app.css` — Reset Themes is not required for the hub look; an **admin SPA rebuild** is.

## Feature defaults

Product modules default **on**. Disable during **setup → Features**, under **Admin → Features**, or via `.env` / Compose.

**Member chrome (Server Settings):** `showHelpButton` and `showTrailers` default **on**. They are baked into every member SPA shell on load (`data-show-help` / `data-show-trailers`), including Systems / Chat / Collections — not only Discover and Favorites. A missing JSON key must not hide those More destinations.

**Stays off by default:** `OIDC_ENABLED` (SSO/auth).  
**Safety locks (also off):** `ENABLE_AI_AUTO_APPLY`, `ALLOW_HARDLINK_APPLY`.  
**Patch catalog:** operator YAML/JSON at `PATCH_CATALOG_PATH` — Oneirodex does not scrape romhacking.net or similar sites.

| Env / module | Default | Notes |
|---|---|---|
| Most `ENABLE_*` product flags | on | See `.env.example` |
| `ENABLE_MALWARE_SCAN` | on | ClamAV when reachable + heuristics; blocks/skips on match; Admin → Features |
| `MALWARE_SCAN_BLOCK_ON_HIT` | on | Skip library adds on heuristic warn or ClamAV hit |
| `CLAMAV_*` | host `127.0.0.1:3310` (native) / `clamav:3310` (Compose profile) | Optional `docker compose --profile clamav up -d` |
| `ENABLE_LIVEKIT` | on | Needs `LIVEKIT_*` + compose profile for actual SFU |
| `ENABLE_VR_BROWSE` | on | `/vr` catalogue |
| `ENABLE_PCDOS_BROWSER` | on | Needs vendored dosbox WASM |
| `ENABLE_FREE_GAMES` | on | News free-games poller + API |
| `NOTIFY_APPRISE_URLS` / `NOTIFY_NTFY_URL` | unset | **Notification bus (INSP-6):** Apprise API notify URL(s) and/or an ntfy topic. Every admin alert that passes its `admin_notify_*` flag is also POSTed there (one event per alert); `NOTIFY_SOCIAL_TO_BUS=true` adds the social kinds (friend requests, mentions, DMs, free games), still gated by each member's own in-app preference. Test with `POST /api/admin/notify-bus/test`. Nothing bundled; a dead endpoint is logged once and never breaks the in-app notice. A per-member topic is sized in H-I |
| `ENABLE_GAME_ASSISTS` | on | Assist packs, and since INSP-45 the companion **overlay links**: `PUT /api/games/<uuid>/assists` takes `overlay_links: [{label, url, kind}]` (`map` / `guide` / `clip` / `wiki` / `other`; **http(s) pages only** — a `file:` URL is 422) and every PC title also gets a PCGamingWiki deep link with no pack at all. The stay-open Friends window shows them for the game on screen (`/social-companion?game=<uuid>`, the desktop companion passes the last launched title). Links beside the game — no memory access, no injection, nothing read from a running process |
| `ENABLE_SAVE_PATHS` | on | **Save location** row on PC details pages (INSP-1): one keyless fetch a day of the community save-location manifest, indexed into `static/library/save_paths/` (`SAVE_PATHS_MANIFEST_URL`, `SAVE_PATHS_CACHE_DIR`). Paths keep their `<winAppData>`-style placeholders; the desktop companion expands them for its own PC when asked to *Open save folder*, and refuses when a placeholder is unknown there. Nothing is synced or copied — the multi-device save story is sized in H-I |
| `ENABLE_MOD_CATALOG` | on | *Browse catalogue* in a game's Mods panel: Thunderstore and Modrinth, read-only, keyless. A hit is a name, version, loader and registry page — never a file. Integrations lists both plus CurseForge as *declined* |
| `ENABLE_MOD_CATALOG` | on | *Browse catalogue* in a game's Mods panel: Thunderstore, Modrinth and GameBanana (keyless) plus Nexus Mods behind `NEXUS_API_KEY`, all read-only. A hit is a name, version, loader and registry page — never a file. Integrations lists the four plus CurseForge as *declined* |
| `NEXUS_API_KEY` | unset | Personal key from your Nexus account page; turns on the Nexus tab (trending + latest for the game). Browse only — Nexus's terms forbid third-party download automation, and nothing here downloads |
| `ENABLE_ANTICHEAT_COMPAT` | on | Community anti-cheat compatibility list, one keyless fetch a day into `static/library/anticheat/`; details show the status as *community reports*. `ANTICHEAT_FEED_URL` / `ANTICHEAT_CACHE_PATH` override the source and the file. Integrations lists it as **Anti-cheat reports**, configured once the first fetch has landed |
| `ENABLE_EMAIL_DIGEST` | on | Scheduler on; members still opt in |
| `ENABLE_LOGIN_RATE_LIMIT` | on | In-process login / password-reset rate limit |
| `OIDC_ENABLED` | **off** | Also requires Admin → Integrations toggle |
| `BIOS_IMPORT_SOURCE` | unset | Folder of dumps you already own. Boot copies missing names (never overwrites). Admin → Emulators **Scan collection** uses the same path. [emulator-bios.md](../runbooks/emulator-bios.md) |

## Arr

- Env: `ENABLE_ARR_MODULE`, `ENABLE_ARR_HARDLINK_PIPELINE`, plus optional Prowlarr/Jackett/qBittorrent URLs in `.env`.
- Admin toggle via Arr settings / `PUT /api/arr/module` (env **or** DB enable).
- On by default; disable under Features if you are not using Acquire.
- **Native indexers:** Admin → Arr registry stores Torznab/Newznab entries in `GlobalSettings.arr_settings.indexers` (add one, JSON/CSV bulk, curated presets with empty API keys). Search merges enabled native endpoints **and** configured Prowlarr **and** Jackett.
- **Admin UI:** Arr page shows indexer table (ready/enabled/source, toggle, delete), add-one form, bulk JSON/CSV import, preset multi-select + Enable selected, hub URL fields, and `indexer_warnings` from status/search.
- APIs: `GET/POST /api/arr/indexers`, `POST /api/arr/indexers/bulk`, `POST /api/arr/indexers/enable-presets`, `PUT|PATCH|DELETE /api/arr/indexers/<id>`.
- Native indexer URLs use outbound SSRF checks (no LAN); hub URLs still respect `ALLOW_PRIVATE_LAN_URLS`. Hub URLs (Prowlarr, Jackett, qBittorrent, Transmission, SABnzbd, NZBGet) are re-checked every time they are called, and every redirect hop is re-checked too, not only when you save them. Connector failures are logged by exception type and host/path only — never the `?apikey=` query string — and the Acquire / Arr download and search routes answer with fixed wording ("Could not reach the download service", "The download service did not respond in time", "…returned an error (401)"), never the exception text, because that text holds the request URL (SABnzbd and AllDebrid send the key in the query string) and the address the host name resolved to; the details are in the server log. Outbound requests dial the address the host name resolved to (unless a proxy applies, see [Outbound proxies and URL forms](#outbound-proxies-and-url-forms)), so a host name this server cannot resolve is refused when it is used (`URL host could not be resolved`) even though it can still be saved while DNS is down; use an IP address or fix DNS/`extra_hosts`. A connector URL that carries credentials (`http://user:pw@proxy.lan`) keeps them across same-origin redirects, and `http://host` redirecting to `https://host` on the default ports keeps its credentials and API-key header the way `requests` does; any other origin change drops them, and the log says which headers were dropped (names only).
- Preset pack: `oneirodex/data/indexer_presets.json` (no secrets; admin-only display names).
- **Remote path mapping (`ARR_REMOTE_PATH_MAP`)** — set this whenever your download client runs in a **different container** than Oneirodex, which is the normal Unraid/Compose layout. qBittorrent reports paths from *its* mounts (`/downloads/…`), Oneirodex sees the same bytes somewhere else (`/storage/downloads/…`), and without a mapping the hardlink pipeline stats a path that does not exist here. The preview then says *"no source file found"* — true, but baffling when the file is plainly on disk.
  - Format: `remote=>local` pairs joined by `|`. `=>` because Windows paths contain colons; `|` because paths can contain commas.
  - Example: `ARR_REMOTE_PATH_MAP=/downloads=>/storage/downloads|/data/torrents=>/mnt/user/torrents`
  - Longest remote prefix wins, so a specific mapping beats a general one. A prefix only matches at a path separator, so `/downloads` never matches `/downloads-old`.
  - Leave empty when client and app share a filesystem view — unmapped paths pass through untouched.
  - When no mapping is set and a lookup fails, the preview reason now names the path it tried and points at this setting instead of just saying "not found".
- **Quality / release profiles (P1-12):** `GlobalSettings.quality_profiles` (multi-profile JSON). Admin → **Quality profiles** SPA at `/admin/quality_profiles` (`QualityProfilesPage`: list · set active · new · delete · edit · score probe; Jinja is an SPA shell). APIs: `GET/POST /api/quality-profiles`, `PUT /api/quality-profiles/active`, `GET/PUT/DELETE /api/quality-profiles/<id>`. Active profile scores Arr search and extends scan name-clean with blocked/excluded terms.

## AI

- Env: `ENABLE_AI_ASSIST`, `ENABLE_AI_AUTO_APPLY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.
- Admin AI page: enable + Ollama URL/model (`PUT /api/ai/config`) and Test.
- Ollama-only by default; never required for core library use.

## Storage / hardlinks

- `ENABLE_HARDLINK_HELPERS` and `ALLOW_HARDLINK_APPLY` are **env-only** safety gates (no DB toggle). `ALLOW_HARDLINK_APPLY` stays **off** by product default.
- Admin page: **Settings → Storage** (`/admin/storage`) — React `StoragePage` (Jinja emptied to SPA shell).
- Status API: `GET /api/storage/status` — `helpers_enabled` · `allow_apply` · `games_path` · `games_exists` / `games_readable` / `games_writable` · `degrade_reason` (RO / apply-off honesty).
- Preview / apply: `POST /api/storage/hardlink/preview` · `POST /api/storage/hardlink/apply` (apply gated by helpers **and** `ALLOW_HARDLINK_APPLY`). Preview surfaces readable reasons, including **destination parent not writable (read-only mount?)**.
- Hub / page banners explain why Apply is disabled when helpers/apply are off or the games mount is RO.

## LiveKit voice

- Env: `ENABLE_LIVEKIT`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
- Compose: `docker compose --profile livekit up -d` — [livekit-unraid.md](../runbooks/livekit-unraid.md).
- Plugin registry: `rtc.livekit` (configured when env is complete).

## Remote play (Moonlight / BYO host)

- Env: `ENABLE_REMOTE_PLAY` (**off** by default), optional `SUNSHINE_BASE_URL` / `WOLF_BASE_URL`, hint vars — see `.env.example`.
- Admin: **Settings → Remote play** (`/admin/remote_play`) or `PUT /api/admin/remote-play/config`.
- Members: `GET /api/remote-play/status`; game details **Play via Moonlight** copies host + hints.
- **No Wolf/GOW in Oneirodex image** — operator runs Sunshine/Wolf on a GPU host; LAN URLs need `ALLOW_PRIVATE_LAN_URLS=true`.
- Plugin registry: `remote_play.moonlight`.

## Loading icons (admin lock / rotate)

- DB: `GlobalSettings.loading_icon_mode` (`rotate` \| `lock`, default **rotate**), `loading_icon_id` (catalogue id or null).
- Public bootstrap: `GET /api/loading-icon` (no admin auth — member/admin loading UIs).
- Admin: `GET`/`PUT /api/admin/loading-icon/config` — lock requires a catalogue id; rotate clears id.
- Catalogue ids: `ring`, `orbit`, `pulse`, `blocks`, `scan`, `arcade` — visuals are SPA/theme-owned.

## Malware scan

- Env: `ENABLE_MALWARE_SCAN`, `MALWARE_SCAN_BLOCK_ON_HIT`, `CLAMAV_HOST`, `CLAMAV_PORT`, `CLAMAV_SOCKET`.
- Compose: `docker compose --profile clamav up -d` — [docker-compose-deploy.md](../runbooks/docker-compose-deploy.md).
- Library scans **skip/block** adds on heuristic filename match or ClamAV hit when `MALWARE_SCAN_BLOCK_ON_HIT=true` (default).
- Admin status: `GET /api/admin/malware-scan/status` or Admin → Features.

## Challenge solver (BYO sidecar)

- Env: `ENABLE_CHALLENGE_SOLVER` (**off** by default), `CHALLENGE_SOLVER_URL`, `CHALLENGE_SOLVER_PROVIDER`, `CHALLENGE_SOLVER_TIMEOUT_MS`, `CHALLENGE_SOLVER_MAX_TIER` (default **5**; admin may raise).
- Optional token CAPTCHA API: `CHALLENGE_TOKEN_API_URL`, `CHALLENGE_TOKEN_API_KEY` when `provider=token_api`.
- Compose: `docker compose --profile challenge up -d` (Ops) — FlareSolverr-compatible TRAWL sidecar on LAN only.
- Admin → Features: enable, solver URL, provider, max tier, **Test solver**; status `GET /api/admin/challenge-solver/status?probe=1`.
- Opt-in only — not bulk-enabled with OIDC/AI apply locks. Solver URL validated via `validate_connector_http_url` + `ALLOW_PRIVATE_LAN_URLS`.
- Acquire (*arr search / debrid HTTP) retries **once** through the solver when a challenge page is detected and the module is on.

## Ambient lighting (Hyperion.ng / Home Assistant)

- Env: `ENABLE_AMBIENT_LIGHTING` (**off** by default), `LIGHTING_PROVIDER` (`off` \| `hyperion` \| `homeassistant`).
- Hyperion: `HYPERION_URL`, optional `HYPERION_TOKEN`, `HYPERION_PRIORITY` (default 50), `AMBIENT_ACCENT_COLOR`.
- Home Assistant: `HA_URL`, `HA_TOKEN`, `HA_LIGHT_ENTITIES`, optional `HA_PLAY_SCENE` / `HA_STOP_SCENE`.
- Play session start/stop hooks fire-and-forget — never block play launch. Child accounts never trigger lighting.
- Admin → Features: enable, provider, connector fields, **Test**; status `GET /api/admin/ambient-lighting/status?probe=1`.
- URLs validated via `validate_connector_http_url` + `ALLOW_PRIVATE_LAN_URLS`.

## Support → GitHub

- Env: `SUPPORT_GITHUB_TOKEN`, `SUPPORT_GITHUB_REPO` — [support-inbox.md](support-inbox.md).
- No Discord webhooks; library events notify admins in-app (`admin_notify_*`).

## Art studio (cover placeholders)

- **Admin → Settings → Art studio** or `/admin/art_studio` (React; admin/ops only). Tabs: **Studio** · **Backup & stock** (`#stock`) · **System marks** (`#marks`) · **Pick & queue** (`#images`).
- Local Pillow renderer — aurora tokens (`--gt-*`), no paid cloud AI. Preview/generate use **artistic** compositions by default (`artistic: true` on `POST /admin/api/art-studio/preview`; optional `artistic: false` for legacy flat A/B). Idle **title scale is 1.3×** (floor 0.85×); the slider always posts `title_scale`.
- **Title-first studio:** large live preview stage; typing a title debounces preview. System / platform selector + preview size toggles (200×300 · 400×600 · 960×540 wide). Soft-fails preview lag with toast.
- **Actions:** Preview · Generate pack · Download ZIP · Set as fallback · Apply to game UUID.
- **Backup & stock** (`#stock`): thumbnail grid of platform packs + stock motifs from `GET /admin/api/art-studio/stock`; ungenerated packs auto-call `POST …/stock/generate` on apply. Select → preview → **Use as library default** / **Set fallback** via `POST /admin/api/art-studio/apply` (`mode=fallback|library`). Soft empty state if catalog 404. Library create/edit Jinja **Choose image** links here.
- **Library default covers** panel shows current `default_cover.jpg` / `default_library.jpg` with **Regenerate defaults** CTA.
- **Batch placeholders** (collapsed) for no-cover titles via `POST /admin/api/art-studio/batch-generate` (alias: `apply-batch`) first, then `POST /admin/api/covers/batch/apply` (`generate_only`) fallback.
- **Auto-pick (ImagesPage):** `POST /admin/api/covers/batch/apply` with `policy=sgdb_then_igdb_then_generate` (library / platform / service filters). Mass search: `POST /admin/api/covers/batch/search`.
- **Single-title picker:** `POST /admin/api/covers/search` + `POST /admin/api/covers/apply`. Identify chips from `GET /api/search_metadata/sources` (Meta Quest / Epic / itch / Giant Bomb / MobyGames / TheGamesDB) search via `GET /api/search_metadata?source=`. Optional `MOBYGAMES_API_KEY` / `THEGAMESDB_API_KEY` — empty results when unset.
- Queue rows show `failure_reason` (and `last_error` fallback); list responses surface `image_save_path.error` when the images volume is not writable.
- API: `POST /admin/api/art-studio/preview|generate|apply|apply-batch`, `GET /admin/api/art-studio/download/<pack_id>`, `POST /admin/api/art-studio/batch-generate`, `GET /admin/api/art-studio/stock`, `POST /admin/api/art-studio/stock/generate`, `GET /admin/api/art-studio/system-marks`, `GET /admin/api/art-studio/system-marks/lab`, `POST /admin/api/art-studio/system-marks/generate`; covers mass tools under `/admin/api/covers/*`.
- **Systems hub marks** (AI): Art Studio tab **System marks** (`#marks`) lists per-theme progress and can generate missing / force-redo via `GET/POST /admin/api/art-studio/system-marks`. The **Lab** on that tab generates **one** theme×platform pair (editable prompt, preview, attempt log) via `GET …/system-marks/lab` and `POST …/generate` with `platforms` + optional `prompt`. Square WebPs land under `static/library/system-marks/<theme>/<platform>.webp`. Requires `ENABLE_AI_ARTWORK` + `AI_ARTWORK_URL`. CLI: `python scripts/generate_system_marks.py --all`. Full batch regen is ops-gated (quality hold).
- **System templates:** generated covers use per-system palette + glyph (NES/SNES/PS1/Switch/PC/…) so 200×300 tiles stay readable — not a generic subtitle-only placeholder.
- **Meta Quest Store:** identify `GET /api/search_metadata?source=meta_quest|meta|quest` · ownership CSV `POST /api/ownership/meta_quest/csv` · `META_QUEST_API_MODE` / `META_QUEST_UNOFFICIAL_GRAPHQL` (off by default) (local strategy notes).
- **Store connections (admin):** `/admin/ownership` (Integrations → Ownership registers) lists each member's store links with one state per store (Linked, Syncing, Partly synced, Reconnect needed, Sync failed, …), the last sync's redacted reason ("Admin can fix" marks operator-side causes such as a refused household token or a missing server key), record counts and which sign-in a sync uses (member / household / **unknown** — a GOG, Amazon or Xbox sign-in saved before LIB-04 on a server that has a household token for that store; older versions stored the household token on member accounts unmarked, so ask those members to reconnect after upgrading). It never shows tokens, store account IDs or title lists. **Retry sync** runs a member's sync with their own saved sign-in (not offered when only the member can fix it); **Stop sync** is offered only for GOG / Epic / Amazon, which stop between pages. Household configuration appears as presence flags. API: `GET /api/admin/ownership/connections`, `POST …/<user_id>/<store>/sync|cancel`.
- **Ownership register:** members link Steam / GOG / Epic / Amazon under **More → Ownership**. Steam Web API, unofficial GOG Galaxy refresh token, unofficial Epic device auth, unofficial Amazon Nile/Heroic token — IDs and names only, never a download. Household env: `STEAM_WEB_API_KEY`, `GOG_REFRESH_TOKEN`, `EPIC_DEVICE_AUTH`, `AMAZON_REFRESH_TOKEN` / `AMAZON_DEVICE_SERIAL` / `AMAZON_NILE_JSON`. **Xbox and PlayStation (INSP-42) are register-only, unofficial and opt-in:** CSV import always works; live sync runs only when `ENABLE_UNOFFICIAL_STORE_SYNC` names the store (`xbox,psn` or `all`; unset = off, decision G5) *and* the optional client is installed (`requirements-optional.txt`: `xbox-webapi`, `psnawp`) *and* a member saved a token on the Ownership page (`xbox-webapi` tokens JSON; PSN `npsso`). Without any of the three the sync button says which is missing in one sentence; the Integrations rows and plugins `store.xbox` / `store.psn` read *disabled* until opted in, *available* until the client exists. Household fallbacks `XBOX_TOKENS_JSON`, `XBOX_CLIENT_ID` / `XBOX_CLIENT_SECRET`, `PSN_NPSSO`. IDs and names only; a 401 fails closed; nothing is ever downloaded. Nintendo stays CSV.
- Disk failures (read-only `IMAGE_SAVE_PATH` / generated-pack folder, out of space) surface as a JSON `error` and show in the red alert banner instead of a bare 500 — check the message for the exact path/permission problem. If applying a pack to a game fails partway (DB error after the file was written), the orphaned file is cleaned up automatically.
- Artwork picker: [steamgriddb-artwork.md](../runbooks/steamgriddb-artwork.md) · [libraries-and-scans.md](libraries-and-scans.md#image-queue).

## Generated cover art

Optional, **off by default**, and self-hosted only. This is the one feature that
talks to an endpoint outside the process, so it stays opt-in.

| Flag | Effect |
|---|---|
| `ENABLE_AI_ARTWORK` | Master switch — default **false** |
| `AI_ARTWORK_URL` | Your endpoint, e.g. `http://sdnext:7860`. No default; generation refuses without it |
| `AI_ARTWORK_ENGINE` | `a1111` (default) — the A1111 REST API, which **AUTOMATIC1111**, **SD.Next** and **Forge** all implement |

- Calls `POST /sdapi/v1/txt2img` on your endpoint. Nothing leaves your network;
  there is no hosted provider and no API key to buy.
- `AI_ARTWORK_ENGINE=comfyui` is recognised but **not implemented** — it raises
  a clear error naming the missing workflow rather than silently producing
  nothing. Use `a1111` for now.
- Generated rows are marked `is_generated` with `generated_by`. Regenerating
  replaces only the previous *generated* image, so hand-picked or scraped art is
  never clobbered.
- Routes: `POST /admin/api/artwork/generate` (one game) ·
  `POST /admin/api/artwork/generate/batch` (fill missing covers).
- Compose ships an SD.Next sidecar under the `artwork` profile
  (`docker compose --profile artwork up -d`) — see `docker-compose.yml`. That
  service overrides the image's CMD: `saladtechnologies/sdnext:latest` still
  passes `--skip-tests`, which its pinned SD.Next checkout does not define, so
  the stock command dies at argparse with *unrecognized arguments* before the
  server ever binds. Its volumes mount at `/webui/data/models` and
  `/webui/outputs` — the image has no `/app`. Its healthcheck probes with
  `wget`, because the image ships no `curl`: a `curl` probe fails with
  "executable file not found" and the container sits unhealthy forever while
  serving fine.
- **GPU is opt-in and never assumed.** The sidecar runs on CPU by default —
  extremely slow, but it runs. `docker-compose.yml` requests no GPU at all,
  because an NVIDIA reservation on a host without a loaded driver fails
  container create (`nvml error: driver not loaded`) and takes the whole stack
  update with it. If the *Docker host* has the driver and the NVIDIA Container
  Toolkit, opt in with `COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml`.
- **GPU on a different machine?** Do not start the profile. On a Windows GPU
  box use [`docker-compose.artwork-local.yml`](../../docker-compose.artwork-local.yml)
  ([artwork-gpu-workstation.md](../runbooks/artwork-gpu-workstation.md)) and set
  `AI_ARTWORK_URL=http://<host>:7860` — the backend only makes an HTTP call.
  Making that turnkey (pairing, health, queueing) is backlog **GPU-N**.

Prefer to supply your own art instead? See
[theme-fonts-and-images.md](theme-fonts-and-images.md#batch-artwork-upload).

## Scan freshness checks

| Flag | Effect |
|---|---|
| `SCAN_CHECK_FRESHNESS` | Check version / updates / DLC after a library scan — default **false** |
| `SCAN_FRESHNESS_LIMIT` | Titles checked per run; default **50** |

Off by default deliberately: each check is outbound store HTTP traffic, so a
routine scan must not start doing it without being asked. The cap keeps a large
first scan from turning into thousands of requests.

## Theme fonts

| Flag | Effect |
|---|---|
| `FONT_PATH` | Where uploaded/dropped-in fonts live. Empty = `static/library/fonts` |
| `FONT_MAX_BYTES` | Per-file upload cap; default `8388608` (8MB) |

Font *files* are operator-supplied — the registry ships the faces, not the
binaries. Full guide: [theme-fonts-and-images.md](theme-fonts-and-images.md).

## Other env toggles

| Flag | Effect |
|---|---|
| `ENABLE_VR_BROWSE` | Member VR catalogue |
| `DAT_HASH_INNER_ARCHIVE` | Open zip/7z/rar and hash the inner dump when the outer archive hash misses (default on) |
| `ENABLE_FREE_GAMES` | News free-games poller + API (default on) |
| `ENABLE_MOD_CATALOG` | Read-only mod registry browse (Thunderstore, Modrinth, GameBanana, Nexus) in the Mods panel (default on) |
| `NEXUS_API_KEY` | Personal Nexus Mods key; browse only (unset = the Nexus tab says it needs a key) |
| `ENABLE_ANTICHEAT_COMPAT` | Community anti-cheat list, daily fetch + details fact (default on) |
| `ANTICHEAT_FEED_URL` | Where the list is fetched from (default: the public games.json) |
| `ANTICHEAT_CACHE_PATH` | Where the fetched file lives (default `static/library/anticheat/games.json`) |
| `FREE_GAMES_POLL_HOURS` | Free-games refresh interval (default 3) |
| `ENABLE_EMAIL_DIGEST` | Batched digest scheduler (default on; members still opt in) |
| `EMAIL_DIGEST_INTERVAL_HOURS` | Digest poll interval (default 24; clamp 1–168) |
| `ENABLE_PCDOS_BROWSER` | Allow PC DOS browser play when dosbox WASM is vendored (default on; still needs WASM on disk) |
| `ENABLE_LOGIN_RATE_LIMIT` | In-process login / password-reset rate limit (default on) |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | Max failures per window (default 10) |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | Window seconds (default 300) |
| `OIDC_ENABLED` + Admin Integrations | SSO (also see OIDC runbooks) |
| Custom chat emoji | Admin → Integrations → Community → **Manage custom chat emoji** (max 20) |
| `ALLOW_PRIVATE_LAN_URLS` | Allow admin *arr/Ollama/ambient-lighting/game-server-health **connector** URLs on RFC1918 and the Tailscale/CGNAT range `100.64.0.0/10` (user/indexer fetches stay blocked; cloud metadata endpoints — `169.254.169.254`, `100.100.100.200` (Alibaba), `168.63.129.16` (Azure wire server), `192.0.0.192` (Oracle), `fd00:ec2::254` and `fd00:ec2::23` (AWS IPv6) — are never reachable, by address or by a name that resolves to one, and not when the IPv4 address is wrapped in IPv6: IPv4-mapped, NAT64 `64:ff9b::/96` and `64:ff9b:1::/48`, 6to4, Teredo, IPv4-compatible and SIIT forms are unwrapped and checked too). The check runs on every request and every redirect hop. An Ollama URL from `OLLAMA_BASE_URL` (or the built-in `127.0.0.1` default) is the operator's own choice and stays reachable with the flag off; one saved in Admin is held to the flag |
| `CHEAT_STORAGE_MAX_BYTES` | Total `.cht` storage across every game (default 0 = 256 MB). Each game is also capped at 200 files of 1 MB; a new file past either bound is refused with 409 `conflict`, and the count-then-write check holds a lock file in the cheats folder, so simultaneous uploads cannot exceed it even from several worker processes. A value that is not a whole number of bytes (`256MB`) is ignored with a warning in the log, as it is for `EMULATOR_BIOS_MAX_BYTES` |
| `OIDC_LOCK_ROLES` | Don’t overwrite roles on every SSO login |
| `ENABLE_CHALLENGE_SOLVER` | **off** — BYO FlareSolverr/TRAWL sidecar for challenged acquire fetches |
| `CHALLENGE_SOLVER_MAX_TIER` | Default **5** (admin may increase) |

### Outbound proxies and URL forms

Server-side fetches (connectors, indexers, metadata and artwork providers, notification webhooks) follow the standard proxy variables the way `requests` does: `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and `NO_PROXY` (host names, `.suffix` entries, IP addresses, CIDR ranges, or `*`).

- **No proxy applies** (variable unset, or the host matches `NO_PROXY`): Oneirodex connects to the address it just checked and keeps the host name on `Host` / TLS, so a name that changes its answer between the check and the connection cannot steer the call (DNS-rebinding protection).
- **A proxy applies:** the host name is checked as usual (loopback, private, link-local and cloud-metadata addresses stay refused), then the *name* goes to the proxy, which resolves it and connects. HTTPS uses `CONNECT host:443` with normal SNI, so name-based proxy rules and virtual hosts work. Oneirodex cannot pin a connection the proxy makes, so **DNS-rebinding protection then rests with the proxy**, on every redirect hop too. A name this server cannot resolve is passed on for the proxy to decide; without a proxy it is refused (`URL host could not be resolved`).
- The proxy decision uses the **host name in the URL**, not the address it resolves to. A LAN connector configured by name (`http://nas.lan:8989`) needs `nas.lan` (or `.lan`) in `NO_PROXY`, otherwise its API key goes to the proxy; one configured by IP address matches `NO_PROXY` entries for that IP or its CIDR range.
- **`Invalid URL`:** a URL is refused when Python and `requests` would read a different host out of it, or when its host part holds characters RFC 3986 does not allow (a backslash, a space, `^`, `|`, braces) or an impossible port. `http://127.0.0.1\@example.com/` is `example.com` to one parser and `127.0.0.1` to the other. Percent-encode special characters in credentials embedded in a connector URL (`@` becomes `%40`), or use the separate username/password fields.

## Mods & household game servers

- **`ENABLE_MOD_TRACKING`** (default on) — per-game mod registry at `/api/games/<uuid>/mods` (librarian/admin CRUD; members read; child read-only). Summary: `GET /api/mods/summary`. Each row carries `id`, `name`, `version`, `source_url`, `notes`, `enabled`, `load_order` and — since INSP-36 — **`loader`**: the mod loader it needs (`bepinex`, `melonloader`, `smapi`, `lovely`, `forge`, `fabric`, `quilt`, `neoforge`, `manual`, `none` are the suggested words, any slug is kept). The pack has a `default_loader` rows inherit (`PATCH /api/games/<uuid>/mods/pack`, or `default_loader` on the bulk `PUT`). Bodies are validated (`422` on unknown fields). The companion only *reads* the loader — its apply result says *Needs BepInEx installed — not managed here*; nothing installs a loader. The details page has a **Mods** panel: everyone sees the tracked list; a librarian gets the default loader, an add form and **Browse catalogue** — `GET /api/games/<uuid>/mods/catalog?source=thunderstore|modrinth|gamebanana|nexus&q=` (librarian). The answer says `status: ok` with hits, or `status: unavailable` with `hits: null` and a note when the registry had no data — never a silent empty list. *Add to list* files the hit through the ordinary `POST` with the registry page as `source_url`. **Profiles (INSP-37):** a pack can hold up to 32 named sets of mod ids (`GET|POST /api/games/<uuid>/mods/profiles`, `DELETE …/profiles/<id>`); `POST …/profiles/<id>/activate` is the one-click enable set — the profile's rows on, every other row off, `active_profile` remembered — which is exactly what the companion's next *Apply mods* stages. `GET …/profiles/<id>/export` returns an `od-mod:` code (base64url JSON: name, default loader, and each mod's name / version / loader / source page — never a file); `POST …/profiles/import {code}` creates the profile on *this* game from what it already tracks (matched by id, then by `source_url`) and returns the rest as `missing` — nothing is invented. Members can read and copy codes; writes are librarian. **Compat and freshness (INSP-38/39):** a row may list `requires` (ids of rows that must be staged first; unknown ids are pruned on read) and `latest_seen_version`. `GET …/mods` also returns `loader_conflicts` — enabled rows whose `loader` disagrees with the pack `default_loader` (both set, neither `manual`/`none`); the panel says so and the **companion refuses to apply** that set until the rows or the default agree. The catalogue drawer marks hits the pack already tracks (`tracked_id`, by source URL) and, when the registry's version differs, `update_available`; *Mark updated to vX* is an ordinary row write. Thunderstore hits carry `dependencies` (package names) and *Add with N needed* files them first, then the hit pointing at them. The companion refuses an empty or short download (`Content-Length` mismatch) before writing it, and re-stages from `source_url` on the next apply — that is the integrity repair.
- **Game servers** — admin CRUD at `/api/game-servers`; members/children read join info only. Ops summary `services.game_servers` includes TCP/HTTP health chips; per-server status: `GET /api/game-servers/<uuid>/status`.

Related: [libraries-and-scans.md](libraries-and-scans.md) · [docker-compose-deploy.md](../runbooks/docker-compose-deploy.md) · [oidc-sso.md](../runbooks/oidc-sso.md) · [troubleshooting.md](troubleshooting.md)

## Personal API tokens (companion / thin)

- **API:** `GET/POST /api/tokens`, `DELETE /api/tokens/{id}` — any logged-in member.
- **Presets:** `POST` body `"preset": "companion"` (`read:library` + `write:download`) or `"preset": "thin"` (`read:library` + `read:social` + `write:presence`; **no** download). List response includes `scope_presets`.
- **Thin protocol:** heartbeat accepts `device_kind` (`companion` | `thin` | `browser`); `GET /api/client/capabilities` advertises allows/denies. Install/update command queue delivers only to `companion` + download/lifecycle scopes.
- **UI:** member SPA **Account → API tokens** (`/tokens`) — create with companion/thin presets, copy one-time secret, revoke. API / `@oneirodex/api-client` / OpenAPI still work. See [desktop-companion.md](../user/desktop-companion.md) · [thin-client.md](../user/thin-client.md).
