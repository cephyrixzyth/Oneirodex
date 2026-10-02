# ADR 0011: Standalone installs bundle a user-space PostgreSQL; SQLite is not offered

**Date:** 2026-09-30
**Status:** Accepted — 2026-09-30, on the human design review (H-STANDALONE: the owner asked for the option that casts the widest net for users). The rollout is separate work.
**Owners:** `agent-platform` (decision), `agent-backend` / `agent-desktop` (follow-up)
**Evidence:** DESK-03 spike, `scripts/spikes/desk03/` (proof C is re-runnable); measured runs recorded in the private P05 evidence note.

## Context

Oneirodex needs a way to run on one machine without a NAS, and a safe way to move
that install to a household server later without losing game identity, member
entitlements and match decisions, saves or library paths.

Today there are two paths, and both are heavy for one person on one computer:
the Compose stack (Docker Desktop on Windows/macOS) and the native installers
(`install-*.sh`, `install-windows.ps1`), which require a system-wide PostgreSQL 17
installed with administrator rights and running as a service.

The earlier proposal (`docs/strategy/db-engine-and-cache-2026-09.md`) suggested
SQLite for a zero-footprint box and noted that a full audit was needed. The spike
did that audit and ran the options.

## What was measured

| | SQLite file (proof A) | Bundled PostgreSQL 17 in user space (proof B) |
|---|---|---|
| Runs today | **No.** `alembic upgrade head` fails at the baseline revision (`ALTER COLUMN … SET DEFAULT`) and leaves 76 tables half-built; boot runs the frozen Postgres DDL in `updateschema.py`; `create_app` waits **122.7 s** on a Postgres port check first | **Yes.** Unmodified app image reached `/pulse` and `/awake` 200 with migrations at head (`a7c1d9e2f3b4`) on an offline network |
| Silent schema drift | 7 partial unique indexes lose their `WHERE` on SQLite: **one image per game** in total | None — one dialect |
| Postgres-only code paths | Library browse fails (`no such function: regexp_replace`); discover impressions use `ON CONFLICT` from the Postgres dialect; `TRUNCATE … RESTART IDENTITY` in system reset | None |
| Row locks | 5 `with_for_update()` sites become silent no-ops, including the LIB-04 sync fence and ownership review | Unchanged |
| 8 concurrent writers, read-modify-write, 20 s | **Lost updates:** 1,556 of 1,710 (default), 3,681 of 4,307 (WAL). Only `BEGIN IMMEDIATE` on every transaction lost none, serialising all writes (worst latency 3.3 s) | **0 lost updates** (row lock); mixed load p99 151 ms, worst 238 ms |
| Footprint | None beyond the file | ~71 MB server bundle uncompressed (~31 MB of it ICU data); data directory ~47 MB after first start; idle memory ~27 MB PSS |
| Start-up | — | `initdb` 2.5–3.4 s once; server start 0.12 s, stop 0.10 s; no administrator rights, no service, any user ID |
| Crash | — | Recovered from a clean stop and from `kill -9` (WAL redo); app readiness back to 200 within seconds |
| Move to a household server | Needs a new cross-dialect copier (type coercion, sequences, constraints) | `pg_dump -Fc` 0.17 s / `pg_restore --single-transaction` 1.0 s for the test database |

The code paths also rule out SQLite as a default: about 12–14 background writer
threads plus scan and image pools write while requests are served.

## Decision

Widest net first: every existing way in stays — the Docker Compose stack for a NAS or Unraid box, the native installers for people who already run PostgreSQL — and a standalone install is added for everyone else.


**A standalone install runs the normal Python server against a PostgreSQL 17
server bundled with it, started in user space inside the install's data folder.**

- No system service and no administrator rights: the launcher runs `initdb` on
  first start, then `pg_ctl` start/stop around the app. The server listens on
  localhost (or a Unix socket) only, with a generated password kept beside the
  data. The password, the secret key and the `initdb` password file are created
  owner-only (`0600`, `O_EXCL`) in one call, never written and then `chmod`-ed,
  and a data folder the launcher creates is `0700` on POSIX.
- One dialect for every install. Migrations, tests, row locks and the LIB-04
  sync fence behave the same on a laptop and on a NAS.
- **SQLite is not offered as an engine.** Supporting it would mean a second
  dialect in every migration and query, a second test matrix (the test harness
  is PostgreSQL-only today), and giving up row-lock guarantees the app relies on.
- **Moving to a household server** is `pg_dump -Fc` → `pg_restore
  --single-transaction` into an empty database, plus the DESK-03 move tool. The
  tool checks the bundle before anything is restored, remaps machine paths in one
  transaction, and verifies the target row for row: per-table digests, game UUIDs,
  entitlements, match decisions, saves, file checksums and sequences. Rolling back
  is dropping the target; the source is never written. Proof C ran this end to end
  with five rollback rehearsals, and all passed.

## Consequences

| Good | Costs and open work |
|---|---|
| Same engine, migrations and guarantees everywhere; no dialect branches in product code | ~71 MB larger download (less if built without ICU — an inference, not measured) |
| No admin rights or services; a data folder you can back up or delete | The launcher must supervise a second process: start, stop, crash restart, port choice |
| The move to a household server uses PostgreSQL's own tools plus verification | Windows and macOS server binaries were **not** measured. Only Linux was; EDB portable archives or a custom build are the candidates |
| Offline start works; outbound features degrade to warnings | Dumps move between operating systems: create standalone clusters with an OS-independent collation (e.g. PostgreSQL 17 `builtin` provider, `C.UTF-8`) so indexes stay valid on the server. **To be verified** |

Also required before rollout, and not done by the spike:

- ~~`create_app` should skip the PostgreSQL port check when the URL has no host.~~
  Done in DESK-04: it probes the port the URL names and skips a URL with no host.
- ~~Everything the server writes must live in the data folder, not the install.~~
  Done in DESK-04: `ONEIRODEX_LIBRARY_DIR` moves `static/library` (themes, icon
  packs, artwork, saves, fonts, caches) and is still served at `/static/library/`.
  Proof D runs the whole install read-only.
- ~~Generated artwork and encrypted-save keys must travel with the bundle.~~
  Done in DESK-05: `python -m oneirodex_standalone export` / `import`
  ([runbook](../runbooks/standalone-move.md)) carries members' files and
  re-encrypts saves for the server's own key instead of moving `SECRET_KEY`.
  Windows paths become the server's. Proof E runs it end to end with every refusal.
- The move tool refuses non-empty targets. Merging two installs, which would need member ID remapping, is out of scope.

## Related

- DESK-03 spike: `scripts/spikes/desk03/README.md`
- Earlier proposal (SQLite / MariaDB / bundled Redis): `docs/strategy/db-engine-and-cache-2026-09.md`
- ADR 0004 (Alembic; `updateschema.py` frozen)
- Desktop companion: `clients/desktop` is a thin client today, with no sidecar (`externalBin`). A Tauri sidecar is one way to ship the launcher.
