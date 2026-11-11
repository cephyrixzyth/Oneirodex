# Support inbox (admins)

> **Doc status:** Active

Teammate reports land in-app. GitHub sync is opt-in on each report. Discord is not used.

## Member path

Members open **More → Report issue** (`/report`). Fields: title (required), symptom/body (optional), area, severity; **Context** (deploy, client, URL) and **Logs** stay collapsed until expanded. Reports stay on this server unless the member checks **Also send this report to GitHub**, selects **Preview GitHub report**, reviews the destination and redacted text, then submits. The external text includes report details, context, optional logs, reporter ID, role and a report reference. Preview does not save a ticket or contact GitHub.

Caps on create: symptom ≤2000 chars, logs ≤4000 chars. List payloads omit log blobs (`has_logs` + truncated `body` / `body_preview` + `empty`).

External titles and bodies are always filtered at the shared GitHub sender. Recognized credentials, private-key blocks, email addresses and home-directory paths are removed; URL queries and fragments are removed as a whole, which can also hide useful diagnostics. Local ticket text is preserved. Automatic filtering cannot recognize every private detail in prose; edit the report or keep it local. There is no raw override.

The preview names the validated owner/repository. Repository visibility is **unknown**; treat the report as potentially public. Configuration availability does not establish provider reachability or write permission. A missing token or invalid repository keeps forwarding unavailable while local-only submission stays usable. Approval expires after 15 minutes and is bound to the signed-in account, normalized contents, report reference and configuration; edits, account changes or configuration changes require another preview. Clients that previously sent only `sync_to_github=true` must obtain preview approval first. Delivery/retry and duplicate-request qualification remain open review work.

## Delivery receipts and retries

The member form creates a UUID before its first submission and keeps it if the response is lost. Repeat the unchanged report with the same `request_id` to recover the original local ticket. The database reserves that reference per account and commits a sending marker before contacting GitHub. A pending reservation can resume with a valid preview; an in-flight, unknown or confirmed attempt is never automatically posted again. Changed contents under an existing reference return409. API clients should generate and retain their own UUID; older local-only clients that omit it receive a server-generated reference but cannot recover a lost response by key unless they retained that reference.

| `github_sync` | Meaning |
|---|---|
| `local_only` | No external send requested. |
| `pending` | Local receipt committed; external attempt not started. |
| `sending` / `unknown` | Delivery is unconfirmed and might already exist. Keep the ticket and report reference; do not submit a new report. |
| `synced` | GitHub returned201 and a valid issue number/link for the configured repository. |
| `reconciled` | An exact matching existing issue was found by a read-only check. This does not prove who created it. |
| `rejected` | GitHub returned a recognized client rejection. The local ticket remains. |
| `skipped` | No external POST was made because forwarding became unavailable. |
| `error` | Historical failure state; inspect the destination before attempting another send. |

For a definite rejection or skipped delivery, **Prepare GitHub retry** reopens the saved details and requires a fresh redacted preview. It keeps the report reference and uses a distinct attempt reference; a lost retry reply can be retried with that same reference to recover the receipt. Pending delivery can be continued without creating a new report. Provider cooldowns and a five-attempt/hour/account budget persist across requests; **Try again after** means no new attempt started during the wait.

For uncertain delivery with retained attempt metadata, enter the issue number from its original destination and choose **Check existing issue**. This performs a bounded read, verifies the repository/link and exact redacted title/body, and never creates an issue. Owners or browser-signed-in administrators may check; unrelated, inaccessible or mismatched provider content is withheld. Failed checks count toward five checks/hour/account. Older receipts without a verifiable attempt fingerprint require manual operator checking. Do not change a delivery state directly in the database or assume a timeout means the issue was not created. Repository redirects are refused; after a rename, repair the configured destination and preview again. No provider request ID or HTTP retry advice establishes exactly-once creation. See the [GitHub create-issue endpoint](https://docs.github.com/en/rest/issues/issues#create-an-issue) and [REST API retry guidance](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).

The receipt migration preserves historical tickets with null references and adopts an existing startup-created unique index into the matching database constraint. It refuses a schema downgrade once receipts exist. For rollback, retain a tested pre-upgrade database backup; deleting receipt columns loses duplicate-send protection.

The follow-up attempt migration preserves old reports without inventing send history. Attempt metadata and lookup budgets belong to their accounts and are deleted with them; security/audit retention is separate. It also refuses downgrade when attempt receipts exist.

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
- Explicit retry uses `POST /api/support/tickets` with unchanged fields and `request_id`, `sync_to_github=true`, `retry_github=true`, new `retry_id`, and its fresh `preview_token`. Replays do not send again. Unknown/sending/confirmed delivery cannot be retried.
- `POST /api/support/tickets/<id>/reconcile` — owner/admin browser session + CSRF, JSON positive integer `issue_number` up to2147483647. Exact match returns a `reconciled` receipt; generic409 retains uncertainty.404 withholds inaccessible reports,429 limits lookups.
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
