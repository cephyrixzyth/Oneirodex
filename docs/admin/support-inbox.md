# Support inbox (admins)

> **Doc status:** Active

Teammate reports land in-app. GitHub sync is opt-in on each report. Discord is not used.

## Member path

Members open **More → Report issue** (`/report`). Fields: title (required), symptom/body (optional), area, severity; **Context** (deploy, client, URL) and **Logs** stay collapsed until expanded. Reports stay on this server unless the member checks **Also send this report to GitHub**, selects **Preview GitHub report**, reviews the destination and redacted text, then submits. The external text includes report details, context, optional logs, reporter ID, role and a report reference. Preview does not save a ticket or contact GitHub.

Caps on create: symptom ≤2000 chars, logs ≤4000 chars. List payloads omit log blobs (`has_logs` + truncated `body` / `body_preview` + `empty`).

External titles and bodies are always filtered at the shared GitHub sender. Recognized credentials, private-key blocks, email addresses and home-directory paths are removed; URL queries and fragments are removed as a whole, which can also hide useful diagnostics. Local ticket text is preserved. Automatic filtering cannot recognize every private detail in prose; edit the report or keep it local. There is no raw override.

The preview names the validated owner/repository. Repository visibility is **unknown**; treat the report as potentially public. Configuration availability does not establish provider reachability or write permission. A missing token or invalid repository keeps forwarding unavailable while local-only submission stays usable. Approval expires after 15 minutes and is bound to the signed-in account, normalized contents, report reference and configuration; edits, account changes or configuration changes require another preview. Clients that previously sent only `sync_to_github=true` must obtain preview approval first. Delivery/retry and duplicate-request qualification remain open review work.

## Admin path

1. Open **`/admin/support`** (Users hub → Support inbox), or follow the in-app notification.
2. Review severity / area / GitHub link.
3. Mark **Resolve** when done.
4. Triage in Cursor with `@issue-assess`, implement with `@issue-fix` — [issue-assess-agent.md](../dev/issue-assess-agent.md).

## Env

| Variable | Purpose |
|---|---|
| `SUPPORT_GITHUB_TOKEN` | PAT with `issues:write`. Forwarding requires opt-in and a current preview; otherwise submit locally with `github_sync=local_only`. An unset token makes preview unavailable. If the token disappears after approval, the sender skips forwarding and retains the local ticket. |
| `SUPPORT_GITHUB_REPO` | Default `cephyrixzyth/oneirodex` |

## Admin alert prefs

Global settings: `admin_notify_support` (and related `admin_notify_*` for library events). User preference `notify_support` controls whether admins receive in-app rows.

## API

- `POST /api/support/tickets` — create (session + CSRF). `title` required; `body`/`symptom` and `logs` optional.
- `POST /api/support/preview` — authenticated browser session + CSRF; returns availability, safe destination, unknown visibility and mandatory redacted preview. No ticket creation or provider contact. Forwarding create requests include its `request_id` and `preview_token`; missing or stale approval returns 409.
- `GET /api/support/tickets` — own tickets (members) / all (admin). Compact rows: `body` ≤280, `logs` null, `has_logs`, `empty`.
- `GET /api/support/tickets/<id>` — full ticket including logs.
- `POST /api/support/tickets/<id>/resolve` — admin

Ticket timestamps are serialized as ISO-8601 UTC with an explicit `+00:00` offset, consistently across create, list, detail, and resolve responses.

### Related member feeds (Wave 2c)

- `GET /api/notifications` — `{ notifications, unread_count, empty }`
- `GET /api/announcements` — `{ announcements, empty }` (+ `body_preview` per row)
- `GET /api/news/gaming` — `{ items, empty }` (never 500 on RSS failure)
- `GET /api/news/free-games` — `{ items, enabled, connected_stores, empty }`

## React admin page behavior

Support Inbox is served at the existing URL through the shared React admin shell. Loading and errors use the shared page shell, with Try again after a failed list request. Resolve controls identify their ticket and prevent overlapping requests; failures leave the ticket visible with an error. Table sorting/filtering and GitHub links retain their existing behavior.
