# ADR 0013: Session, reusable-secret and deletion recovery contract

> **Doc status:** Active

**Date:** 2026-11-07  
**Status:** Accepted — owner decisions recorded 2026-11-07; implementation and runtime qualification remain tracked work.  
**Owners:** `agent-backend` · `agent-ops` · `agent-security`

## Context

The repository review confirmed that the legacy remember cookie has no server-
enforced age, inactivity limit or per-device revocation. Reusable integration
credentials do not yet share one encrypted storage contract, and account
deletion does not yet inventory and clean every user-owned database row and
file. These changes share key custody, backup and retained-record decisions;
implementing them independently could strand integrations or retain data in a
way the owner did not select.

This record captures the owner's selected policies. The persistent browser
session implementation is now present in the current review branch and is
under independent postpatch review. Reusable-credential and account-deletion
migrations remain planned work.

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
  separate key purposes. Current save encryption still derives its key from
  `SECRET_KEY`; the standalone move path carries the source save key in its
  protected move package. This decision does not make `SECRET_KEY` rotation a
  safe save-key rotation. P2-18 must specify and verify save-key recovery and
  rotation before that migration can be called complete.

### Account deletion and backups

- Delete the user's live private data and credentials. Retain security and
  audit events only after removing direct account identifiers from retained
  records where the event can remain meaningful without them.
- Do not delete shared household records or another user's data merely because
  the departing user authored, used or referenced them. Each relation and
  managed file class needs an explicit disposition before the deletion job is
  considered complete.
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
| Save-encryption key | Keep the existing standalone move compatibility path. New key custody and rotation remain a P2-18 acceptance gate; do not rotate `SECRET_KEY` as a substitute. |

## Migration order

1. Add and verify the session, key-envelope and deletion contracts against
   current schema and runtime behavior. **Policy decisions recorded.**
2. Add server-enforced sessions and explicit legacy-cookie reauthentication.
   **Implemented in review branch; independent candidate review finding fixed and focused verification passed; release qualification remains pending.**
3. Introduce versioned reusable-secret envelopes, then migrate and rotate
   credentials in restartable batches while retaining old ciphertext until
   decryptability is verified.
4. Inventory every user relation and managed file, then implement resumable
   deletion using the decisions above.
5. Include key identifiers and restore checks in backup/restore work. Keep
   save encryption migration separate from reusable integration credentials.

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
