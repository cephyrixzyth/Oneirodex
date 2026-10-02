# Launcher import and sync-all

> **Doc status:** Active

Goal: a member can bring a library in from any launcher that can export one, and
refresh every linked store with one action. Everything stays **register-only**:
Oneirodex records *that a title is owned*; it never downloads, installs or reads
credentials.

## What exists

| Piece | Where |
|---|---|
| Format registry, sniffers, parsers | `oneirodex/utils/launcher_imports.py` (`FORMATS`) |
| Import route | `POST /api/imports/launcher` (multipart `file` or JSON; optional `launcher`) |
| Format list | `GET /api/imports/launchers` |
| Sync every linked store | `POST /api/ownership/sync-all` (`utils/store_sync_all.py`) |
| UI | Store connections: *Import … export* per source, *Sync all stores* |

Formats today: Playnite (JSON/CSV), Heroic, Lutris, GOG Galaxy (community JSON),
generic CSV. Rows are recorded under the launcher's own `store` key (`heroic`,
`lutris`, `galaxy`, `playnite`, `import`), so a launcher import can never collide
with a live store sync's ids. Heroic ids are namespaced `runner:app_name`
because app names are only unique per runner.

## Rules every importer follows

1. Go through `upsert_owned_title` — idempotent, keeps reviewed matches.
2. Never auto-link on a name alone; unmatched titles go to the review queue.
3. Fail with a member-safe sentence (`ValueError`), never exception text.
4. Cap size (`MAX_TITLES`) and id length (`EXTERNAL_APP_ID_MAX`).

## Adding a launcher

1. Write `_sniff_x(data)` and `_parse_x(data) -> list[ParsedTitle]`.
2. Add a `LauncherFormat` to `FORMATS` (specific sniffers before generic ones).
3. Add a row to `store_capabilities._DEFINITIONS` and `_FILE_IMPORT`.
4. Add a fixture and a detection test in `tests/test_launcher_imports.py`.

## Not done yet

- **Direct reads** of a launcher's own files (Heroic's config folder, Lutris's
  database, Galaxy's `galaxy-2.0.db`) rather than an export file — needs the
  desktop companion, since the server cannot see a member's PC.
- **Matching improvements** — launcher titles currently match only through the
  review queue; the matcher work (`docs/dev` matching notes) will feed it.
- Itch.io, Humble, EA, Ubisoft, Battle.net remain *unavailable* (no export we
  can read honestly).
