# Single-container install, Unraid Community Apps and Docker Hub

> **Doc status:** Active (submission steps are a checklist; nothing here has been submitted yet)

Oneirodex ships as **one image that carries its own PostgreSQL**. Without a
`DATABASE_URL` the container creates a cluster in `/config` on first start, generates
its database password and `SECRET_KEY`, and runs both processes. With a
`DATABASE_URL` (the Compose stack sets one) the embedded database is never started
and nothing changes.

| Install | File | Database |
|---|---|---|
| Unraid Community Apps / `docker run` | [`unraid/oneirodex.xml`](../../unraid/oneirodex.xml) | embedded, in `/config/pgdata` |
| Docker Compose, one container | [`docker-compose.single.yml`](../../docker-compose.single.yml) | embedded |
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

Embedded to the Compose stack: `pg_dump -Fc` from inside the container
(`docker exec oneirodex sh -c 'PGPASSWORD=$POSTGRES_PASSWORD pg_dump -h 127.0.0.1 -p 55432 -U oneirodex -Fc oneirodex' > oneirodex.dump`),
then `pg_restore` into an empty database on the server. Copy `/config/library` to the
server's library mount. The reverse works the same way. A standalone desktop install uses
[standalone-move.md](standalone-move.md) instead.

## Publishing the image

`.github/workflows/docker-publish.yml` builds `linux/amd64` + `linux/arm64` on every `v*` tag
(or by hand) and pushes to GHCR using the built-in token. To also push to Docker Hub, add the
repository variable `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN` (a Hub access token
with write scope). The template points at Docker Hub (`chrisjrovira/oneirodex`); change
`<Repository>` if you publish elsewhere.

Before the first public tag, work through [release-checklist.md](release-checklist.md) and
[scrub-shipped-bundles.md](scrub-shipped-bundles.md). Image layers must contain no BIOS,
firmware, keys or `.env`.

## Docker Hub listing

1. Create the public repository `chrisjrovira/oneirodex` on Docker Hub.
2. Short description: *The self-hosted game library for a household.* Paste the README as the
   full description (Hub does not sync it from GitHub on its own; a
   `peter-evans/dockerhub-description` step can be added later).
3. Tag at least `latest` and the version; the `org.opencontainers.image.*` labels in the
   Dockerfile carry source and revision.

## Unraid Community Apps submission

Community Apps reads templates from a **public** repository and needs a support thread.

1. Make the code repository public, or create a small public repo (for example
   `chrisjrovira/unraid-templates`) containing `oneirodex.xml` at its root. If the template
   moves, update `<TemplateURL>` and `<Icon>` to the new raw URLs. Both must resolve
   without authentication.
2. Confirm the image pulls anonymously: `docker pull chrisjrovira/oneirodex:latest` from a
   machine that is not logged in.
3. Install it on a real Unraid box through *Add Container* with the template URL and check:
   first-run wizard, a scan of the games share, `docker stop` leaves a clean log, and a
   restart keeps the library.
4. Open a support thread in the Unraid forum's Docker Containers section (CA requires one)
   and put its URL in `<Support>`.
5. Submit the repository through Community Apps' *Submit* form
   (<https://ca.unraid.net/> → *Submit an application*), then respond to moderator feedback.
   They check XML validity, an icon, an overview, category, working WebUI and that defaults
   do not expose secrets.
6. Keep `<Category>` to values from the Community Apps list and re-check it at submission;
   the categories change.

## Known gaps

- The first start needs the image's PostgreSQL major to match the cluster: an image that
  ships a newer major needs a `pg_upgrade` step that does not exist yet. Pin the Debian
  base when changing majors.
- `linux/arm64` is built but not exercised on real hardware.
- Optional sidecars (LiveKit, ClamAV, challenge solver) are Compose profiles only; the
  template does not start them. Point the matching env vars at external services.
