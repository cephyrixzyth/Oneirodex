# Single-container install, Unraid Community Apps and Docker Hub

> **Doc status:** Active (public CA template and a real Unraid installation are in use; release-sync automation requires a repository token)

Oneirodex ships as **one image that carries its own PostgreSQL**. Without a
`DATABASE_URL` the container creates a cluster in `/config` on first start, generates
its database password and `SECRET_KEY`, and runs both processes. With a
`DATABASE_URL` (the Compose stack sets one) the embedded database is never started
and nothing changes.

| Install | File | Database |
|---|---|---|
| Unraid Community Apps / `docker run` | [`unraid/oneirodex.xml`](../../unraid/oneirodex.xml) | embedded, in `/config/pgdata` |
| Docker Compose, one container | [`docker-compose.single.yml`](../../docker-compose.single.yml) | embedded; use `APPDATA_PATH` for persistent `/config` and `APP_ENV_FILE` to retain app settings |
| Docker Compose, two containers (existing stacks) | [`docker-compose.yml`](../../docker-compose.yml) | separate `postgres:17.6` service |

## How the embedded database behaves

- Mode `ONEIRODEX_EMBEDDED_DB`: `auto` (default: embedded when neither `DATABASE_URL` nor
  `DATABASE_HOST` is set), `true`, `false`.
- Listens on `127.0.0.1:55432` inside the container only (`ONEIRODEX_EMBEDDED_DB_PORT`), scram
  auth, no unix socket. Nothing is published, so it is unreachable from the LAN.
- Runs as `PUID:PGID` (default `99:100`, Unraid's nobody:users); PostgreSQL refuses root.
- Same collation as the standalone install ([ADR 0011](../adr/0011-standalone-bundled-postgres.md)),
  so `pg_dump` moves cleanly to a Compose server later.
- `docker stop` stops the app first and PostgreSQL second (set `stop_grace_period: 60s` or more).
  If PostgreSQL dies, the container exits and the restart policy brings it back.
- Layout under `/config`: `pgdata/`, `secrets/` (0600), `logs/postgres.log`, `library/`
  (themes, covers, saves). Mounting a separate folder at `/app/oneirodex/static/library`
  still wins, which keeps a Compose-style layout working.

**Back up `/config`** (stop the container first, or use Unraid's appdata backup plugin
with the container stopped). Losing `secrets/` makes the database unreadable.

## Moving between modes

### Move a two-container Compose install to one container

The migration copies PostgreSQL data; it does not remove the source volume. Keep the old
database container stopped until the embedded app has passed `/awake` and a sign-in check.

1. Back up the source database and validate the archive:

   ```sh
   docker exec oneirodex-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > oneirodex.dump
   docker exec -i oneirodex-db pg_restore --list < oneirodex.dump >/dev/null
   ```

2. Choose durable paths in `.env`: `COMPOSE_FILE=docker-compose.single.yml`,
   `APPDATA_PATH=/path/to/appdata/oneirodex/config`, `APP_ENV_FILE=/path/to/appdata/oneirodex/config/runtime.env`,
   and keep the existing `DATA_FOLDER_GAMES`, `LIBRARY_HOST_PATH`,
   `WEBRETRO_CORES_HOST_PATH`, and `EMULATORJS_HOST_PATH`. `APP_ENV_FILE` should contain
   the app's current settings with external database keys (`DATABASE_URL`, `DATABASE_HOST`,
   `DATABASE_PORT`, `POSTGRES_USER`, and `POSTGRES_PASSWORD`) removed. Protect it as a
   secrets file. The single-container Compose file forces embedded mode and supplies the
   container paths.

3. Build the image, then start a temporary maintenance container that initializes
   PostgreSQL without starting the web app:

   ```sh
   docker compose build oneirodex
   docker run -d --name oneirodex-db-migrate \
     -e ONEIRODEX_EMBEDDED_DB=true -e POSTGRES_DB=oneirodex -e PUID=99 -e PGID=100 \
     -v "$APPDATA_PATH:/config" --entrypoint /bin/bash "$(docker compose images -q oneirodex)" \
     -c 'source /app/docker/embedded-db.sh; start_embedded_db; trap stop_embedded_db EXIT; sleep infinity'
   ```

4. Restore into the empty `oneirodex` database and stop the maintenance container:

   ```sh
   docker exec -i oneirodex-db-migrate bash -c \
     'export PGPASSWORD="$(cat /config/secrets/db_password)"; pg_restore --no-owner --no-acl --role=oneirodex --single-transaction -h 127.0.0.1 -p 55432 -U oneirodex -d oneirodex' < oneirodex.dump
   docker stop -t 60 oneirodex-db-migrate
   docker rm oneirodex-db-migrate
   ```

5. Start the app with the single-container file. Confirm `/awake`, `/login`, and the
   Alembic version, then stop the old `oneirodex-db` container. Keep its named volume
   and the dump until the new install has been used successfully.

The embedded cluster and generated secrets live under `/config`; back up that directory
with the app stopped. Keep the separate library bind mount pointed at its existing host
path so covers, themes, and uploads remain in place. A standalone desktop install uses
[standalone-move.md](standalone-move.md) instead.

## Publishing the image

`.github/workflows/docker-publish.yml` builds `linux/amd64` + `linux/arm64` on every `v*` tag
or when manually run from `main`, then pushes to GHCR using the built-in token. Manual runs
from other refs do not publish. To also push to Docker Hub, set the
repository variable `DOCKERHUB_USERNAME=cephyrixzyth` and the `DOCKERHUB_TOKEN` secret in the
GitHub Actions environment named `DOCKERHUB`. The secret must be a Docker Hub access token with
write scope. The workflow publish job selects that environment and pushes to Hub when both
settings exist. Do not paste the token into the repository or chat. The template points at
`cephyrixzyth/oneirodex`; change `<Repository>` if you publish elsewhere.

Before the first public tag, work through [release-checklist.md](release-checklist.md) and
[scrub-shipped-bundles.md](scrub-shipped-bundles.md). Image layers must contain no BIOS,
firmware, keys or `.env`.

## Docker Hub listing

1. Create the public repository `cephyrixzyth/oneirodex` on Docker Hub.
2. Short description: *The self-hosted game library for a household.* Paste the README as the
   full description (Hub does not sync it from GitHub on its own; a
   `peter-evans/dockerhub-description` step can be added later).
3. After the GitHub Actions variable and secret are set, run **Actions → Docker publish → Run
   workflow** from `main` to publish `latest`, or publish a `v*` tag to publish the version and
   `latest`. The workflow builds `linux/amd64` and `linux/arm64`; the
   `org.opencontainers.image.*` labels carry source and revision. Confirm `latest` is public
   and can be pulled without logging in before submitting the CA template.

## Unraid Community Apps listing

The public template repository is [cephyrixzyth/unraid-templates](https://github.com/cephyrixzyth/unraid-templates).
Its nested `oneirodex/oneirodex.xml` is the catalog entry and has been used to install Oneirodex
on a real Unraid server. The application monorepo also contains Android resource XML files, so
the Community Apps scanner consumes the dedicated template repository rather than this repo.
The source copy is [`unraid/oneirodex.xml`](../../unraid/oneirodex.xml); keep the raw
`TemplateURL`, image repository, WebUI port and volume mappings aligned between both copies.

### Keep CA installs current

Unraid tracks the Docker image digest for the installed repository and tag. Oneirodex's CA
template uses `cephyrixzyth/oneirodex:latest`; each stable version tag publishes a new
multi-architecture image and advances `latest`. The template feed separately carries install
defaults and app metadata, so release automation copies `unraid/oneirodex.xml` into the public
template repository and stamps its overview with the release version. The app
derives `IMAGE_SAVE_PATH` as `<ONEIRODEX_LIBRARY_DIR>/images` (default
`/config/library/images`) from the persistent library mount; do not point it at
the read-only `/storage` games share. Optional `ENABLE_AI_ARTWORK`,
`AI_ARTWORK_URL`, and `AI_ARTWORK_ENGINE` fields connect a trusted LAN Forge or
A1111-compatible workstation. AI artwork remains off unless explicitly enabled.

The GitHub Actions repository secret `UNRAID_TEMPLATES_TOKEN` should be a fine-grained token
restricted to `cephyrixzyth/unraid-templates` with Contents read/write access. A release succeeds
without it when the public CA feed already matches; if the release changes the template, the sync
job fails until the token is configured. For an installed app, run Unraid's Docker image update check / update action after the
new `latest` digest is available. Refreshing or reinstalling the CA template alone does not pull
the image.

## Known gaps

- The first start needs the image's PostgreSQL major to match the cluster: an image that
  ships a newer major needs a `pg_upgrade` step that does not exist yet. Pin the Debian
  base when changing majors.
- `linux/arm64` is built but not exercised on real hardware.
- The Community Apps template starts only Oneirodex. Optional sidecars are separate
  services: ClamAV and TRAWL can join a private Docker network; TRAWL/J4125 setup is in
  [challenge-solver-unraid.md](challenge-solver-unraid.md). Keep the solver disabled until
  an admin opts into private-LAN URL access. LiveKit remains an independently configured
  Compose service and requires real credentials plus media-port planning.
