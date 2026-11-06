# Behavior parity review

## Goal

Establish and verify 100% behavior parity between the exact official v1.1.8 release and the current FastAPI/React application. Compare every shared route and method across permissions, state changes, validation and failure responses, redirects, cookies, direct navigation, and relevant UI states. Retain newer behavior when it is better and owner-approved, document the evidence, and verify current-only operations separately. Do not declare completion while any in-scope route or material behavior is partial or unexplained.

Work in risk-ranked route-family batches. Reuse evidence only when exact image identity and scope are proven. Fix confirmed regressions, then run focused verification. Keep independent clean-main fixes reviewable. The owner authorized pushing the review branches to GitHub for independent review on 2026-11-06; merging, publishing, and deployment remain out of scope.

## Current evidence status — 2026-11-06

The current pinned images are official v1.1.8 `sha256:19648d0ed947d72ba0b74292ecd91b3d92d4a37be3ac8063ab16e80a43bc864e` and current source image `00b0bf2a` (`sha256:17a0bbdc97e24c51f6c30746b4af5f35151089361cb11428edb669451d6471d1`, source revision `00b0bf2ab06b531938476d9d765c4c4e99a706b3`).

The exact-image route inventory contains 1,545 shared method/path pairs: all 1,545 are structurally dispatched, while current-image behavior is fully verified for 0, partially verified for 10, and unverified for 1,535. Structural coverage does not establish behavior parity. The 160 current-only method/path pairs include 81 non-synthesized operations; 2 are partially exercised and 158 remain unverified. See `.artifacts/parity-v1.1.8/route-action-matrix-current-r1970.json`.

At the 2026-11-06 review-branch push, GitHub reported 108 open Dependabot alerts on the default branch: 13 critical, 54 high, 40 moderate, and 1 low. The configured GitHub CLI could not retrieve individual alert records because its token lacks the required security-alert access. This is a repository-level dependency backlog snapshot; the independent security review should fetch and triage the individual alerts. These parity and indexer/provider commits do not resolve or disposition those alerts.

R1967 added 29 exact-image comparisons for personal API-token list/create/revoke behavior. All status, normalized body, and redirect-location comparisons matched. Cases include member/other/admin/child roles, missing CSRF, malformed JSON, invalid name type, unknown preset, scope restrictions, ownership, repeat revocation, and active/revoked bearer use. Mutations stayed in disposable cloned databases; external egress was blocked; cleanup passed. These are selected cases, so the three API routes remain partial. Evidence: `.artifacts/parity-v1.1.8/api-token-lifecycle-exact-r1967.json`; follow-up ledger: `.artifacts/parity-v1.1.8/route-followups-r1967.json`.

R1969 captured direct `/tokens` navigation and the signed-in account-menu token panel on both exact images at 1440px and 390px. Both returned 200, showed matching token-page headings and empty state, opened the API tokens dialog, and produced zero page errors. Document/body width matched the viewport. R1970 confirmed in fresh 390×844 contexts that the legacy rail is visible over content while current hides it off-canvas and marks it aria-hidden. The owner approved keeping current rail behavior on 2026-11-06. `GET /tokens` remains partial because its other behavior and UI states are not fully verified; see `.artifacts/parity-v1.1.8/api-token-ui-exact-r1969.json`, `route-followups-r1969.json`, and R1970 fresh-mobile evidence.

R1972 compared the mobile token lifecycle in the signed-in account panel on both exact images at 390×844. Create returned 201; the one-time secret was shown in the expected format, copied, then cleared on Done; thin scopes persisted; revoke returned 200 and the cloned database row was marked revoked. The account panel and `GET /api/tokens` continued to list the revoked token on both images. No page errors occurred, and all disposable apps, databases, volumes, proxies, and network resources were removed. The lifecycle outcomes matched. The legacy account dialog measured 358×484px; current uses a 390×844px full-screen panel. This size difference is recorded for independent review and has no owner disposition yet. Sanitized evidence: `docs/dev/parity-evidence/token-ui-lifecycle-r1972.json`. The account panel and route remain partial pending disposition and coverage of remaining states.

## Next execution batches

1. Get owner/independent-review disposition on the R1972 mobile dialog-size difference; then cover remaining token failure, populated, keyboard, and accessibility states plus database-failure/expiry API cases.
2. Continue through shared routes in risk-ranked families; keep synthesized HEAD/OPTIONS explicit and verify current-only operations on their own track.
3. For every mismatch, decide whether it is a confirmed regression or an owner-approved improvement, implement only supported corrections, and rerun the affected exact-image cases.
4. Run the targeted regression/security checks for accepted fixes, refresh the route ledger and hub status, and make small local commits.
5. Report verified cases separately from route completion; no route is complete solely because its tested subset passed.

## Independent clean-main fixes

The clean-main worktree `C:\Users\cephyrix_zyth\.codex\worktrees\parity-fix-lane\Oneirodex` has two local commits on `codex/parity-indexer-https-guard`: native indexers require HTTPS, and metadata-provider errors redact API keys. The first pytest invocation stopped at the repository safety guard because `TEST_DATABASE_URL` was not configured. Five database-independent tests covering HTTPS indexer save/use/redirect guards and metadata-provider key redaction passed. Database-backed tests remain unrun until a dedicated disposable test URL is configured. The owner has now authorized pushing both review branches to GitHub; no merge or deployment is authorized.
