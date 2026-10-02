# Runbook: Container will not start

## Symptoms

- Unraid / Docker shows exited / restart loop
- Logs stop immediately after start
- Healthcheck fails forever
- App unhealthy / restarting while **db is healthy**, logs show `no pg_hba.conf entry … no encryption` (see §3b)
- App restarting after `.env` was edited, logs show `password authentication failed for user` (see §3c)
- `livekit` container exits with `one of key-file or keys must be provided` (see §10)
- GPU service never gets created, `nvml error: driver not loaded` (see 7)
- Container serves fine but sits **unhealthy** forever (see 8)

## Checklist (in order)

### 1. SECRET_KEY missing or placeholder

**Log signature:** `RuntimeError: SECRET_KEY environment variable is not set`

**Fix:** Set a strong random `SECRET_KEY` in the container env. Do not use `put_your_own_secret_string_here_32617432`.

### 2. Bash / entrypoint failure

**Log signature:** `exec /bin/bash: no such file` or `entrypoint.sh: not found`

**Fix:** Rebuild from current Dockerfile (installs `bash`). Ensure `entrypoint.sh` has LF line endings (`sed -i 's/\r$//'` is in the Dockerfile).

Startup exits when initialization fails, including a failed force-setup reset;
workers start only after initialization succeeds. Resolve the initialization error
before restarting. The entrypoint and startup script use `exec`, so Docker's
shutdown signal reaches uvicorn directly.

### 3. Postgres not ready / wrong host

**Log signature:** connection refused to `db` / timeout waiting for PostgreSQL

**Fix:** Confirm `DATABASE_URL` host is reachable from the app container. On Compose, hostname is `db`. On Unraid with external Postgres, use the LAN IP/hostname. Check `POSTGRES_USER` / password / db name match.

### 3b. Postgres up but `pg_hba` rejects app (`no encryption`)

**Log signature:**
```text
FATAL: no pg_hba.conf entry for host "172.x.x.x", user "postgres", database "oneirodex", no encryption
```

Postgres is reachable; it is **refusing non-SSL TCP** from the app container IP (common after a hardened / stale volume `pg_hba.conf`).

The shipped `docker/postgres/pg_hba.conf` allows scram-sha-256 only from loopback and the private ranges `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and `fc00::/7`, and has no `0.0.0.0/0` rule. If the logged address is **outside** those ranges (a custom Docker address pool, Tailscale `100.64.0.0/10`, a global IPv6 prefix), add one line for that CIDR to `docker/postgres/pg_hba.conf` and recreate `db`. Do not add `0.0.0.0/0`: together with a default password it hands every reachable network a superuser login.

**Fix (preferred):** Pull current Compose (ships `docker/postgres/pg_hba.conf` + `hba_file=` override) and recreate **db** (keeps data volume):

```bash
docker compose up -d --force-recreate db
docker compose up -d app
```

Confirm active HBA: `docker compose exec db psql -U postgres -d oneirodex -c "SHOW hba_file;"` → `/etc/oneirodex/pg_hba.conf`.

**Fix (legacy stacks without `hba_file=`):** only when `SHOW hba_file` still points at `$PGDATA/pg_hba.conf`:

```bash
docker compose exec db bash -c 'printf "\nhost all all 10.0.0.0/8 scram-sha-256\nhost all all 172.16.0.0/12 scram-sha-256\nhost all all 192.168.0.0/16 scram-sha-256\nhost all all fc00::/7 scram-sha-256\n" >> "$PGDATA/pg_hba.conf"'
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_reload_conf();"
```

With current Compose, **do not** append to `$PGDATA/pg_hba.conf` — Postgres ignores it when `hba_file=/etc/oneirodex/pg_hba.conf` is set. Edit the host file `docker/postgres/pg_hba.conf` and `force-recreate db` instead.

Then restart the app container. Do **not** wipe `db_data` unless you intend to lose the library DB. Intentional clean slate (still logging in after a partial wipe): [unraid-deploy.md — Factory wipe](unraid-deploy.md#factory-wipe-still-logging-in-after-wiped-volumes).

### 3c. `password authentication failed` after changing `POSTGRES_PASSWORD`

**Log signature:** `FATAL: password authentication failed for user "postgres"` from the app (or from a client on the host), right after `.env` was edited or a new `.env` was copied from a template.

**Cause:** `POSTGRES_PASSWORD` is read only when Postgres first creates the `db_data` volume. The database keeps the password it was initialised with; the app now sends the new one.

**Fix (keep the data):** either put the old value back in `.env`, or set the database to the new value. Both steps are in [docker-compose-deploy.md § Rotating the password](docker-compose-deploy.md#rotating-the-password-on-an-existing-database): `\password` inside `psql` (the in-container socket is trusted, no old password needed), then `docker compose up -d --force-recreate app`. Wiping `db_data` also clears the error but destroys the library database — see [unraid-deploy.md — Factory wipe](unraid-deploy.md#factory-wipe-still-logging-in-after-wiped-volumes) only if that is intended.

### 4. Database URL points at production during tests

Only relevant for pytest: `TEST_DATABASE_URL` must contain `test` in the database name.

### 5. Port conflict

Default host port `5006`. Change the published port mapping if occupied.

### 6. Read-only rootfs / missing library volume

If `/app/oneirodex/static/library` is not writable, theme install and image downloads fail (may still boot). Mount a writable appdata path.

### 7. `nvml error: driver not loaded` (GPU reservation on a host with no GPU)

Whole-stack symptom, single-service cause. The create fails with:

```text
error running prestart hook #0: exit status 1, stderr: Auto-detected mode as 'legacy'
nvidia-container-cli: initialization error: nvml error: driver not loaded
```

Only the optional `sdnext` artwork sidecar ever asks for a GPU, but the failed
create aborts the whole `compose up` / stack update, so it reads as "Oneirodex
is broken" when the app container is fine.

Despite naming a driver, this is almost always a **placement** error rather than
a driver one: a GPU reservation reached a host that has no NVIDIA GPU. Confirm
which it is before touching drivers — on the *deploy* host, not your
workstation:

```bash
nvidia-smi -L || lspci | grep -i nvidia
```

No output means there is no GPU to reserve, and no driver work will help.

| Check | Fix |
|---|---|
| Does the host have a working NVIDIA driver? `nvidia-smi` on the host, then `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` | If either fails, the host cannot serve a GPU — do not request one |
| Is `COMPOSE_FILE` pulling in `docker-compose.gpu.yml`? | Remove it from `.env`. That overlay is opt-in and only for hosts that pass the check above |
| Does your deployed stack file carry its own `deploy: … driver: nvidia` or `runtime: nvidia`? | Delete it. `docker-compose.yml` never requests a GPU; a copy edited on the host may |
| Unraid after an OS upgrade | The Nvidia Driver plugin must be reinstalled for the new kernel and the box rebooted — until then `nvidia-smi` fails and so will every GPU container |

Unraid Compose Manager’s working dir **is** this checkout (not a separate `isos` copy). Check the live tree, including the Windows GPU override:

```bash
STACK=/mnt/user/example-share/_projects/Oneirodex
grep -n -A6 reservations "$STACK/docker-compose.yml" "$STACK/docker-compose.override.yml"
grep -n COMPOSE_FILE "$STACK/.env"
```

The sidecar runs on **CPU** with no reservation at all — slow, not broken. If the
GPU is on a different machine, do not start the profile here: run
[`docker-compose.artwork-local.yml`](../../docker-compose.artwork-local.yml) on
the GPU PC ([artwork-gpu-workstation.md](artwork-gpu-workstation.md)) and set
`AI_ARTWORK_URL=http://<gpu-host>:7860`.

### 8. Healthcheck names a binary the image does not ship

**Signature:** the service answers requests normally but never leaves
`unhealthy`. The health log shows the probe itself failing to launch:

```text
OCI runtime exec failed: exec: "curl": executable file not found in $PATH
```

```bash
docker inspect <container> --format '{{json .State.Health}}'
```

An `ExitCode` of `-1` means the probe never ran — this is not the service
failing. Check what the image actually has before writing a probe:
`saladtechnologies/sdnext` ships `wget` and no `curl`, which is why the artwork
sidecar's healthcheck uses `wget`.

### 9. `docker compose build` fails in `frontend-build` (`tsc --noEmit`)

**Log signature:** hundreds of `TS6142` / `jsx is not set` / `Cannot find name 'Map'` under `npm run build --workspace=member-app`, often with `Cannot read file '/build/tsconfig.base.json'`.

**Cause:** the SPA tsconfigs `extends` repo-root `tsconfig.base.json`. The `frontend-build` stage must `COPY tsconfig.base.json` before the workspace builds.

**Fix:** pull a tree whose Dockerfile stages that file, then `docker compose … up -d --build` again. Local `npm run build` can still pass when the file exists on the host — only the image stage was blind.

### 10. `livekit` exits: `one of key-file or keys must be provided`

**Cause:** the SFU no longer runs in `--dev` mode with a built-in `devkey` / `secret`. It reads `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` from `.env`, and refuses to start when either is empty (or is a number-only secret that LiveKit's YAML parser drops). Only the optional `livekit` profile is affected; the app, db and other profiles start normally.

**Fix:** generate a pair and recreate the SFU and the app — [livekit-unraid.md](livekit-unraid.md#compose-profile). `Could not parse keys` means the value holds a colon, `$`, `#` or a quote. Voice that connects but carries no audio means a hand-copied `livekit` service lost `--udp-port 7882` (see the upgrade section of that runbook).

## Collect for support

```text
docker logs <container> --tail 200
env | grep -E 'SECRET_KEY|DATABASE|DATA_FOLDER|POSTGRES'   # redact secrets
docker inspect <container> | grep -A20 Mounts
```
