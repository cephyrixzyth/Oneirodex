# ADR 0013: Session, reusable-secret and deletion recovery contract

> **Doc status:** Active

**Date:** 2026-11-07  
**Status:** Accepted — owner decisions recorded 2026-11-07; implementation and runtime qualification remain tracked work.  
**Owners:** `agent-backend` · `agent-ops` · `agent-security`

## Context

At the review snapshot, the legacy remember cookie had no server-enforced age,
inactivity limit or per-device revocation, reusable integration credentials
did not share one encrypted storage contract, and account deletion did not
inventory and clean every user-owned database row and file. These changes
share key custody, backup and retained-record decisions; implementing them
independently could strand integrations or retain data in a way the owner did
not select.

This record captures the owner's selected policies. The persistent browser
session implementation is present in the current review branch. The reusable-
credential envelope and conversion tooling are implemented in the candidate;
focused tests and an independent source review passed. Synthetic database
conversion and recovery from a separate operator-backup copy are qualified;
live operator database conversion and a protected-backup restore drill remain
pending. Save encryption now has a separate versioned keyring candidate and
legacy read path, with a synthetic PostgreSQL current/history rotation test.
The Linux Docker standalone restore rehearsal recovered the synthetic save
keyring from a separate read-only backup volume and verified imported saves;
real operator-media recovery and deployed/operator migration qualification
remain pending.
Account deletion now has
a PostgreSQL-verified relation inventory, a transactional managed-file job
queue, and a retry worker; deployment-schema, restart, and restore qualification
remain pending.
An offline standalone backup command now produces a versioned, checksummed
bundle and refuses completion when reusable plaintext credentials remain or a
referenced reusable-secret key ID is unavailable. A disposable Linux Docker
rehearsal verified import, rollback, repeat import, restored file serving and
recovery from a separate synthetic save-keyring backup volume. Docker/Unraid
backup capture, external-PostgreSQL capture and production backup-media
qualification remain open.

## Decision

### Persistent sessions

- Enforce a **30-day absolute maximum** and **7-day inactivity maximum** on the
  server.
- Support revoking the current device and all devices. Revocation must cover
  both persistent credentials and browser sessions minted from them.
- Store only a hash of a random persistent-session secret. Keep session
  records distinct from personal API tokens.
- On migration from the stateless legacy remember cookie, require the member
  to authenticate again. Do not silently extend the legacy cookie.
- A lost cookie-signing key requires fresh authentication; signing keys remain
  separate from reusable-credential and save-encryption keys.

### Reusable integration secrets

- Encrypt reusable integration credentials with an authenticated, versioned
  envelope and a dedicated operator-managed key ring. Do not derive this key
  from `SECRET_KEY` or store clear key material beside the database backup.
- Recover the key ring from an operator-managed backup whose access and storage
  are protected independently from database backups. Preserve key identifiers
  needed by restored ciphertext.
- If the active key is unavailable, keep ciphertext intact and report the
  integration as unavailable until the operator restores the matching key.
  Never fall back to plaintext or a built-in key.
- Cookie signing, reusable-credential encryption and save encryption have
  separate key purposes. New encrypted saves use a versioned key ID from a
  dedicated operator-managed keyring and authenticate the owning user, game,
  slot and opaque generation ID in `GTENC3`; retain old key IDs while any
  current save or supported encrypted backup needs them. Legacy `GTENC1` and
  `GTENC2` data remain readable; `GTENC1` uses its original `SECRET_KEY`-derived
  key or the protected legacy key entry. Do not treat a `SECRET_KEY` rotation
  as save-key rotation.
- Restore save-encryption key material from a protected operator backup stored
  separately from database, library and move bundles. If a key is unavailable,
  preserve ciphertext and report the save as unreadable until its matching key
  is restored. Key retirement remains explicit and requires evidence that no
  current save or supported backup references the key ID.

### Account deletion and backups

- Delete the user's live private data and credentials. Retain security and
  audit events only after removing direct account identifiers from retained
  records where the event can remain meaningful without them.
- Do not delete shared household records or another user's data merely because
  the departing user authored, used or referenced them. Each relation and
  managed file class needs an explicit disposition before the deletion job is
  considered complete.
- For user-owned avatar, emulator-save and generation, and uploaded chat
  attachment files, purge after the database deletion commits. Failed cleanup
  must remain retryable and visible; do not add a recovery quarantine.
- Offline backups are outside account deletion and follow a separate operator
  retention policy. This ADR does not set a backup duration.
- A deletion job must revoke access first, be idempotent and resumable, and
  report partial failure until owned database rows and files are handled.
- A database backup may contain data that was later deleted from the live
  system. Restoring such a backup restores that snapshot; operators must apply
  deletion requests again after restore when required. No backup-retention
  duration is selected by this record.
- Back up reusable-credential recovery material separately from database and
  library backup payloads. A key backup must not be bundled beside a shareable
  database dump.

### Key-loss tabletop outcomes

| Material | Selected recovery or consequence |
|---|---|
| Cookie-signing key | Old signed sessions become invalid; members authenticate again. Do not reuse a different key as a silent fallback. |
| Reusable-credential key ring | Restore the matching key IDs from the independently protected operator backup. If unavailable, preserve ciphertext and mark dependent integrations unavailable. |
| Save-encryption keyring | Restore matching protected key IDs separately from database, library and move bundles. Keep encrypted bytes unchanged if a key is missing. Legacy `GTENC1` reads still need the original derived key. |

## Migration order

1. Add and verify the session, key-envelope and deletion contracts against
   current schema and runtime behavior. **Policy decisions recorded.**
2. Add server-enforced sessions and explicit legacy-cookie reauthentication.
   **Implemented in review branch; independent candidate review finding fixed and focused verification passed; release qualification remains pending.**
3. Introduce versioned reusable-secret envelopes, then migrate and rotate
   credentials in restartable batches while retaining old ciphertext until
   decryptability is verified. **Implementation, independent source review,
   synthetic database conversion, and key-backup recovery qualification
   passed; live operator conversion and protected-backup restore drill remain
   pending.**
4. Inventory every user relation and managed file, then implement resumable
   deletion using the decisions above. The ORM user-FK inventory has 50 columns
   and a focused PostgreSQL test compares it with the database schema. Managed
   avatar, save, and chat-attachment cleanup is transactionally queued and
   retried; deployed-schema and restart-level qualification remain open.
5. Include key identifiers and restore checks in backup/restore work. Keep
   save encryption migration separate from reusable integration credentials.
   A versioned save keyring and standalone-move key-ID contract are implemented
   in the candidate; context-bound `GTENC3` writes, copy-across-owner rejection,
   synthetic PostgreSQL rotation, and Linux Docker restore using a separate
   read-only protected-key backup volume passed. Real operator-media restore
   and migration are still required.
6. The initial offline standalone backup reuses the stopped-application move
   snapshot and writes a completion marker only after re-hashing its dump and
   managed files. Its manifest records required key IDs and excluded roots,
   while key material stays in the separate protected operator backup.
   The disposable Linux Docker restore rehearsal passed; Docker/Unraid backup
   capture and concurrent-traffic qualification outside standalone remain
   pending.

Each step requires focused database-backed verification and operator-facing
documentation before it can be marked complete.

## Consequences

| Benefit | Cost |
|---|---|
| Copied persistent credentials can expire or be revoked server-side. | Legacy remember-cookie users must sign in again at cutover. |
| Restored integration ciphertext can be recovered without placing its key in the database backup. | Operators must maintain an independently protected key backup and preserve key IDs. |
| Deletion distinguishes private data from retained security history. | The relation/file inventory and retryable cleanup are required before deletion can be called complete. |
| Restore behavior makes backup retention explicit without promising immediate erasure from old snapshots. | Restore procedures must reapply applicable deletion requests. |

## Related

- [ADR 0011: Standalone bundled PostgreSQL](0011-standalone-bundled-postgres.md)
- [Privacy and data handling](../admin/privacy-data-handling.md)
- [Standalone-to-server move](../runbooks/standalone-move.md)
- Independent-review tasks P2-01, P2-05–P2-10 and P2-18 in the supplied
  2026-11-06 review plan; implementation evidence is tracked in
  `docs/dev/behavior-parity-review.md`.
