# Ops scripts

One-shot **operational** tooling for the live Unraid host — rebuilds, smoke checks,
scan seeding, env patching. These are not part of the app and nothing in the
runtime imports them.

They were previously `scripts/_unraid_*.py`, where an underscore prefix was the
only thing separating them from real repo tooling like `api_envelope_lint.py`.
Several of these touch a live host destructively; that is a poor reason to leave
them looking like scratch files.

## Read before running

Several of these act on the **live NAS**, not a test environment:

| Script | What it does to the host |
|---|---|
| `unraid_rebuild_and_reset.py` | Compose rebuild from the live NAS tree, then resets themes |
| `unraid_reset_themes.py` | Drops and reseeds default + preset themes in `oneirodex-app` |
| `unraid_ship_update_now.py` | Compose rebuild + themes reset + smoke, skipping git pull |
| `unraid_patch_env.py` | Merges product flags and OIDC config into the live `.env` — **see the warning below before running** |
| `unraid_scan_leaves*.py` | Creates leaf libraries and queues scans |
| `unraid_requeue_leaves.py` | Queues a `ScanJob` per household leaf |
| `unraid_enable_oidc_db.py` | Flips `GlobalSettings.oidc_enabled` on |

The rest are read-only diagnostics: `unraid_status_snapshot.py`,
`unraid_propose_dump.py`, `unraid_list_spa_dist.py`, `unraid_spa_mtime.py`,
`unraid_git_*.py`, `unraid_rebuild_preflight.py`, `unraid_post_rebuild_smoke.py`.

None of them write git config; the `unraid_git_*` helpers pass
`safe.directory` per invocation instead.

## `unraid_patch_env.py` — two defects fixed 2026-09-02

Both found during the sweep, both now fixed. Recorded because the second one
governs how *any* script here should touch the live `.env`.

**1. It no longer writes LiveKit config.** It used to upsert
`ENABLE_LIVEKIT=true` with `LIVEKIT_API_KEY=devkey` /
`LIVEKIT_API_SECRET=secret` and a LAN `ws://` URL. Those are not a leaked
secret — they are the keys the compose `livekit` service's `--dev` mode has
built in, and `.env.example` ships `devkey` too. The problem was posture: the
script pushed a dev configuration onto a live host, overriding
`.env.unraid.example`, which leaves `LIVEKIT_API_KEY` deliberately **blank**.
With the server on `--bind 0.0.0.0` and the port published on every interface,
anyone on the LAN reaching `:7880` could mint room tokens. Since 2026-09-30
the compose `livekit` service no longer runs `--dev`: it takes its keys from
`LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` and refuses to start without them
([livekit-unraid.md](../../docs/runbooks/livekit-unraid.md)). Setting those
keys is still an operator decision, not one a flags-merge script should make.

**2. The `.env` write is atomic.** It was `read_text` then `write_text` in
place: an interrupt between truncate and flush left a half-written file holding
`SECRET_KEY`, `OIDC_CLIENT_SECRET` and the database credentials, with no way
back. `write_atomic()` now copies the current file to `.env.bak` first, writes
a sibling temp file, `fsync`s it, and `os.replace`s it into position — atomic
on the same filesystem, Windows included. A failure anywhere leaves the
original untouched and cleans up the temp. `.env.bak` is gitignored.

**Any future script here that edits the live `.env` must use `write_atomic()`,
not `write_text()`.**

## Convention

If a script here stops matching how the host is actually deployed, delete it
rather than leaving it to rot — git history keeps it. A stale script that still
looks runnable is the failure mode this directory exists to prevent.

Related: [unraid-deploy runbook](../../docs/runbooks/unraid-deploy.md) ·
[themes reset](../../docs/admin/themes-reset.md)
