# Architecture decision records

> **Doc status:** Active

One file per decision, numbered in the order they were taken. A superseded
record keeps its number and gains a **Superseded** header pointing forward; it
is never rewritten. Historical entries keep the former product string where
they used it — do not scrub them.

| # | Decision | Status |
|---|---|---|
| [0001](0001-schema-migrations-defer-alembic.md) | Defer Alembic before 1.0; keep `updateschema.py` | Superseded by 0004 |
| [0002](0002-defer-api-client-spa.md) | Defer `@oneirodex/api-client` in the member SPA | Superseded by 0005 |
| [0003](0003-product-name-oneirodex.md) | Product name: Oneirodex | Accepted — clean break finished |
| [0004](0004-adopt-alembic.md) | Adopt Alembic with a squashed baseline; freeze `updateschema.py` | Accepted |
| [0005](0005-api-client-is-the-requester.md) | `@oneirodex/api-client` is the one requester (Bearer + browser transports) | Accepted |
| [0006](0006-asgi-bridge-a2wsgi.md) | Flask behind uvicorn, bridged by a2wsgi; static and SSE bypass the bridge | Accepted |
| [0007](0007-four-frontends-one-shared-package.md) | Three React SPAs + `@oneirodex/ui` over a Jinja admin hybrid | Accepted |
| [0008](0008-npm-workspaces-single-lockfile.md) | npm workspaces, one root lockfile (C:-worktree rule on SMB) | Accepted |
| [0009](0009-api-envelope.md) | One JSON envelope — `api_ok` / `api_error`, eleven documented keeps | Accepted |
| [0010](0010-pydantic-request-validation.md) | pydantic `@validate_body`, `extra='forbid'`, semantic checks stay in the view | Accepted |
| [0011](0011-standalone-bundled-postgres.md) | Standalone installs bundle a user-space PostgreSQL; SQLite is not offered | Accepted |
| [0012](0012-evaluate-mariadb-before-engine-change.md) | Evaluate MariaDB before changing database support | Proposed |

**Still frozen on purpose:** `oneirodex/updateschema.py` (1,700 lines) carries
pre-Alembic installs to the baseline and takes no new columns — see 0004. Its
size is not a cleanup target.

New record: copy the header block from 0005 (`Date`, `Status`, `Owners`,
optional `Supersedes`), then Context → Decision → Consequences (pros/cons
table) → Related.
