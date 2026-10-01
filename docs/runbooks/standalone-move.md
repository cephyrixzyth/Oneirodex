# Move a standalone install to a household server

For people who started with the standalone app on a laptop or desktop and now
want Oneirodex on an always-on box: Docker Compose, Unraid or a NAS. The move
takes the database and your members' files with it, checks them before
anything is restored, and verifies the result row for row. The standalone
install is never changed, so you can keep using it until you are happy.

Design and evidence: [ADR 0011](../adr/0011-standalone-bundled-postgres.md).

## What moves

| Moves | Stays behind |
|---|---|
| Everything in the database: members, libraries, games, matches, store entitlements, play history, settings | Game files themselves. They stay where they are; tell the move where they live on the server (`--root`, below) |
| Artwork, generated cover packs, saves (encrypted ones are re-encrypted for the server), chat uploads, custom emoji, mods, cheats, assists, uploaded themes | The default theme, colour presets, icon packs, fonts and caches: the server rebuilds them on start |
| | BIOS files: copy them to the server's BIOS folder yourself ([emulator-bios.md](emulator-bios.md)) |

## Before you start

- The server is set up and has started once (so its `db` service exists), with
  a server image that includes the PostgreSQL 17 client (`pg_restore`). Images
  built before the move command shipped do not have it: see **Troubleshooting**.
- Know where each games folder is on both machines. On the standalone machine
  it might be `D:\Games`; in the server's app container it is `/storage`
  (`DATA_FOLDER_GAMES` in `docker-compose.yml`).

## 1. Export on the standalone machine

Quit Oneirodex, then run from the install folder:

```bash
python -m oneirodex_standalone export --pg-home <bundled-postgres> --to <move-folder> --root games=D:\Games
```

- `--to` must be a new or empty folder. A failed export leaves nothing behind.
- `--root NAME=PATH` names a folder whose paths should move. Repeat it for each
  games folder. Paths under your Oneirodex data folder are handled for you.
- The export ends with a note if some paths are outside every folder you named.
  Those keep their old value on the server; name their folder too, or rescan
  afterwards. It also notes BIOS files, which are not carried.
- While Oneirodex is running, the export refuses to start.

The export prints a **fingerprint**, 64 characters long. Write it down or copy
it somewhere other than the move folder, because the import asks for it.

## 2. Copy the move folder to the server

Put it next to `docker-compose.yml`, for example as `./move`, over a share or
a USB drive. The import checks every file against the manifest, so a partial
copy is refused rather than half-restored.

The fingerprint is what makes the folder trustworthy on the server. Restoring
a database runs its contents on the server. So a folder someone changed along
the way, even with every checksum inside rewritten to match, is refused unless
its fingerprint is the one your export printed.

The check is repeated at the moment of use. The import copies `db.dump` into a
private temporary folder, hashing it as it writes, and runs `pg_restore` on that
copy, never on the path in the move folder. A dump swapped on the share after the
folder was checked (or a `db.dump` that is a symbolic link) is refused with
`db.dump changed in the move folder while it was being copied`, before the
database is touched. The copy needs free space equal to the dump in the server's
temporary folder, and is removed when the import ends.

The folder holds your members' data (password hashes, settings and API keys
included), their saves and, if any saves are encrypted, the key that opens
them. It is created readable only by you. Keep it private and delete it once
the move is done.

## 3. Create an empty database for the move

```bash
docker compose exec db createdb -U postgres oneirodex_moved
```

Use your `POSTGRES_USER` if it is not `postgres`. The import only restores
into an empty database. It never writes over the one the server is using now.

## 4. Import

```bash
docker compose run --rm --no-deps -v ./move:/move:ro \
  -e DATABASE_URL=postgresql://postgres:<POSTGRES_PASSWORD>@db:5432/oneirodex_moved \
  --entrypoint python app -m oneirodex_standalone import /move --expect <fingerprint> --root games=/storage
```

- `--expect` is the fingerprint from step 1. The first 16 characters are enough.
- Give `--root` once for every folder named at export, with its path on the server.
- The target database comes only from `DATABASE_URL`. There is no command-line
  option for it, so the password stays out of your shell history.
- The server's own `SECRET_KEY` comes from the app container's environment. It
  is used to re-encrypt encrypted saves.
- Files go into the server's library folder (`LIBRARY_HOST_PATH`). If a file
  with the same name and different content is already there, the import stops
  before anything is written.

The import:

1. checks the move folder, the target and the schema version before changing
   anything (a folder from a newer Oneirodex is refused: update the server first);
2. restores the database in one transaction;
3. copies the files, checking each as it is copied;
4. rewrites machine paths in one transaction, including Windows `\` to `/`;
5. re-encrypts encrypted saves;
6. verifies every table, the game, entitlement, decision and save identities,
   and every file.

It ends with `imported and verified`. Otherwise it prints the problems it
found and exits with status 1. If that happens after the restore, the files it
added are removed again, and you drop the target database (see **Rolling back**).

## 5. Switch the server over

Set `POSTGRES_DB=oneirodex_moved` in the server's `.env`, then:

```bash
docker compose up -d
```

Sign in with your standalone account. Everyone signs in again, because the
server has its own `SECRET_KEY`. If games live somewhere you did not name
with `--root`, run a scan.

## Rolling back

Nothing was changed on the standalone machine, and the server's previous
database is still there. To undo, set `POSTGRES_DB` back, restart, and drop the
moved database:

```bash
docker compose exec db dropdb -U postgres oneirodex_moved
```

To try again, for example with a corrected `--root`, create the empty database
again (step 3) and rerun the import. It accepts the files an earlier run of
the same move left in the library, re-encrypted saves included. They are listed
in `<move-folder>/manifest.json` (`files`) if you would rather remove them.

## Exit status and messages

| Status | Meaning |
|---|---|
| 0 | Moved and verified (`imported and verified …`) |
| 1 | `REFUSED: …`: a check failed. Before the restore, nothing was changed. After it, the files it added were removed; drop the target database as above |
| 2 | `usage: …`: the command line was wrong (a missing `--expect`, a malformed `--root`, no `DATABASE_URL`) |

## Troubleshooting

| Message | Fix |
|---|---|
| `Oneirodex is running: stop it, then export` | Quit the standalone app (check the tray) and retry |
| `the target database is not empty` | Import into a new database (step 3), not the one the server uses |
| `--root must name exactly the folders named at export` | Give one `--root` per folder you named at export, no more |
| `encrypted saves need the server's SECRET_KEY` | Run the import through `docker compose run … app` so it gets the server's environment |
| `pg_restore not found` / `pg_restore did not run` | Older server image without the PostgreSQL 17 client. Copy the standalone's Linux PostgreSQL bundle to the server and pass `--pg-bin <bundle>/usr/lib/postgresql/17/bin`; the import finds the bundle's libraries itself |
| `move folder incomplete or altered` | Copy the folder again; something was lost or changed on the way |
| `does not match the fingerprint from export` | The folder is not the one you exported, or it was changed. Export again and copy the new folder |
| `comes from a newer Oneirodex` | Update the server's image, then import |
| `… is marked encrypted but does not open` (export) | That one save is damaged. Remove or replace it in the standalone app, then export again |
| `--root must name a folder` | Name the games folder itself, not a whole drive or `/` |

The whole flow, every refusal above included, is exercised by
`scripts/spikes/desk03/run_proof_e.sh`.
