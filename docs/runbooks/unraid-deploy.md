# Unraid deploy — Oneirodex

> **Doc status:** Active

## Deploy gates (operator checklist)

Do these **before** and **after** every Unraid `git pull` / image rebuild. Agents cannot free host disk or run a live NAS rescan without an explicit human ship.

### Before pull / build

| Gate | Operator step | Why |
|---|---|---|
| **Free host disk** | Unraid Main / Shares: free space until the array is **well under ~99% full** (target: tens of GB free on the cache/array used by Docker) | Pull + `docker compose build` fail or evict other containers when the host is full |
| **Workspace path** | Edit the live checkout: Unraid `/mnt/user/example-share/_projects/Oneirodex`, Windows `Z:\_projects\Oneirodex` | This tree **is** the Compose Manager stack. `/mnt/user/isos/oneirodex/` is retired. Games stay on `/mnt/user/example-share/_software/_games` (scan root), not the repo |
| **Disk hygiene (dev caches)** | Optional: wipe regenerable local caches only — [workspace-disk-hygiene.md](workspace-disk-hygiene.md) | Shrinks build context; does **not** free Unraid array capacity by itself |

### After deploy (every code image)

1. Confirm readiness: `curl -f http://<unraid-ip>:5006/awake`
2. Admin → Themes → **Reset Default Themes** (library volume theme CSS/JS lag the image) — [themes-reset.md](../admin/themes-reset.md)
3. Confirm the image rebuilt **`frontend/member-app` dist** (`member-app.css` / `.js` in View Source). Reset Themes alone does **not** refresh the SPA bundle
4. Reload the browser normally; smoke Discover/Library + Admin Ops glance
5. **Deep discounts:** Discover → Elsewhere (or the Deep discounts shelf). CheapShark is public HTTPS (`www.cheapshark.com`); the container must be allowed outbound. Init seeds `store_deals` if missing. An empty shelf is honest when the pull succeeded and nothing is ≥75% off — not a missing seed. A failed pull (generic User-Agent 400, timeout) keeps the last snapshot instead of hiding the shelf. No Reset Themes needed for this shelf.

> Step 4 used to read "hard-refresh". It no longer needs to: theme URLs are versioned by mtime+size
> and `/static/library/themes/` serves `no-cache`, so a reset is visible on an ordinary reload. If a
> hard refresh still changes what you see, that is a defect to report rather than a step to keep —
> [themes-reset.md](../admin/themes-reset.md).

### After Stage A0–A8 lands on origin

Only when the human has **shipped** the name-resolution code and the image is running that build:

1. Confirm Library A (**PCWIN**, letter-bucket `…/_pc` root) has **`scan_depth=2`**
2. Run a **propose-only** scan first; review Unmatched / proposals
3. Then a **full** rescan at `scan_depth=2` — do **not** start overlapping full scans on the same tree

Exact steps: [libraries-and-scans.md — After A0–A14](../admin/libraries-and-scans.md#after-a0a14-ship--library-a-pcwin-rescan).

## Prerequisites

- Unraid 6.12+ with Docker / Compose Manager
- A **games** share (read-only mount into the container — scan root only)
- A writable **library** share for covers, themes, uploads (separate from games)
- Postgres (compose `db` service or external)
- Host disk **not** at ~99% before pull/build (see [Deploy gates](#deploy-gates-operator-checklist))

## Required environment

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | **Yes** | Must not be the example placeholder. Generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DATABASE_URL` | Yes (Compose builds it) | Host is always `db` — do not use `@localhost` |
| `DATA_FOLDER_GAMES` | Yes | **Host** games path in `.env` (Compose mounts → `/storage:ro`). Container env hard-sets `/storage`. |
| `LIBRARY_HOST_PATH` | Yes | **Host** appdata library path → `/app/oneirodex/static/library` RW |
| `POSTGRES_PASSWORD` | If using bundled db | **Set a strong value** (`python -c "import secrets; print(secrets.token_hex(24))"`). Compose still falls back to `postgres` when it is unset so old stacks start, but that is a known superuser password. Read only when the `db_data` volume is first created — rotate an existing one per [docker-compose-deploy.md](docker-compose-deploy.md#rotating-the-password-on-an-existing-database). |
| `POSTGRES_HOST_BIND` / `POSTGRES_HOST_PORT` | No | Host publish of Postgres. Defaults to `127.0.0.1:5432` (this Unraid box only). Set `POSTGRES_HOST_BIND=<Unraid LAN IP>` to reach it from another machine; see [Postgres exposure](docker-compose-deploy.md#postgres-exposure-and-password). |
| other `POSTGRES_*` | If using bundled db | Match Compose `db` service |

Template: [`.env.unraid.example`](../../.env.unraid.example) (also `.env.nas.example` / `.env.docker.example`).

## Volume sectioning

Do **not** put covers, themes, or uploads on the games mount.

| Role | Host env | Container mount | Mode | Purpose |
|---|---|---|---|---|
| **Games** | `DATA_FOLDER_GAMES` | `/storage` | **ro** | Library scan root only — never uploads |
| **Library / uploads** | `LIBRARY_HOST_PATH` | `/app/oneirodex/static/library` | **rw** | Covers, themes, user uploads (`UPLOAD_FOLDER`) |
| **Optional BIOS / firmware** | `EMULATOR_BIOS_HOST_PATH` (uncomment bind in compose) | `/app/oneirodex/static/library/bios` | **rw** | Private household firmware folder under **appdata** — not the games share. See [Local private BIOS mount](#local-private-bios-mount-vs-public-upload) |
| Postgres | Compose volume `db_data` | `/var/lib/postgresql/data/pgdata` | rw | DB |
| Optional WebRetro cores | `WEBRETRO_CORES_HOST_PATH` (uncomment in compose) | `/app/oneirodex/static/vendor/webretro/cores` | rw | Must include shipped cores — [webretro-cores.md](webretro-cores.md) |

Unraid path examples (edit to match your shares):

```bash
DATA_FOLDER_GAMES=/mnt/user/games
LIBRARY_HOST_PATH=/mnt/user/appdata/oneirodex/library
# Optional — after creating the host dir and uncommenting the compose bios bind:
# EMULATOR_BIOS_HOST_PATH=/mnt/user/appdata/oneirodex/bios
# EMULATOR_BIOS_PATH=/app/oneirodex/static/library/bios
```

App libraries in Admin should point at paths under `/storage/...` (inside the container).

## HTTPS, SMTP, passkeys (HellfireNAS)

The app container publishes **HTTP `:5006` only**. There is no Swag / NPM / Caddy sidecar on this host. Unraid’s own TLS bundle (`/boot/config/ssl/certs/HellfireNAS_unraid_bundle.pem`) is for the **management GUI**, not Oneirodex.

To put the app on HTTPS:

1. Pick a hostname (LAN DNS or public) and terminate TLS on a reverse proxy (npm / Swag / Caddy / Unraid extra nginx).
2. Proxy to `http://127.0.0.1:5006` with `X-Forwarded-Proto: https` — [oidc-sso.md § reverse proxy](oidc-sso.md#6-reverse-proxy-and-https).
3. Set `TRUSTED_PROXIES=1`, `SESSION_COOKIE_SECURE=true`, and Admin **Site URL** to the `https://…` base.

4. Once TLS is up, members can **install the app** (Preferences → Install this library) on laptops, Chromebooks, tablets and headsets — the install path needs a secure origin, so on plain HTTP the row never appears. Installed seats heartbeat as `browser`, not `thin`; they hold no install ACLs. See [thin-client.md § No binary](../user/thin-client.md#no-binary-install-the-web-app-instead-tc-2b).

**SMTP** is stored in Admin → Integrations → SMTP (`GlobalSettings.smtp_*`), not `.env`. Tuta: `smtp.tuta.com` port **587** STARTTLS. Do not paste the password into git or chat. **Passkeys** for Unraid’s GUI are a host setting; the Oneirodex login page has no WebAuthn yet.

### Local private BIOS mount vs public upload

| Surface | How firmware reaches Play | Rule |
|---|---|---|
| **GitHub / public image** | Operator **uploads** via Admin → emulator BIOS (`POST /api/emulator-bios`) | **Never** ship BIOS binaries in git, CI artifacts, or public Docker layers as content |
| **Local / household Unraid** | Optional bind of a **private** host folder you already own into the container | Mount under **appdata** (RW), never onto `/storage:ro` games |

**Local mount steps (optional)**

1. On the host: `mkdir -p /mnt/user/appdata/oneirodex/bios`
2. Place legally obtained firmware files you already own (names only — see [browser-play.md](../user/browser-play.md#bios--firmware-filenames-only)). No download links; Oneirodex does not distribute BIOS packs.
3. In `.env`: set `EMULATOR_BIOS_HOST_PATH=/mnt/user/appdata/oneirodex/bios` and keep `EMULATOR_BIOS_PATH=/app/oneirodex/static/library/bios` (Compose default).
4. Uncomment the bios volume line in `docker-compose.yml`, then recreate the app container.
5. Confirm Admin → emulator BIOS lists the files. Remaining names can be uploaded one at a time, or **Scan collection** / **Install matching firmware** if the dumps live in a folder the container can see (`BIOS_IMPORT_SOURCE` or a library root).

Without the optional bind, Admin upload still writes under the library volume at `…/library/bios` on the host. The dedicated appdata folder is for operators who keep firmware separate from covers/themes.

### Library root watch (`ONEIRODEX_LIBRARY_WATCH`) — Unraid honesty

Wave 3 optional watcher (Backend). **Safe default: off** (`ONEIRODEX_LIBRARY_WATCH=0` / unset). Do not enable until you understand mount-event limits below.

| Mount style | Host path example | What the container sees | Event honesty |
|---|---|---|---|
| **User-share FUSE** | `/mnt/user/games` (typical Unraid) | Bind of FUSE tree into `/storage:ro` | Host-side add/rename/delete **often missed** or delayed — FUSE/`shfs` does not reliably forward inotify to the container |
| **Disk / cache bind** | `/mnt/diskN/...` or `/mnt/cache/...` | Directer bind | Better chance of events, still not guaranteed across mover / cache↔array moves |
| **NFS / SMB remount inside container** | Extra volume on a network path | Nested remote FS | **Do not rely on watch** — use scheduled / manual scan |

**Operator rules**

1. Leave watch **off** on household Unraid unless you accept missed events and will still run scheduled scans.
2. When watch is on, it must see the **same mount** Admin libraries use (`/storage/...`). Watching a different host path than the games bind will miss library-root changes.
3. Host renames/moves under `/mnt/user/...` may never fire inside the container — treat watch as **best-effort enqueue**, not a substitute for scan jobs.
4. When the watcher enqueues many paths: prefer **Queue** (`queue_policy=queue`) over **Force parallel** — overlapping full/partial scans pin NAS CPU. See [§ CPU / scan load](#cpu--scan-load-unraid-safe-defaults) and [libraries-and-scans.md](../admin/libraries-and-scans.md#run-a-scan).
5. Env: `.env.example` / `.env.unraid.example` — `ONEIRODEX_LIBRARY_WATCH=0` (default) and optional `ONEIRODEX_LIBRARY_WATCH_DEBOUNCE_SEC=3`. Details: [library-root-watch-spike.md](../admin/library-root-watch-spike.md). Ops pulse: `services.library_watch`.

### Console / emulator leaf libraries

If the games share includes a mixed `_console-gaming` tree (families + emu installs + tools):

1. **Do not** create one library on `_console-gaming` or family parents (`NINTENDO`, `Sega`, `Sony`, …).
2. Create **one library per platform ROM/game leaf** under `/storage/.../_console-gaming/...` with matching `LibraryPlatform`, `scan_mode` files|folders, `scan_depth` 1 (or 2 only for `_a`…`_z` letter buckets).
3. Never point library `folder` at `_Emulators`, named emu installs, Pegasus/CRU/tools, or archive-only parents.
4. **Skip-dir** (built-in globs + Admin → Scanning filters `dir:…`) is defense-in-depth only — it does **not** replace per-leaf libs. Do not rely on skips to “fix” a family-root library.
5. Test-scan NES / Genesis / PS1 leaves first; Arcade ~6k dirs last. Games mount stays `:ro`.

Admin short form: [libraries-and-scans.md](../admin/libraries-and-scans.md#console--emulator-trees-_console-gaming).

## Image

Local build tag `oneirodex:1.1.0` (Compose default). Hub image: `cephyrixzyth/oneirodex` — set `APP_IMAGE`. The image includes `bash` for `entrypoint.sh`. Live stacks still named `oneirodex-app` pin `APP_CONTAINER_NAME` until the scan FIFO is idle.

## Compose Manager paths

This household’s Unraid stack **is** the git checkout (not a copy under `isos`):

| Field | Path |
|---|---|
| External ENV File Path | `/mnt/user/example-share/_projects/Oneirodex/.env` |
| Indirect Compose File | `/mnt/user/example-share/_projects/Oneirodex/docker-compose.yml` |
| Indirect Path | leave empty |

Windows mapping of the same tree: `Z:\_projects\Oneirodex`. Short copy notes: [NAS-DEPLOY.md](../../NAS-DEPLOY.md).

`/mnt/user/isos/oneirodex/` is **retired** — do not point Compose Manager there.

Copy template (only if `.env` is missing):

```bash
cp .env.unraid.example /mnt/user/example-share/_projects/Oneirodex/.env
# set SECRET_KEY + host volume paths, then Compose Manager → Update Stack
```

This household’s volume binds (inside `.env`, not as the compose-file path):

```bash
DATA_FOLDER_GAMES=/mnt/user/example-share/_software/_games
LIBRARY_HOST_PATH=/mnt/cache/appdata/oneirodex/library
```

## Optional profiles (full-stack test)

Sidecars are **opt-in** — not started with bare `app` + `db`.

| Profile | Enable | App env |
|---|---|---|
| `livekit` | `docker compose --profile livekit up -d` | `ENABLE_LIVEKIT=true` + `LIVEKIT_URL` + **your own** `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` (no `--dev`, no built-in pair; empty keys = container refuses to start) — [livekit-unraid.md](livekit-unraid.md) |
| `clamav` | `docker compose --profile clamav up -d` | `ENABLE_MALWARE_SCAN=true`, `CLAMAV_HOST=clamav` |
| `challenge` | `docker compose --profile challenge up -d` | `ENABLE_CHALLENGE_SOLVER=true`, `CHALLENGE_SOLVER_URL=http://trawl:8191` — [challenge-solver-unraid.md](challenge-solver-unraid.md) |
| `artwork` | `docker compose --profile artwork up -d` | `ENABLE_AI_ARTWORK=true`, `AI_ARTWORK_URL=http://sdnext:7860` — **CPU-only here**, see below |

**`artwork` has no GPU on this box.** The SD.Next sidecar runs on CPU, which is
extremely slow rather than broken — usually a reason not to enable the profile
here at all. It has no login, so its UI is published on `127.0.0.1:7860` only
(`SDNEXT_HOST_BIND`); the app reaches it as `http://sdnext:7860` over the Compose network. Put the generator on the Windows 2080 workstation with
[`docker-compose.artwork-local.yml`](../../docker-compose.artwork-local.yml)
and point `AI_ARTWORK_URL` at that LAN IP — [artwork-gpu-workstation.md](artwork-gpu-workstation.md).
Do **not** merge `docker-compose.gpu.yml` into Unraid `COMPOSE_FILE`. If a stack
update dies with `nvml error: driver not loaded`, set `COMPOSE_FILE=docker-compose.yml`
in the Unraid `.env` (or do not start `--profile artwork`). See
[container-wont-start.md](container-wont-start.md) 7.

Single-container household deployment:

```bash
docker compose up -d --build
```

This household’s Unraid `.env` pins `COMPOSE_FILE=docker-compose.single.yml` and points
`APPDATA_PATH` to a durable appdata directory. PostgreSQL data and generated secrets stay
under that `/config` bind; the current library, game, WebRetro-core, and EmulatorJS binds
remain separate. `APP_ENV_FILE` can point at a protected file in appdata with the existing
app settings. Product flags keep **`ENABLE_AI_AUTO_APPLY=false`** and
**`ALLOW_HARDLINK_APPLY=false`**. Artwork stays on the Windows 2080 box (`AI_ARTWORK_URL`).
`ONEIRODEX_LIBRARY_WATCH` stays off on `/mnt/user` FUSE. The old Compose PostgreSQL
container and named volume remain stopped until the embedded install has been validated.

SSO is **Authentik** already installed via Dockerman (`authentik` / `authentik-worker` on `authentik-net`, UI `http://192.0.2.10:9000`). Oneirodex OAuth slug **`oneirodex`**, redirect `http://192.0.2.10:5006/login/oidc/callback`. Env `OIDC_ENABLED=true` is not enough — also set `global_settings.oidc_enabled` (Admin → Integrations → OIDC, or SQL after rebuild). LAN HTTP cookies: `SESSION_COOKIE_SECURE=false`, `TRUSTED_PROXIES=0`. Walkthrough: [oidc-authentik-unraid.md](oidc-authentik-unraid.md) Appendix A.

**Observability / Grafana:** not bundled. Prefer Admin → Ops + probes. Commented Compose stub only — [observability-profile.md](observability-profile.md).

## First boot checklist

1. Set persistent `/config`, game, and library paths in `.env`
2. Start the app; watch logs until embedded PostgreSQL is ready
3. Confirm healthy: `curl -f http://<unraid-ip>:5006/awake` (Compose healthcheck uses this; `/pulse` is liveness-only)
4. Open `http://<unraid-ip>:5006`
5. Complete setup wizard (admin → SMTP optional → IGDB)
6. Admin → Themes → **Reset Default Themes** (installs presets; regenerates at `GENERATOR_VERSION` 9)
7. Add a library pointing at `/storage/...`
8. Run a small scan before a full library scan

## Factory wipe (still logging in after “wiped volumes”)

**Symptom:** You deleted some Docker volumes / appdata, but the UI still accepts login and shows libraries. The wipe may have hit a **different** Compose project, or the persistent `/config` bind may still contain the embedded database. User data is in PostgreSQL, not the games RO share.

**Do this on the Unraid host (SSH or Unraid terminal):**

1. **Identify the live project** (container names + `com.docker.compose.project`):

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}' | grep -Ei 'oneirodex|oneirodex'
docker inspect oneirodex-db --format '{{index .Config.Labels "com.docker.compose.project"}} → {{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect oneirodex-app --format '{{index .Config.Labels "com.docker.compose.project"}} → {{index .Config.Labels "com.docker.compose.project.working_dir"}}'
# Live Unraid until FIFO-idle recreate may still be oneirodex-db / oneirodex-app.
```

2. **Identify the database storage mode:**

```bash
docker inspect oneirodex-app --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
docker ps -a --format '{{.Names}} {{.Status}}' | grep oneirodex-db || true
# Embedded mode persists its cluster in the host path mounted at /config.
# Legacy two-container mode persists it in oneirodex_db_data at the Postgres PGDATA path.
```

3. **Confirm which database is active:**

```bash
docker exec oneirodex-app sh -c 'printf "embedded_mode=%s\\n" "$ONEIRODEX_EMBEDDED_DB"'
docker exec oneirodex-app bash -c 'export PGPASSWORD="$(cat /config/secrets/db_password)"; psql -h 127.0.0.1 -p 55432 -U oneirodex -d oneirodex -tAc "select count(*) from users"'
# For an external Postgres app, inspect DATABASE_URL without printing its credentials.
```

4. **Wipe THAT stack** from the project working_dir above (not a sibling `002`/`003`/`004` clone):

```bash
cd "$(docker inspect oneirodex-app --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')"
# Capture library bind before down (needed to empty host files):
LIB=$(docker inspect oneirodex-app --format '{{range .Mounts}}{{if eq .Destination "/app/oneirodex/static/library"}}{{.Source}}{{end}}{{end}}')
echo "LIBRARY host path: $LIB"
# Stop and back up /config before a factory wipe. This path is a bind mount, so
# `docker compose down -v` does not remove the embedded database or its secrets.
# Only remove the `/config` host directory when intentionally resetting the install.
# Legacy two-container mode: `docker compose down -v` removes its named db_data volume.
# Empty library bind (covers/themes/uploads) — does NOT touch /storage games RO:
[ -n "$LIB" ] && [ -d "$LIB" ] && rm -rf "${LIB:?}/"*
docker compose up -d --build
```

5. **Expect setup wizard** at `http://<unraid-ip>:5006` — login with old credentials must fail / redirect to setup. If login still works, you wiped the wrong project or `DATABASE_URL` is external.

| Failure mode | Why login/libraries survive |
|---|---|
| Wrong project prefix (`oneirodex` vs `002`/`003`/`004`) | `down -v` removed a sibling stack’s volume; live data remains |
| Embedded `/config` bind remains | Compose does not remove bind-mounted data; the embedded database and secrets remain there |
| `docker compose down` **without** `-v` in legacy mode | Containers gone; named volume `db_data` kept |
| External `DATABASE_URL` (LAN Postgres / other stack) | Local `/config` or `db_data` wipe is irrelevant; clear that external database only when intended |

See also [container-wont-start.md](container-wont-start.md) (§3 / §3b — do **not** wipe `db_data` for `pg_hba` fixes).

## Monitor while testing

Use this loop while Unraid-testing so the team can report status **without Discord / webhooks** — Ops glance + scan progress + container logs.

| Check | How | Pass signal |
|---|---|---|
| Readiness | `curl -f http://<unraid-ip>:5006/awake` | HTTP 200 (DB + init) |
| Liveness | `curl -f http://<unraid-ip>:5006/pulse` | HTTP 200 (process up) |
| Ops glance | Admin → Ops (`/admin/ops`) — polls `/admin/api/ops/summary` ~15s | `host` / `library` OK; `issues` not flagging games RO as bad; disk % stays **Warning / Info** (not Action required); **Services** = LiveKit · malware/ClamAV · companions · queues · game_servers |
| Scan progress | Admin → Scan jobs **or** Ops `scans.jobs[]` | `status` + `folders_success` / `folders_failed` / `total_folders` (+ `current_processing`); aliases `progress` / `errors` OK |
| Container logs | `docker compose logs -f app` (and `db` / profile sidecars) | No crash loops; theme sync / `[OK]` lines |

**Team feedback:** paste Ops summary highlights (`issues`, `scans.jobs[]` counters, `services.*` reachability) + last ~40 log lines — not chat webhooks.

## CPU / scan load (Unraid-safe defaults)

Scans and image downloads can pin a NAS CPU if parallelism is left high. **There is no Compose env for scan/image thread counts** — they live in **Admin → Settings → Server Settings** (`GlobalSettings`). Keep Compose `UVICORN_WORKERS=1` (already the Unraid template default).

| Knob | Where | Unraid-safe default | Notes |
|---|---|---|---|
| `UVICORN_WORKERS` | `.env` / Compose | **1** | SSE/schedulers are per-worker; do not raise on single-node Unraid |
| `ONEIRODEX_ENABLE_BACKGROUND_WORKERS` | `.env` / Compose | **true** | Schedulers (scan, library-watch, free-games, discover-ML, ownership, email-digest) start from the ASGI lifespan handler, not `create_app()`. Leave **true** on a single-node box; set `false` only for a web-only process that must not run them |
| Game scan threads | Server Settings | **1** (max **2** on capable hosts) | UI/API already cap at 4; overlapping full scans still freeze the host — one job at a time |
| Turbo image downloads | Server Settings | Off during first large scan, or threads **≤4**, batch **≤100** | Stored defaults are **4 / 100**; runtime also hard-caps via `OD_IMAGE_*` |
| ClamAV profile | Compose `--profile clamav` | **Off** until needed | Heuristics + `ENABLE_MALWARE_SCAN` still run without the daemon; defs + on-add scans add CPU/IO |
| Challenge / TRAWL | `--profile challenge` | Off unless Acquire needs it | Browser pool is heavy; old NAS → `TRAWL_IMAGE=…:baseline` |
| `ONEIRODEX_LIBRARY_WATCH` | `.env` | **0** (off) | Best-effort root-folder watch; enqueues scans only — see [§ Library root watch](#library-root-watch-gt_library_watch--unraid-honesty) |
| Watcher burst enqueue | Scan conflict UI / API | **Queue** (not force parallel) | Many path events → FIFO queue; force-parallel stacks jobs and spikes CPU |

After Backend lands harder code caps/defaults: rebuild + recreate **app**, then open Server Settings once and confirm values match the safe row above (existing DB rows may keep old highs until clamped or re-saved).

## Theme / JS not updating?

Library volume persists old theme files. After every code deploy (same as [Deploy gates → After deploy](#after-deploy-every-code-image)):

1. Free disk if needed, then `docker compose build --no-cache && docker compose up -d`
2. Watch logs for theme sync / `[OK] Default theme` / token presence
3. Admin → Themes → **Reset Default Themes** (or delete `themes/default` under the library volume and restart)
4. Confirm **`member-app.css` / `member-app.js`** load in the browser (View Source on Discover/Library). Missing CSS means the image rebuild did not include a fresh `frontend/member-app` dist — Reset Themes alone will not fix it

Full matrix: [themes-reset.md](../admin/themes-reset.md).

## Smoke checklist (Style B+C + Systems + Wave 5/6)

0. `curl -f http://<host>:5006/pulse` and `/awake` both succeed (Unraid Docker health should track `/awake`)
0a. After Jul 27 SSE/pg_hba fixes: `docker compose up -d --force-recreate db` then rebuild/restart **app** from a tree that includes `docker/postgres/pg_hba.conf` + ASGI activity SSE — [container-wont-start §3b](container-wont-start.md#3b-postgres-up-but-pg_hba-rejects-app-no-encryption) · [admin Discover hang](../admin/troubleshooting.md#spa-navigates-but-pagesadmin-hang-discover-stuck-on-loading)
0b. Admin → Ops (`/admin/ops`): **Services** tile shows LiveKit · malware/ClamAV · companions · queues · game_servers (via `/admin/api/ops/summary`)
0c. Console trees: leaf libs under `/storage/.../_console-gaming/...` only — not family roots; skip-dir is backup, not a substitute ([§ Console leaf libraries](#console--emulator-leaf-libraries))
1. First-boot logs show theme tokens OK (or Reset Default Themes after `GENERATOR_VERSION` 9)
2. Discover/Library: View Source includes **`member-app.css`** and `member-app.js`
3. Admin pages: View Source includes **`admin-app.css`** and `admin-app.js` (React admin SPA)
4. Default accent reads **green `#2fd67b`** (not teal/orange); Ocean/Forest still recolour on a normal reload
5. Top nav only on member pages (Discover, Library, **Systems**, Downloads, Favorites, More)
6. **Systems** (`/systems`): family groups load; click a console → library filtered with platform skin
7. Preferences swatch grid responds; page reloads after save; tile size changes grid density
8. Covers show for games with downloaded images (fallback only when truly missing)
9. Admin: React top bar — no member left sidebar; Dashboard / Libraries / Settings work
10. `/admin/settings` grouped rows (one sheet); Themes → Reset Default Themes after rebuild
11. Collections: create, search-add, reorder, edit, delete
12. **Game details SPA** (`/game_details/<uuid>`): TopNav present; summary/versions/screenshots load; Check stores works
13. **Updates** (`/updates`): freshness inbox; store search binds to library games; Want pack; Download / Apply
14. **Acquire** (`/acquire`, optional): ENABLE_ARR_MODULE / ENABLE_DEBRID — indexer search + librarian send
15. **Big Picture** (`/big-picture`): fullscreen shell (no TopNav); Open / Download / Install; Exit → Library
16. **Emulator play**: WebRetro cores for mapped platforms; cloud save button; .cht select when uploaded
17. Companion (optional): Install/Apply; assist packs when ENABLE_GAME_ASSISTS
18. **Social**: `/activity`, `/chat`, `/notifications`, `/report` load; admin `/admin/support` inbox
19. **LiveKit** (optional): `ENABLE_LIVEKIT` + `--profile livekit` — Activity voice lobby mints token ([livekit-unraid.md](livekit-unraid.md))

Operator sign-off: tick the list above after `build --no-cache` + Reset Default Themes, then mark Unraid smoke done (local strategy notes).

See also [docker-compose-deploy.md](docker-compose-deploy.md) · [observability-profile.md](observability-profile.md) · [themes-reset.md](../admin/themes-reset.md) · [support-inbox.md](../admin/support-inbox.md).

