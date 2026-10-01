# Unraid Compose — checkout deployment

Use a dedicated checkout for your Unraid stack. All share names and paths below are examples; substitute your own operator configuration. Keep actual host paths and credentials out of public documentation.

| Role | Path |
|---|---|
| Unraid compose / env | `/mnt/user/example-share/_projects/Oneirodex` |
| Windows mapping | `Z:\_projects\Oneirodex` |
| Games scan root (RO) | `/mnt/user/example-share/_software/_games` |
| Library / uploads (RW) | `/mnt/cache/appdata/oneirodex/library` |

Full operator runbook: [docs/runbooks/unraid-deploy.md](docs/runbooks/unraid-deploy.md).

## Compose Manager

- External ENV File Path: `/mnt/user/example-share/_projects/Oneirodex/.env`
- Indirect Compose File: `/mnt/user/example-share/_projects/Oneirodex/docker-compose.yml`
- Indirect Path: leave empty

`.env` must **not** contain `DATABASE_URL=...@localhost...`. Compose builds the URL with host `db`. Prefer `.env.unraid.example` (or `.env.nas.example`) if you are creating `.env` from scratch — set `SECRET_KEY`, `DATA_FOLDER_GAMES`, and `LIBRARY_HOST_PATH`. Do not overwrite a live `.env`.

`docker-compose.override.yml` may contain local hardware overrides. On a host without the requested GPU: leave `--profile artwork` off, or set `COMPOSE_FILE=docker-compose.yml` in the Unraid `.env` if a stack update dies with `nvml error: driver not loaded`.

## Start / rebuild

```bash
cd /mnt/user/example-share/_projects/Oneirodex
docker compose down
docker compose up -d --build
docker compose exec app python -c "import os; from sqlalchemy.engine import make_url; u=make_url(os.environ['DATABASE_URL']); print('host:', u.host, 'database:', u.database)"
```

Expected: `...@db:5432/...` and `DATABASE_HOST=db`. Confirm readiness with `curl -f http://<unraid-ip>:5006/awake`.

## Network exposure defaults

Compose publishes only what the app needs on the LAN. After a `git pull` and `docker compose up -d` your existing `.env` still works, with these defaults:

| Service | Default | Opt in to wider access | Details |
|---|---|---|---|
| Postgres (`db`) | `127.0.0.1:5432`, private source ranges only in `pg_hba.conf` | `POSTGRES_HOST_BIND=<LAN IP>` | [docker-compose-deploy.md](docs/runbooks/docker-compose-deploy.md#postgres-exposure-and-password) |
| LiveKit (`--profile livekit`) | Production mode, keys from `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`, no built-in `devkey` | n/a (ports 7880/tcp, 7881/tcp, 7882/udp stay published for browsers) | [livekit-unraid.md](docs/runbooks/livekit-unraid.md) |
| SD.Next (`--profile artwork`, `docker-compose.artwork-local.yml`) | `127.0.0.1:7860` (it has no login) | `SDNEXT_HOST_BIND=<LAN IP>` | [artwork-gpu-workstation.md](docs/runbooks/artwork-gpu-workstation.md) |

Set a strong `POSTGRES_PASSWORD` in `.env` (the templates show how). Changing it on a stack that already has a `db_data` volume does not change the database: rotate it as described in the Postgres link above, or the app cannot log in.

## Frontend (member SPA)

The image build runs `frontend/member-app` (Vite) and copies the bundle into `/app/oneirodex/static/dist/member-app/`. After rebuild:

```bash
docker compose exec app test -f /app/oneirodex/static/dist/member-app/member-app.js && echo ok
```
