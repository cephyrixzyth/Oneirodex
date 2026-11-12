# Docker Compose deploy — Oneirodex

> **Doc status:** Active

The repo includes two supported layouts: `docker-compose.yml` runs `oneirodex-app` plus `oneirodex-db`; `docker-compose.single.yml` runs one app container with embedded PostgreSQL. The single-container file reads app settings from `APP_ENV_FILE` (default `.env`) and keeps database files and generated secrets under the `/config` bind. Hub image: `cephyrixzyth/oneirodex` via `APP_IMAGE`.

Container startup opens with Onei's expedition field-terminal splash and prints
the initialization outcome as a quest-log entry. In non-interactive container
logs, the art stays plain text so the output remains readable.

## Prerequisites

- Docker Compose v2
- Host path to games (mounted read-only at `/storage`)
- Writable host path for library data (covers, themes)

The app starts as non-root `PUID:PGID` (default `99:100`). Set those variables
to match the owner of writable host mounts. On first start after upgrade or an
identity change, the entrypoint transfers ownership of the configured library
directory once per app identity and mounted library volume; its marker lives
inside that persistent library mount, so replacement mounts are prepared as
well. `/storage` is excluded and remains read-only.

Image builds pin the Node and Python base indexes by digest, install Debian
packages from a fixed Debian snapshot, and install Python runtime packages from
the hash-locked `requirements.lock`. Npm uses the committed integrity-bearing
root lockfile. Update direct runtime versions in `requirements.txt`, regenerate
the Python lock with `pip-tools==7.6.2`, and review the full lock diff together.
The EmulatorJS archive and font fallback assets also require their reviewed
SHA-256 digests. Before publishing, the workflow checks required licence files,
their pinned digests, and the third-party notice entries; it attaches BuildKit
SBOM and provenance attestations and records the published image digest beside
the source commit in its GitHub job summary.

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
# Optional store credential key ring: prepare the separate operator-managed JSON
# file, then uncomment its read-only bind mount below.
# Do NOT set DATABASE_URL=@localhost — Compose builds URL with host "db"
docker compose up -d --build
```

App: http://localhost:5006

The image includes the admin React shell and serves its page routes through
FastAPI. The container entrypoint fails startup if the packaged admin shell is
missing. Form posts and APIs that have not migrated use their native FastAPI
compatibility adapters while preserving the existing session and CSRF behavior.

Both Compose layouts set session and remember-me cookies to `Secure` by
default when those variables are unset. Existing `.env` files from older
templates may still explicitly set them to `false`; for HTTPS deployments,
change those existing values to `true` because explicit `.env` values override
the Compose defaults. Use HTTPS at a reverse proxy for normal browser access.
Direct HTTP access by LAN address will not retain authenticated cookies; setting both
`SESSION_COOKIE_SECURE=false` and `REMEMBER_COOKIE_SECURE=false` opts into
sending authentication cookies over HTTP. The loopback-only review Compose
file keeps that explicit local-development override.

Chat attachments share a **1 GiB** total storage cap across users and channels
by default, with a **10,000-file** cap to bound directory checks during uploads.
Set `CHAT_ATTACHMENT_STORAGE_MAX_BYTES` or `CHAT_ATTACHMENT_STORAGE_MAX_FILES`
in `.env` to raise either limit. Zero or unset uses the 1 GiB and 10,000-file
defaults. The file cap counts regular files, including orphaned files, under
`UPLOAD_FOLDER/chat-attachments` across all channels.

## Free isolated public demo (Blitz)

The public preview runs at
[`https://demo.oneirodex.blitz.cloud/demo`](https://demo.oneirodex.blitz.cloud/demo)
on Blitz's free plan, built from the public `cephyrixzyth/oneirodex` repository's
`main` branch. It uses the attached free PostgreSQL database and a persistent
`/config` volume for app data. Startup creates a member-only visitor, fetches the
five licensed homebrew sample ROMs into `/config/library/demo-games`, provisions
the four browser cores those samples use, and signs visitors in through `/demo`.
It does not seed an admin, use household data, or configure external service
credentials. The app listens on the host-provided `PORT`; Compose and Unraid
continue to default to 5006.

The isolated service sets `ONEIRODEX_PUBLIC_DEMO=true`,
`ONEIRODEX_EMBEDDED_DB=false`, `ONEIRODEX_CONFIG_DIR=/config`,
`ONEIRODEX_LIBRARY_DIR=/config/library`, `SESSION_COOKIE_SECURE=true`, and
`REMEMBER_COOKIE_SECURE=true`. The demo sets `DATA_FOLDER_GAMES` to the persistent
`/config/library/demo-games` directory so the sample ROM download route accepts
those files. Disable optional external integrations. These five samples do not
require console BIOS files. The free service sleeps when idle and can take time
to cold-start; its database and persistent volume may reset after a restart or
deploy. The free host subdomain is used directly; this is not a production
storage target.

`render.yaml` remains an alternate Render Blueprint for the same isolated demo.
The demo seed runs from the app root via `PYTHONPATH=/app` so the script can
import the `oneirodex` package when launched by the container entrypoint. The
free ROM fetcher supports repeatable `--id` filters so the demo downloads only
its listed samples rather than every ROM in the manifest.

## Volume sectioning

Do **not** conflate games (scan root) with library/uploads. Compose header has an **UNRAID VOLUMES** comment block; container env hard-sets `DATA_FOLDER_GAMES=/storage` and `UPLOAD_FOLDER=/app/oneirodex/static/library` while `.env` supplies **host** bind paths.

| Role | Host env | Container mount | Mode | Purpose |
|---|---|---|---|---|
| **Games** | `DATA_FOLDER_GAMES` | `/storage` | **ro** | Scan root only — never uploads |
| **Library / uploads** | `LIBRARY_HOST_PATH` | `/app/oneirodex/static/library` | **rw** | Covers, themes, uploads |
| **Optional BIOS / firmware** | `EMULATOR_BIOS_HOST_PATH` (uncomment bind in compose) | `/app/oneirodex/static/library/bios` | **rw** | Private host firmware under appdata — not games. Public stance remains Admin upload-only — [unraid-deploy.md § Local private BIOS](unraid-deploy.md#local-private-bios-mount-vs-public-upload) |
| Optional WebRetro cores | `WEBRETRO_CORES_HOST_PATH` (uncomment in compose) | `/app/oneirodex/static/vendor/webretro/cores` | rw | Operator WASM cores — [webretro-cores.md](webretro-cores.md) |
| Postgres | Compose volume `db_data` | `/var/lib/postgresql/data/pgdata` | rw | DB |
| Store credential key ring | `ONEIRODEX_STORE_CREDENTIAL_KEYRING_HOST_PATH` (uncomment in compose) | `/run/secrets/oneirodex-store-credential-keyring.json` | **ro** | Dedicated key file; back it up separately from database/library data |
| Emulator save key ring | `ONEIRODEX_SAVE_KEYRING_HOST_PATH` (uncomment in compose) | `/run/secrets/oneirodex-save-keyring.json` | **ro** | Separate from integration and cookie keys; protect and back it up separately |
| pg_hba | `./docker/postgres/pg_hba.conf` | `/etc/oneirodex/pg_hba.conf` | ro | App↔db TCP without SSL (scram still required), private source ranges only |

If app loops on `no pg_hba.conf entry … no encryption`, recreate `db` with current Compose or use the one-liner in [container-wont-start.md](container-wont-start.md#3b-postgres-up-but-pg_hba-rejects-app-no-encryption).

### Credential key ring

Store-provider and admin integration credentials use an authenticated key ring,
separate from `SECRET_KEY` and database credentials. Create a JSON file outside the database
and library backup payloads, restrict host access, then mount it read-only at
`/run/secrets/oneirodex-store-credential-keyring.json`. Configure
`ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE` to that in-container path. The old
`ONEIRODEX_STORE_CREDENTIAL_KEYRING_FILE` name remains a compatibility alias. The JSON
shape is `{ "active_key_id": "key-a", "keys": { "key-a": "<Fernet key>" } }`;
keep prior key IDs in `keys` while data encrypted under them remains.
On Linux, keep the containing directory private and set the key-ring file to
mode `0600`; the app refuses to load a key ring with group or other permission
bits. On Windows, set an NTFS ACL that grants read access only to the Oneirodex
service account and administrators; Python cannot validate those ACLs with its
portable POSIX-mode check.

Back up the key ring separately under protected access. Database backups without
the key ring cannot restore encrypted store sync or admin integrations; the key ring itself must not be
placed in the database or library backup payload. Losing it leaves encrypted
credentials unreadable.

The key ring is optional at install time. Without it, saving member sign-in
tokens and saving reusable admin integration credentials are unavailable;
existing encrypted values cannot be used until their matching key is restored.
Members can still save an account
identifier without a token, import a list, or disconnect; existing links and
title history are retained. Some operator household-token paths that do not
persist refreshed credentials remain usable.

### Save keyring

Encrypted emulator saves use a distinct keyring configured with
`ONEIRODEX_SAVE_KEYRING_FILE` and mounted read-only at
`/run/secrets/oneirodex-save-keyring.json`. Create it with
`python scripts/migrate_emulator_save_keys.py --initialize-keyring <protected-output>`
while the existing `SECRET_KEY` is available. The generated ring retains the
legacy derived key for reading `GTENC1` saves and writes new saves with a
versioned key ID. Do not store key material in `.env`, the database, or a move
bundle. Keep the ring and its protected backup outside database and library
backup payloads. Linux keyring files must be mode `0600`; on Windows, restrict
the NTFS ACL to the service account and administrators.

To rotate keys, prepare a second file with
`python scripts/migrate_emulator_save_keys.py --rotate-keyring-from <current-ring> --write-keyring <new-ring>`.
Preserve both protected rings, point the app at the new one, stop save writers,
then run `python scripts/migrate_emulator_save_keys.py --migrate --root <save-root>`
for a report-only inventory. Repeat with `--apply` to re-encrypt current and
retained generations. The migration stages a new immutable file, then commits
its metadata path. It removes the old file only after checking that no current
or retained generation still references it, including normalized path aliases.
Uncertain references or an ambiguous commit preserve ciphertext for recovery.
Applied migration uses the same owner lock as save writes and refreshes metadata
after waiting; this defensive protection does not replace stopping all writers.
The report-only command remains read-only. It keeps each save generation and
never schedules history garbage collection. Retain old key IDs for encrypted
backups that still need them. The command does not contact providers or load
`.env`; set `DATABASE_URL`
for an external database or use the embedded database environment described
by the script.

[R2039 evidence](../dev/parity-evidence/save-rotation-safety-r2039.json) covers
synthetic shared-path, writer-overlap and abrupt process-exit recovery checks.
It does not qualify your operator backup media or a fully online migration.

#### Convert existing credentials after upgrading

The schema upgrade must run once on the new image before the conversion command.
Stop every old app instance first so no old version can write plaintext while
conversion runs. Before conversion, take a protected database backup; a backup
made before conversion can still contain plaintext provider credentials. With
the new Compose image started once and its schema upgrade
complete, stop the app and run:

```bash
docker compose stop app
docker compose run --rm --no-deps --entrypoint python3 app /app/scripts/migrate_reusable_secrets.py
docker compose run --rm --no-deps --entrypoint python3 app /app/scripts/migrate_store_credentials.py
docker compose up -d app
```

The Compose service supplies `DATABASE_URL` and the mounted key-ring path to the
converter. It requires that process-level `DATABASE_URL`; it does not read `.env`
or fall back to `TEST_DATABASE_URL`. It verifies each ciphertext against the
source before clearing legacy plaintext, commits one row at a time, is safe to
rerun, prints counts only, and makes no provider calls. A missing or invalid key,
database conflict, or row failure exits nonzero; investigate the redacted count
and rerun after fixing the cause. Do not leave the app stopped until the
conversion succeeds and new app is started.

The reusable-secret converter handles scalar GlobalSettings values and the
enumerated *arr, debrid, challenge-solver, lighting, and indexer JSON credentials.
For key rotation, add a new key ID to `keys`, set `active_key_id` to it, then run
both converters while the app is stopped. They re-encrypt values under the
active key and verify before commit. Keep previous key IDs until both runs
report `rotated=0` with no failures and no retained database backups require
those keys. Never remove keys based only on the current database if older
backups still contain ciphertext encrypted under them.

## Postgres exposure and password

The bundled `db` service is a superuser login, so three independent layers keep it
off the LAN. The app container uses none of the host-side ones: it reaches `db:5432`
over the Compose network.

| Layer | Default | Change it by |
|---|---|---|
| Published host port | `127.0.0.1:5432` — `POSTGRES_HOST_BIND` (default `127.0.0.1`) and `POSTGRES_HOST_PORT` (default `5432`) | Set `POSTGRES_HOST_BIND=<host LAN IP>` (or `0.0.0.0`) in `.env`; when an existing database volume is present, startup verifies the configured password through a private loopback-only connection before exposing the port. |
| Client auth | `docker/postgres/pg_hba.conf`: scram-sha-256 from loopback, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and `fc00::/7` only. There is no `0.0.0.0/0` rule. | Add a line for any other CIDR (a custom Docker address pool, Tailscale `100.64.0.0/10`, a global IPv6 prefix), then `docker compose up -d --force-recreate db`. |
| Password | `POSTGRES_PASSWORD` in `.env`. The templates ship a `CHANGE_ME…` placeholder, and both app and database startup reject it. Compose retains the old `postgres` fallback for interpolation, but startup rejects it by default. | For an existing volume only, set `ONEIRODEX_ALLOW_LEGACY_POSTGRES_PASSWORD=true` to regain service temporarily, rotate the DB credential below, then set it back to `false`. New volumes reject the default even with the compatibility flag. |

The database entrypoint checks the password and effective host bind before
starting. The legacy `postgres` password is blocked unless the explicit
`ONEIRODEX_ALLOW_LEGACY_POSTGRES_PASSWORD=true` compatibility flag is set and an
existing `db_data` volume is detected. This flag is temporary: keep the host bind
on loopback, rotate to a unique password, then turn the flag off. Non-loopback
publication requires a non-default `POSTGRES_PASSWORD`. On an existing database
volume, startup temporarily starts Postgres bound only to the container's
loopback interface and authenticates with the configured password before the
published listener starts. The configured account must also be the volume's
only login-capable superuser, so a second privileged role cannot bypass the
checked credential. A mismatch, additional login-capable superuser, or failed
probe refuses startup. Fresh volumes are initialized using the configured
password. The check runs in the database container, so it still applies when
the app container is stopped.

Generate a password (hex, because it is spliced into `DATABASE_URL` and `@ : / ? # % $` would break the URL):

```bash
python -c "import secrets; print(secrets.token_hex(24))"     # or: openssl rand -hex 24
```

### Upgrading an existing stack

`git pull` then `docker compose up -d` recreates `db` with the new port mapping. The
database volume is untouched. If your `.env` has no password or still uses the
legacy value `postgres`, enable temporary compatibility before starting:

```dotenv
ONEIRODEX_ALLOW_LEGACY_POSTGRES_PASSWORD=true
```

Keep `POSTGRES_HOST_BIND=127.0.0.1`, rotate the password using the procedure below,
then set `ONEIRODEX_ALLOW_LEGACY_POSTGRES_PASSWORD=false` and recreate the app and
database containers. The database guard refuses the legacy default for fresh
volumes even while the compatibility flag is enabled.

The other change is:

- **The host port is now loopback-only.** If something on another machine connects
  to this host's `5432` (pytest, a GUI client, a second app), set `POSTGRES_HOST_BIND`
  as above.
- **A legacy `postgres` password is now an explicit, temporary compatibility choice.**
  Rotate it as soon as the upgraded stack is running.
- **Before enabling a non-loopback bind, rotate the password inside the database**
  using the steps below. The database entrypoint checks that the configured
  password authenticates against the existing volume before allowing the bind.

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
- **Unraid `/mnt/user` FUSE / network remounts** — host-side renames and many writes **often never reach** inotify inside the container. Prefer scheduled/manual scan; details: [unraid-deploy.md § Library root watch](unraid-deploy.md#library-root-watch-oneirodex_library_watch--unraid-honesty).
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
