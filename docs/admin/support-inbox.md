# Support inbox (admins)

> **Doc status:** Active

Teammate reports land in-app and optionally on GitHub. Discord is not used.

## Member path

Members open **More → Report issue** (`/report`). Fields: title (required), symptom/body (optional), area, severity; **Context** (deploy, client, URL) and **Logs** stay collapsed until expanded.

Caps on create: symptom ≤2000 chars, logs ≤4000 chars. List payloads omit log blobs (`has_logs` + truncated `body` / `body_preview` + `empty`).

## Admin path

1. Open **`/admin/support`** (Users hub → Support inbox), or follow the in-app notification.
2. Review severity / area / GitHub link.
3. Mark **Resolve** when done.
4. Triage in Cursor with `@issue-assess`, implement with `@issue-fix` — [issue-assess-agent.md](../dev/issue-assess-agent.md).

## Env

| Variable | Purpose |
|---|---|
| `SUPPORT_GITHUB_TOKEN` | PAT with `issues:write`. If unset, ticket still saves; `github_sync=skipped`. |
| `SUPPORT_GITHUB_REPO` | Default `cephyrixzyth/oneirodex` |

## Admin alert prefs

Global settings: `admin_notify_support` (and related `admin_notify_*` for library events). User preference `notify_support` controls whether admins receive in-app rows.

## API

- `POST /api/support/tickets` — create (session + CSRF). `title` required; `body`/`symptom` and `logs` optional.
- `GET /api/support/tickets` — own tickets (members) / all (admin). Compact rows: `body` ≤280, `logs` null, `has_logs`, `empty`.
- `GET /api/support/tickets/<id>` — full ticket including logs.
- `POST /api/support/tickets/<id>/resolve` — admin

### Related member feeds (Wave 2c)

- `GET /api/notifications` — `{ notifications, unread_count, empty }`
- `GET /api/announcements` — `{ announcements, empty }` (+ `body_preview` per row)
- `GET /api/news/gaming` — `{ items, empty }` (never 500 on RSS failure)
- `GET /api/news/free-games` — `{ items, enabled, connected_stores, empty }`
