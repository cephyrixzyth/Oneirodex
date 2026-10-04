# Docker Compose deploy — Oneirodex

> **Doc status:** Active

The repo includes two supported layouts: `docker-compose.yml` runs `oneirodex-app` plus `oneirodex-db`; `docker-compose.single.yml` runs one app container with embedded PostgreSQL. The single-container file reads app settings from `APP_ENV_FILE` (default `.env`) and keeps database files and generated secrets under the `/config` bind. Hub image: `cephyrixzyth/oneirodex` via `APP_IMAGE`.

## Prerequisites

- Docker Compose v2
- Host path to games (mounted read-only at `/storage`)
- Writable host path for library data (covers, themes)

## Isolated local staging

Use `docker-compose.review.yml` with a distinct Compose project and an explicit
staging env file so Compose does not read the checkout's live `.env`. Set
`ONEIRODEX_REVIEW_PREFIX`, `ONEIRODEX_REVIEW_PORT` and
`ONEIRODEX_REVIEW_DB_PORT` in that file to unused local names/ports. Published
ports bind only to `127.0.0.1` (defaults 6120 and 5432). The project owns separate
database, library/upload and read-only game volumes; artwork integration is off.

```bash
docker compose --env-file /path/to/staging.env -p oneirodex-staging -f docker-compose.review.yml config --quiet
docker compose --env-file /path/to/staging.env -p oneirodex-staging -f docker-compose.review.yml up -d --build
```

The Docker build uses Node 22 and Python 3.12 with repository dependency pins,
isolating runtime imports from other tools installed on the host. Run `python -m
pip check` in the built image before accepting it. A health endpoint is only the
first check: finish setup with test-only accounts, then smoke member and admin
flows. Stop staging with `down` without `-v` when retaining its test data.

Before a production release, record the exact clean source commit, built image
digest and previous image digest. A dirty local build is staging evidence only;
record its base commit and patch identity separately. Back up Postgres with
`pg_dump -Fc` and the writable library volume, restore both into a separate test
project, and verify the restored catalog before deployment. Rollback uses the
previous image plus its matching database/library backup when schema changes
are not backward compatible. Recheck target disk allocation before transferring
images or backups. Local staging acceptance does not deploy or update a NAS.

## Setup

```bash
cp .env.docker.example .env          # local/NAS
# Unraid: this checkout IS the stack — cp .env.unraid.example .env
#   Compose Manager: /mnt/user/example-share/_projects/Oneirodex
#   (not /mnt/user/isos/oneirodex/ — retired). See unraid-deploy.md
# Set SECRET_KEY (required — container refuses the placeholder)
# Set POSTGRES_PASSWORD to a strong value (see "Postgres exposure and password")
# Set DATA_FOLDER_GAMES = HOST games path
# Set LIBRARY_HOST_PATH = HOST library/appdata path (default ./data/library)
# Optional BIOS: EMULATOR_BIOS_HOST_PATH + uncomment bios bind in compose
#   (appdata only — never games share; never commit firmware binaries)
# Do NOT set DATABASE_URL=@localhost — Compose builds URL with host "db"
docker compose up -d --build
```

App: http://localhost:5006

## Free isolated public demo (Render)

`render.yaml` defines a separate $0 Render Docker service for a disposable
public demo. It uses the embedded PostgreSQL database under `/tmp`, creates a
member-only visitor and five clearly labeled homebrew sample titles at startup,
and signs visitors in through `/demo`. It does not seed an admin, include ROM
files, use household data, or configure external service credentials. The app
listens on Render's `PORT` value; Compose and Unraid continue to default to
5006.

To provision it, connect the public `cephyrixzyth/oneirodex` GitHub repository
to Render, create a Blueprint from `render.yaml`, and choose the Free plan.
The free service sleeps after 15 minutes without inbound traffic; its first
request after sleep has a cold start. Render's filesystem is ephemeral, so
demo state resets after a restart or deploy. Do not attach a paid disk or
database for this demo. Once the service is live, set `liveDemoUrl` in the
website repo to `https://<render-service>.onrender.com/demo`.

Render requires a connected account and repository authorization to create the
service. Its free tier requires no payment method, but it has no persistent
filesystem; treat the service as a preview only, never as production storage.

## Volume sectioning

Do **not** conflate games (scan root) with library/uploads. Compose header has an **UNRAID VOLUMES** comment block; container env hard-sets `DATA_FOLDER_GAMES=/storage` and `UPLOAD_FOLDER=/app/oneirodex/static/library` while `.env` supplies **host** bind paths.

| Role | Host env | Container mount | Mode | Purpose |
|---|---|---|---|---|
| **Games** | `DATA_FOLDER_GAMES` | `/storage` | **ro** | Scan root only — never uploads |
| **Library / uploads** | `LIBRARY_HOST_PATH` | `/app/oneirodex/static/library` | **rw** | Covers, themes, uploads |
| **Optional BIOS / firmware** | `EMULATOR_BIOS_HOST_PATH` (uncomment bind in compose) | `/app/oneirodex/static/library/bios` | **rw** | Private host firmware under appdata — not games. Public stance remains Admin upload-only — [unraid-deploy.md § Local private BIOS](unraid-deploy.md#local-private-bios-mount-vs-public-upload) |
| Optional WebRetro cores | `WEBRETRO_CORES_HOST_PATH` (uncomment in compose) | `/app/oneirodex/static/vendor/webretro/cores` | rw | Operator WASM cores — [webretro-cores.md](webretro-cores.md) |
| Postgres | Compose volume `db_data` | `/var/lib/postgresql/data/pgdata` | rw | DB |
| pg_hba | `./docker/postgres/pg_hba.conf` | `/etc/oneirodex/pg_hba.conf` | ro | App↔db TCP without SSL (scram still required), private source ranges only |

If app loops on `no pg_hba.conf entry … no encryption`, recreate `db` with current Compose or use the one-liner in [container-wont-start.md](container-wont-start.md#3b-postgres-up-but-pg_hba-rejects-app-no-encryption).

## Postgres exposure and password

The bundled `db` service is a superuser login, so three independent layers keep it
off the LAN. The app container uses none of the host-side ones: it reaches `db:5432`
over the Compose network.

| Layer | Default | Change it by |
|---|---|---|
| Published host port | `127.0.0.1:5432` — `POSTGRES_HOST_BIND` (default `127.0.0.1`) and `POSTGRES_HOST_PORT` (default `5432`) | `POSTGRES_HOST_BIND=<host LAN IP>` (or `0.0.0.0`) in `.env`, then `docker compose up -d db`. Opt-in; set a strong password first. |
| Client auth | `docker/postgres/pg_hba.conf`: scram-sha-256 from loopback, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and `fc00::/7` only. There is no `0.0.0.0/0` rule. | Add a line for any other CIDR (a custom Docker address pool, Tailscale `100.64.0.0/10`, a global IPv6 prefix), then `docker compose up -d --force-recreate db`. |
| Password | `POSTGRES_PASSWORD` in `.env`. The templates ship a `CHANGE_ME…` placeholder, and the app container refuses to start while it is still set. Compose falls back to `postgres` only when the variable is unset, so old stacks keep starting (with a warning in the log). | See below. |

Generate a password (hex, because it is spliced into `DATABASE_URL` and `@ : / ? # % $` would break the URL):

```bash
python -c "import secrets; print(secrets.token_hex(24))"     # or: openssl rand -hex 24
```

### Upgrading an existing stack

`git pull` then `docker compose up -d` recreates `db` with the new port mapping. The
stack still starts with your current `.env` and the database is untouched, but two
things change:

- **The host port is now loopback-only.** If something on another machine connects
  to this host's `5432` (pytest, a GUI client, a second app), set `POSTGRES_HOST_BIND`
  as above.
- **If `.env` still has `POSTGRES_PASSWORD=postgres` (or none), the superuser password
  is a known value.** It is no longer reachable from the LAN, but rotate it.

### Rotating the password on an existing database

`POSTGRES_PASSWORD` is read only when Postgres first creates the `db_data` volume.
Editing `.env` alone does **not** change the database password and locks the app out
(`password authentication failed`, [container-wont-start.md](container-wont-start.md#3c-password-authentication-failed-after-changing-postgres_password)).
Change both, in this order:

```bash
# 1. Set the new password inside the database. The in-container socket is trusted,
#    so no old password is needed; \password hashes it client-side.
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
#    at the prompt:  \password    (enter it twice)   then  \q

# 2. Put the same value in .env as POSTGRES_PASSWORD, then recreate the app so its
#    DATABASE_URL picks it up.
docker compose up -d --force-recreate app
```

A fresh install (no `db_data` volume yet) just takes the value from `.env`.

### Library root watch (optional Wave 3)

`ONEIRODEX_LIBRARY_WATCH` stays **off by default** (`0` / unset). Compose bind-mounts only forward filesystem events the kernel delivers on that mount:

- **Direct host binds** (local disk path → `/storage:ro`) — events may work; still debounce + queue, never assume zero misses.
- **Unraid `/mnt/user` FUSE / network remounts** — host-side renames and many writes **often never reach** inotify inside the container. Prefer scheduled/manual scan; details: [unraid-deploy.md § Library root watch](unraid-deploy.md#library-root-watch-gt_library_watch--unraid-honesty).
- When a watcher (or Admin) enqueues many paths while a scan is busy: use **Queue**, not force-parallel — [libraries-and-scans.md](../admin/libraries-and-scans.md#run-a-scan).

## After first start

1. Complete setup wizard
2. Admin → Themes → **Reset Default Themes** (ensures `#2fd67b` tokens / `GENERATOR_VERSION` 9)
3. Add library under `/storage/...`, run a small scan

## Rebuild after frontend/theme changes

```bash
docker compose build --no-cache && docker compose up -d
```

Then Reset Default Themes if the library volume still has stale CSS.

**Admin SPA build note:** `frontend-build` copies `oneirodex/setup/default_theme/js/stageECandidates.js`, `unmatchedTriage.js`, and `scanJobsDom.js` into the build tree before `admin-app` `npm run build` so relative SoT re-exports resolve (those files are not under `frontend/admin-app/`).

## Other optional profiles

### LiveKit voice

```bash
# 1. Generate your own pair once (the app and the SFU read the same two values)
python -c "import secrets; print('LIVEKIT_API_KEY=odx' + secrets.token_hex(6)); print('LIVEKIT_API_SECRET=' + secrets.token_hex(32))"
# 2. In .env: paste those two lines, plus
#      ENABLE_LIVEKIT=true
#      LIVEKIT_URL=ws://<lan-host>:7880      # a name real browsers can reach
# 3. Start it
docker compose --profile livekit up -d
```

LiveKit no longer runs in `--dev` mode, so there is no built-in `devkey` / `secret`
pair for anyone on the LAN to mint room tokens with. With the key or secret empty
the `livekit` container refuses to start rather than run open. Stacks that still
carry `devkey` / `secret` start, but LiveKit logs `secret is too short`: rotate both
values (upgrade steps in [livekit-unraid.md](livekit-unraid.md#upgrading-a-stack-that-used---dev)).

Full notes: [livekit-unraid.md](livekit-unraid.md).

### ClamAV malware scan

```bash
export ENABLE_MALWARE_SCAN=true
export MALWARE_SCAN_BLOCK_ON_HIT=true   # skip library adds on heuristic/ClamAV match
export CLAMAV_HOST=clamav
export CLAMAV_PORT=3310
docker compose --profile clamav up -d
```

- Compose profile starts `clamav/clamav` with a persistent `clamav_db` volume (first start may take several minutes while definitions download).
- **Unraid / host clamd:** bind-mount the host socket into the app container and set `CLAMAV_SOCKET=/run/clamav/clamd.sock` instead of TCP.
- Status: `GET /api/admin/malware-scan/status` (admin) or Admin → Features → Malware scanner section.

### Generated cover art (SD.Next)

```bash
export ENABLE_AI_ARTWORK=true
export AI_ARTWORK_URL=http://sdnext:7860
export AI_ARTWORK_ENGINE=a1111
docker compose --profile artwork up -d
```

- **No GPU is requested by default, on purpose.** The sidecar runs on CPU —
  extremely slow, but it runs. An NVIDIA reservation on a host with no loaded
  driver does not degrade, it fails container create with `nvml error: driver
  not loaded` and aborts the whole stack update. See
  [container-wont-start.md](container-wont-start.md) § 7.
- **GPU in this Docker host:** opt in with the overlay, after confirming
  `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi`
  works:

  ```bash
  # in .env (Linux hosts; use ";" as the separator on Windows)
  COMPOSE_FILE=docker-compose.yml:docker-compose.gpu.yml
  ```

- **SD.Next has no login**, so the sidecar publishes its UI on `127.0.0.1:7860`
  only (`SDNEXT_HOST_BIND`, default `127.0.0.1`). The app reaches it over the
  Compose network at `http://sdnext:7860` and does not use that mapping. To open
  the UI from another machine set `SDNEXT_HOST_BIND=<this host's LAN IP>`.
- **GPU on another machine** (the usual case for a GPU-less NAS): skip the
  profile entirely. On a Windows box with a card, use
  [`docker-compose.artwork-local.yml`](../../docker-compose.artwork-local.yml)
  — [artwork-gpu-workstation.md](artwork-gpu-workstation.md) — then set
  `ENABLE_AI_ARTWORK` / `AI_ARTWORK_URL` / `AI_ARTWORK_ENGINE` in `.env` and
  recreate **app** (those keys are mapped in `docker-compose.yml`). Turnkey
  pairing for that shape is backlog **GPU-N**.

### Challenge / captcha solver (TRAWL)

```bash
export ENABLE_CHALLENGE_SOLVER=true
export CHALLENGE_SOLVER_URL=http://trawl:8191
export CHALLENGE_SOLVER_MAX_TIER=5
export ALLOW_PRIVATE_LAN_URLS=true   # Unraid / RFC1918 solver URL
docker compose --profile challenge up -d
docker compose up -d app   # reload app env
```

- Profile **`challenge`** starts Redis + `ghcr.io/germondai/trawl` — **no host ports** (Docker network only).
- Default remains off: `ENABLE_CHALLENGE_SOLVER=false` in `.env.example`.
- Old NAS CPUs: `TRAWL_IMAGE=ghcr.io/germondai/trawl:baseline` in `.env`.
- Full Unraid steps + MITM CA warning: [challenge-solver-unraid.md](challenge-solver-unraid.md).

## Monitor while testing

Feedback loop for local/Unraid tests — use Ops glance + scan progress + logs (**no Discord / webhooks**).

| Check | How | Pass signal |
|---|---|---|
| Readiness | `curl -f http://localhost:5006/awake` | HTTP 200 (DB + init); Compose `healthcheck` uses this |
| Liveness | `curl -f http://localhost:5006/pulse` | HTTP 200 |
| Ops glance | Admin → Ops (`/admin/ops`) → `/admin/api/ops/summary` ~15s | `host` / `library` OK; games RO not a path issue; **Services** (LiveKit · malware · companions · queues · game_servers) |
| Scan progress | Admin scan jobs **or** Ops `scans.jobs[]` | `folders_success` / `folders_failed` / `total_folders` (+ `current_processing`); aliases `progress` / `errors` OK |
| Container logs | `docker compose logs -f app` (+ `db` / profile sidecars) | No crash loops |

## Smoke

- Health + Ops + scan checks from **Monitor while testing** above
- View Source on Discover/Library: `member-app.css` + `member-app.js` present
- Accent green `#2fd67b`; Systems hub (`/systems`) loads
- Admin uses top bar only (no member LHN)
- Optional: Activity voice lobby when LiveKit enabled

### Observability (optional — not required for 1.0)

Prometheus/Grafana are **not** bundled. Near-realtime ops for operators = Admin → Ops (`/admin/ops`, polls `/admin/api/ops/summary` including **Services**: LiveKit, malware/ClamAV, companions, queues, game_servers) + the probes above. Compose keeps a commented `# profile: observability` stub — see [observability-profile.md](observability-profile.md). Do not block upgrades on scrape.

### Workers

Default `UVICORN_WORKERS=1` (Compose + `startweb-docker.sh`; override in `.env` / Compose env). Schedulers, SSE fan-out, and in-memory rate limits are **per worker** — keep **1** for single-node household ops until a shared cache lands. Set `UVICORN_WORKERS=2` only when you accept split in-process state.

`UVICORN_GRACEFUL_TIMEOUT` controls how many seconds Uvicorn waits for active HTTP requests after `SIGTERM` before cancelling them (default **5**). Raise it in `.env` if a reverse proxy or container stop routinely interrupts longer requests; Docker's `stop_grace_period` should be longer than this value.

Background schedulers (scan, library-watch, free-games, discover-ML, ownership, email-digest) start from the **ASGI lifespan handler** (`asgi.py`), not `create_app()`. `ONEIRODEX_ENABLE_BACKGROUND_WORKERS` (default **true**) gates them — set `false` only for a web-only process that must not run them (e.g. a second replica behind the same DB).

Scan / turbo image thread counts are **not** Compose env vars — set them under Admin → Server Settings. Unraid-safe defaults (scan **1**, turbo off or ≤4 threads during big libraries): [unraid-deploy.md § CPU / scan load](unraid-deploy.md#cpu--scan-load-unraid-safe-defaults). Keep `ONEIRODEX_LIBRARY_WATCH` off unless you accept best-effort events; watcher bursts should **queue**, not force-parallel.

`/api/activity/stream` and `/api/events/stream` are handled **natively in ASGI** (not WsgiToAsgi) so a single open EventSource cannot freeze Discover/Admin on the same worker. Flask WSGI fallbacks return **503** (no sync generator). If pages hang with only static + activity-stream 200s in the logs, rebuild/restart so that ASGI path is live — see [admin troubleshooting](../admin/troubleshooting.md#spa-navigates-but-pagesadmin-hang-discover-stuck-on-loading).

Unraid-specific notes: [unraid-deploy.md](unraid-deploy.md). Break-glass: [container-wont-start.md](container-wont-start.md).
