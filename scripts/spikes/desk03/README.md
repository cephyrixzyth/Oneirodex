# DESK-03 standalone spike (P05)

Isolated proof code for the standalone / household-server decision
([ADR 0011](../../../docs/adr/0011-standalone-bundled-postgres.md)). Nothing in
`oneirodex/` imports these files; they are kept so the proof can be re-run.

| File | What it proves |
|---|---|
| `household_move.py` | Moving a standalone PostgreSQL install to a household server: identity manifest (per-table digests with machine paths made relative to named roots; game UUID, entitlement, match-decision and save digests), save-file checksums, bundle integrity check, one-transaction path remap, row-for-row verification. |
| `seed_standalone.py` | Synthetic representative data (users, library, games with two artwork kinds, saves with real files, entitlements and decisions). Refuses any database whose name lacks `test` / `standalone`. |
| `run_proof_c.sh` | End-to-end move plus five rollback rehearsals in throwaway PostgreSQL 17 containers on an `--internal` network. Exit 0 only if every check passes; a rehearsal passes only on a clean refusal (exit 1), never on a crash. |
| `run_proof_d.sh`, `proof_d/` | DESK-04: the real standalone launcher (`python -m oneirodex_standalone`) with a relocated PostgreSQL 17 bundle, offline, as `nobody`, with the whole install read-only. Checks first-run health, collation, state-file permissions, runtime files (themes, icon packs, fonts) in the data folder and served from it, database crash restart, clean stop, second start, and that no secret reaches a log. |

| `run_proof_e.sh`, `proof_e/` | DESK-05: the supported move command (`oneirodex_standalone/move.py`, which supersedes `household_move.py`). A real standalone install with Windows-style game paths and encrypted saves is exported, then imported into an empty database on a separate PostgreSQL 17 server with another `SECRET_KEY`. The proof checks paths, re-encrypted saves and carried files, and that the real server starts on the result. Every refusal must exit 1 and change nothing: export while running, a used move folder, wrong folder names, no server key, a non-empty target, a file conflict, a tampered folder and a repeat import. |

```bash
bash scripts/spikes/desk03/run_proof_c.sh
bash scripts/spikes/desk03/run_proof_d.sh
bash scripts/spikes/desk03/run_proof_e.sh
```

Proof D's start-up time is not representative on Windows: the app is read from
a folder mounted into Docker, where every file read is slow.

Requirements: Docker with the `postgres:17.6` and `oneirodex:p04-tests` images
(the latter is the Python 3.12 test image with the app's dependencies). Output
and evidence go to `.artifacts/p05/proof-c/` (git-ignored). The live `.env` is
masked by an empty file; no network access is used.

The move sequence the proof validates (app stopped on both ends):

1. `snapshot` the standalone database and save roots.
2. `pg_dump -Fc` into the bundle; `pack` records the dump and file checksums.
3. On the server: `check-bundle` before touching anything.
4. `pg_restore --single-transaction --exit-on-error` into an empty database.
5. `unpack-files`, then `remap` path prefixes in one transaction.
6. `verify` — tables, identity digests, paths outside roots, sequences, files.
7. Rollback at any point is dropping the target database; the source is never
   written (checked by re-snapshotting it).

Spike limits: path columns are the audited three plus any text column named
`*path*` / `*folder*`; artwork under `static/library/images` is not bundled
(re-downloadable except generated art — see the ADR); encrypted saves need
their key moved with them; user IDs are preserved as-is (a move into an
existing multi-member server would need ID remapping, which this does not do).
