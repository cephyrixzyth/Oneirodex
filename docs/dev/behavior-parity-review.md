# Behavior parity review

## Goal

Establish and verify 100% behavior parity between the exact official v1.1.8 release and the current FastAPI/React application. Compare every shared route and method across permissions, state changes, validation and failure responses, redirects, cookies, direct navigation, and relevant UI states. Retain newer behavior when it is better and owner-approved, document the evidence, and verify current-only operations separately. Do not declare completion while any in-scope route or material behavior is partial or unexplained.

Work in risk-ranked route-family batches. Reuse evidence only when exact image identity and scope are proven. Fix confirmed regressions, then run focused verification. Keep independent clean-main fixes reviewable and local. Push, publish, merge, and deploy only after explicit release authorization.

## Current evidence status — 2026-11-06

The current pinned images are official v1.1.8 `sha256:19648d0ed947d72ba0b74292ecd91b3d92d4a37be3ac8063ab16e80a43bc864e` and current source image `00b0bf2a` (`sha256:17a0bbdc97e24c51f6c30746b4af5f35151089361cb11428edb669451d6471d1`, source revision `00b0bf2ab06b531938476d9d765c4c4e99a706b3`).

The exact-image route inventory contains 1,545 shared method/path pairs: all 1,545 are structurally dispatched, while current-image behavior is fully verified for 0, partially verified for 9, and unverified for 1,536. Structural coverage does not establish behavior parity. The 160 current-only method/path pairs include 81 non-synthesized operations; 2 are partially exercised and 158 remain unverified. See `.artifacts/parity-v1.1.8/route-action-matrix-current-r1967.json`.

R1967 added 29 exact-image comparisons for personal API-token list/create/revoke behavior. All status, normalized body, and redirect-location comparisons matched. Cases include member/other/admin/child roles, missing CSRF, malformed JSON, invalid name type, unknown preset, scope restrictions, ownership, repeat revocation, and active/revoked bearer use. Mutations stayed in disposable cloned databases; external egress was blocked; cleanup passed. These are selected cases, so the three API routes remain partial. Evidence: `.artifacts/parity-v1.1.8/api-token-lifecycle-exact-r1967.json`; follow-up ledger: `.artifacts/parity-v1.1.8/route-followups-r1967.json`.

## Next execution batches

1. Finish token routes with database-failure and expiry cases, remaining validation boundaries, and complete token-management UI/direct-navigation states.
2. Continue through shared routes in risk-ranked families; keep synthesized HEAD/OPTIONS explicit and verify current-only operations on their own track.
3. For every mismatch, decide whether it is a confirmed regression or an owner-approved improvement, implement only supported corrections, and rerun the affected exact-image cases.
4. Run the targeted regression/security checks for accepted fixes, refresh the route ledger and hub status, and make small local commits.
5. Report verified cases separately from route completion; no route is complete solely because its tested subset passed.

## Independent clean-main fixes

The clean-main worktree `C:\Users\cephyrix_zyth\.codex\worktrees\parity-fix-lane\Oneirodex` has two local commits on `codex/parity-indexer-https-guard`: native indexers require HTTPS, and metadata-provider errors redact API keys. The first pytest invocation stopped at the repository safety guard because `TEST_DATABASE_URL` was not configured. I then ran the five database-independent tests covering HTTPS indexer save/use/redirect guards and metadata-provider key redaction; all 5 passed. Database-backed tests remain unrun until a dedicated disposable test URL is configured. No GitHub or release action was taken.
