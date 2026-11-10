# Privacy & data handling (operator notes)

> **Doc status:** Active

This is **not** a public privacy policy, **not** a terms-of-service, and **not** legal advice.
Oneirodex is self-hosted: the machine you run it on holds the data, and **you** decide what to tell
the household. Use this as a fact sheet to adapt, not as something to publish as if Oneirodex Inc.
were the controller.

The product used to serve WebRetro's upstream ToS / privacy / cookie pages from every deployment
(finding L3). Those files are gone so this host does not impersonate another site's operator.

Related: [members-and-invites.md](members-and-invites.md) · [settings-modules.md](settings-modules.md) ·
[webretro-core-clauses.md](webretro-core-clauses.md) (snes9x / genesis_plus_gx — not counsel)

## What stays on your server

| Kind | What | Notes |
|---|---|---|
| Accounts | Username, Argon2 password hash, role, optional email | Emailless accounts use an unroutable `.invalid` placeholder — [members-and-invites.md](members-and-invites.md). New password-reset tokens are stored as SHA-256 digests and expire after 15 minutes; tokens issued before this change remain accepted until their existing expiry. |
| Sessions | Signed browser cookie, CSRF token, and a per-login server record with a hash of a random session secret plus created/last-seen/expiry/revocation times | Same-origin. Browser sessions expire after 7 inactive days and at 30 days absolute; members can revoke one or all from Account → API tokens → Browser sessions. The raw session secret is never stored. API tokens are separately **hashed** (SHA-256); the raw `gt_…` secret is shown once |
| Library | Game metadata, paths, artwork you stored | Paths point at disks you mounted (`DATA_FOLDER_GAMES`, `ONEIRODEX_LIBRARY_ROOTS`); member freshness responses omit absolute install paths |
| Playtime | Per-user totals and session heartbeats | `share_activity` (default on) controls whether accepted friends see live play status in Discover. It does not hide historical playtime from profile or comparison views when those viewers already have access to the member's library/social data. |
| Presence | Online / away / in-game | Derived from play sessions and companion heartbeats, not a third-party tracker |
| Chat | Channel messages, reactions, attachments | Household Spaces only. **No Discord**. Attachment reads recheck channel access and return `Cache-Control: private, no-store` |
| Store ownership | Steam ID; GOG / Epic / Amazon / Xbox / PlayStation sign-in tokens; synced title IDs and names; per-store sync history (status, redacted reason code, counts, times; last 20 per store) | Register only — never a store download. Provider credentials are encrypted at rest with a dedicated operator-managed key ring, never returned by APIs, and do not use `SECRET_KEY`. Sync errors reach members and admins as fixed sentences, never provider error text, request URLs or tokens. Disconnect removes the link, its titles, match decisions and sync history |
| Notifications | In-app inbox + archive | Optional SMTP for mentions/DMs and a daily digest, each a member preference |
| Support reports | Title, body, optional logs, client/url hints | Stays on this server by default. The member must opt in before a report is sent to GitHub. |
| Companion devices | Heartbeat / last-seen | Desktop client stores its token in the OS credential store, not plaintext config |

There is no Oneirodex cloud account, no product analytics SaaS, and no Discord.

Native member JSON write APIs stream request bodies with a 64 KiB limit for saved filters and previews, collection updates, wanted-update entries, ownership match decisions, notification preferences, chat writes, and batch freshness checks. Oversized bodies receive HTTP 413 before these writes reach persistence.

Administrator supplied library artwork is limited to 10 MiB compressed and 16 megapixels, accepts decoder-identified GIF/JPEG/PNG/WebP content regardless of the filename suffix, and is normalized to PNG for storage. The cropped-image preview reads no more than its configured streamed JSON ceiling before parsing. Member avatars are limited to 5 MiB and 16 megapixels per frame, with a 200-frame and 32-megapixel total-frame ceiling for animations. The stored avatar format follows the decoded JPEG/PNG/GIF/WebP content, regardless of suffix. Custom chat emoji are limited to 256 KiB and 4 megapixels, accept decoder-identified PNG/JPEG/WebP content regardless of suffix, reject animated sources, and are stored as WebP. These per-input limits do not yet establish a measured whole-process memory ceiling under simultaneous uploads.

Game artwork uploads are limited to 3 MiB compressed and 60 megapixels, and the saved suffix follows the decoded JPG, PNG, or GIF format rather than the client filename. Downloaded cover qualification is limited to 60 megapixels and uses the same image-work slot. One library-art, avatar, game-art, downloaded-cover, or custom-emoji validation/transform runs per server process; overlapping work receives a retryable unavailable response or a retry message in legacy forms. Native image workers are synchronous and cannot be forcibly stopped: cancellation waits for the worker to finish before its request/database scope closes. A cancelled avatar change is rolled back and its replacement files are removed; other route-specific cancellation outcomes are not yet verified. Multiple server workers each have their own slot. The 60-megapixel ceiling and per-worker slot count remain provisional until supported NAS peak-work measurements are complete.

The admin RetroAchievements match API also stops reading JSON once its 8 KiB request limit is exceeded.

Container startup passes parsed database connection settings to its probe as environment data rather than interpolating them into Python source.

The browser PWA caches versioned public assets and a data-free offline page, not private pages, APIs or covers. Startup retires the former VR worker before private VR requests proceed; sign-out removes owned caches even when no worker controls the page. Unrelated application caches remain intact. Fully offline legacy installations need an online update before these protections can apply. Focused Chromium migration fixtures are verified; authenticated application/headset acceptance remains open.

## What can leave the machine (only if you turn it on)

| Channel | When | What goes out |
|---|---|---|
| SMTP | You set a mailer | Invite links, optional social/digest mail — only to addresses you or members provided |
| Store ownership sync | Member saves a Steam ID or a store token (or the operator sets a household token) | Store account ids and owned-title lists come back. Tokens stay on this host. Unofficial launcher APIs for GOG, Epic, Amazon, Xbox and PlayStation. **Household tokens:** a member who links a store *without* their own token syncs the household account, and that library is recorded in *their* register; the member's store card and the admin **Store connections** page say which sign-in each link uses. A member's own token, even an incomplete one, is never mixed with the household one. Replacing a household env token supersedes the copies refreshed into member rows. Copies stored by versions before LIB-04 were not marked, so on a server with a household token for GOG, Amazon or Xbox a pre-upgrade sign-in is reported as *unknown* (not as the member's own) until the member reconnects |
| News feeds | `ONEIRODEX_NEWS_FEEDS` (http/https only) | The **server** fetches public destinations and checks each redirect under the same policy. Private-network feeds and responses above 512,000 decoded bytes are skipped; members can hide individual sources |
| OIDC | `OIDC_ENABLED` | Username / email / groups from *your* IdP (Authentik, etc.); the configured issuer must use HTTPS |
| LiveKit | Voice profile | Room tokens for household voice; media goes to the LiveKit you deployed |
| GitHub support | `SUPPORT_GITHUB_*` and the member's per-report opt-in | The selected report, context, optional logs, reporter ID, and role go to the administrator-configured repository. Members can keep reports local by leaving the opt-in unchecked. |
| WebRetro cores | First boot fetch | WASM cores from the operator-provisioned install path — [webretro-cores.md](../runbooks/webretro-cores.md) |

ROM files, BIOS, and artwork you pointed the library at never upload to a Oneirodex service — there isn't one.

Validated outbound HTTP requests recheck redirect destinations. On a change of
scheme, hostname or port, they discard authentication, cookies and provider
headers; original query parameters are not appended again. Body-preserving
307/308 redirects are supported within one origin; replay to another origin is
rejected because request bodies may contain store credentials.
Debrid API calls begin at fixed HTTPS provider URLs and validate each redirect
hop against the public-only HTTPS policy; redirects to private or cleartext
destinations are refused.

## Delegated tokens and private reads

Chat messages, attachments, space membership, notifications, friends and presence,
member profiles, and household activity require `read:social` for bearer-token
reads. Social mutations require `write:social`, which is not included in the thin
client preset. A library-only companion token cannot access social data; channel
membership and child-safety rules still apply to social tokens. Emulator save-state
listing and downloads require `read:library`; uploads and deletion require
`write:library`. RetroArch cheat files follow the same boundary: list/download
requires `read:library`, while upload/delete requires `write:library`. PC cheat
notes are readable with `read:library`; authoring/deletion stays librarian-only.
LiveKit token requests require `read:social`; bearer tokens need `write:social` to
mint a publish-enabled token, while read-only social tokens can request spectator
access.
Favorite and play-status changes, Discover pins and saved filters, wishlist
requests, wanted-update entries, member preferences and detail layouts,
personal collections, playtime sessions, and on-demand freshness checks also
require `write:library` for Bearer tokens; `read:library` alone cannot invoke
these write routes. Bounded update scans, store ownership links/imports/syncs,
launcher imports, and owned-title matching use the same bearer scope. Free-game
ownership assistance, which may update ownership data and start a store sync,
also uses this scope.
Member-specific library reads—including Discover feeds, library filters,
exports, game health, wanted/update search, mod state, related media,
RetroAchievements progress, trailer picks, and assist packs—require
`read:library` for Bearer tokens. Shared taxonomy and provider capability
metadata remain available without it; signed browser sessions keep their
existing access.
Registration invite management requires a signed-in browser session, including
the classic invite page. API tokens cannot list, create or delete these invites.
Private account summaries and support report reads also require the signed-in
browser session; delegated library/social tokens cannot retrieve account email
or report bodies/logs. Report submissions are capped at five per account per
hour before any optional GitHub issue sync runs.
Normal browser account flows and public invite redemption remain available.

## Child accounts

Collection item lists and counts follow the child's current library allow-list
and genre/theme restrictions, including when the child owns the collection.
Changing those restrictions immediately changes what appears in existing
collections.

`child` is not a cosmetic label. On top of parental library allowlists:

- No `admin`, `write:library`, or `write:download` — on **session cookies and Bearer tokens**
- Server-file download initiation (base games, updates, extras, and translation patches) is denied for child accounts
- Cannot mint those scopes (including the Desktop companion preset)
- Existing Bearer-token scopes are checked against the current account role when companion commands are delivered; changing a member to `child` stops lifecycle command delivery even if an older token remains active
- `GET /api/acquire/search` returns 403
- Companion download / install / update / uninstall / patch / mod-pack commands are denied
- Personal playtime and download history hide games outside the child's current library/content access

Thin-client tokens (browse / social) still work.
The social status `now_playing` list is empty for child accounts, matching the
child restriction on `/api/activity` in both server runtimes. Friend presence
continues to follow accepted-friend and game-access rules.

## Backups and deletion

Postgres holds accounts, chat, playtime, and the catalog. Game files live on the library mounts.
The operator-managed credential key ring is required to decrypt linked-store and reusable
integration credentials. Keep it outside database/library backups and maintain a protected
independent backup. A database backup without the matching key ring cannot restore those
integrations; when a key is unavailable, preserve ciphertext and restore the matching key ID or
reconnect the affected integration. Backups created before the credential conversions may
contain plaintext provider or integration credentials and should remain protected accordingly.
Backups from before password-reset token hashing may also contain raw reset tokens;
the application continues to enforce the 15-minute expiry when a token is used.
Account deletion is in progress. The Flask and native handlers now share relation cleanup and
audit anonymization. The current ORM metadata inventory contains 82 tables and 50 foreign-key
columns to user IDs; all nine with no database `ON DELETE` action have explicit delete, clear, or
retain dispositions. PostgreSQL route/service tests cover a blocking download request, invite
creator and used-by references, personal attract settings, favorites/status rows, duplicate-fix
actor history, authored newsletter removal, and audit retention with direct identifiers removed.
Absolute Windows, UNC, and POSIX paths in retained events for the deleted account are redacted.
Retained unmatched-folder feedback and notifications delivered to other members also have the
departing actor's identifiers and absolute paths redacted; household chat message text remains
visible with its author anonymized, as selected by the owner. Public and system game collections
and their items remain available after their owner is deleted, with the owner reference cleared;
private non-system collections and items are deleted with that account.
The retained-text inventory now also covers announcements, related media, PC cheats,
public/system collection names and descriptions, and game-request/support-ticket text retained
when another member owns the record. Before account deletion, direct name/email/stable-ID matches
and detected absolute local paths are redacted from those retained fields, and actor/resolver or
owner references are cleared in the deletion transaction. Household chat bodies remain intact
under the selected anonymized-author exception. This is an ORM-source review, not a comparison
against every deployed database schema; arbitrary unrelated personal facts in free text cannot
be reliably detected.

The selected policy is to purge user-specific emulator save-state, uploaded avatar, and chat
attachment bytes after the database deletion commits. The deletion transaction records safe
managed-root cleanup jobs before it commits; failed unlinks remain retryable, and the deletion
response reports whether cleanup is pending. A background worker retries pending jobs after
startup and every minute. Offline backups are outside account deletion and follow a separate
operator retention policy with no duration set here. The reviewed retained-text fields are
listed above; unrelated personal facts in arbitrary text remain undetectable. Shared
library/game files, shared chat spaces, shared emojis, and reference
sets must not be removed merely because an account is deleted; uploader/author references are
cleared where supported. Full server restart/redeployment, deployed-schema comparison, and
restore reapplication remain open work.
The verified offline backup flow currently covers standalone installs only; see
[Backup and restore](../runbooks/backup-restore.md) for its inclusion and exclusion boundary.
Deleting a game removes its
play sessions and per-game progress; game requests, owned-title matches, and linked game-server
records remain with their game reference cleared where the schema defines `SET NULL`.
There is no built-in "export my data" package — dump the database if a household member asks for a copy.

To inspect emulator-save storage without modifying files, run `python scripts/audit_emulator_saves.py --root <configured-save-root>` with the intended database configured through the same explicit database settings as the other operator maintenance scripts. The bounded report includes only counts and status for referenced, missing, outside-root, symlink, and unreferenced entries; it never prints paths and never performs garbage collection. Review reported orphan candidates before any manual action.

Admin → System danger-zone reset can wipe catalog / libraries / users / settings in-app; it **never
touches files on disk**.
Previously committed account-deletion file cleanup jobs survive every reset scope. The separate
cleanup worker continues those earlier deletions; resetting users does not cancel them. The users
scope includes persistent login sessions and prior save-generation records. Reset planning refuses
a database cascade that would erase the retained cleanup journal.

## Adapting this for a real notice

If you need a notice for your jurisdiction, keep the facts above and add: who operates the host,
how long you keep backups, how a member asks you to delete an account, and whether any of the
optional outbound rows are actually enabled on *this* deploy. Do not paste WebRetro's or any other
vendor's policy onto your domain.
