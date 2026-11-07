# Behavior parity review

## Goal

Establish and verify 100% behavior parity between the exact official v1.1.8 release and the current FastAPI/React application. Compare every shared route and method across permissions, state changes, validation and failure responses, redirects, cookies, direct navigation, and relevant UI states. Retain newer behavior when it is better and owner-approved, document the evidence, and verify current-only operations separately. Do not declare completion while any in-scope route or material behavior is partial or unexplained.

Work in risk-ranked route-family batches. Reuse evidence only when exact image identity and scope are proven. Fix confirmed regressions, then run focused verification. Keep independent clean-main fixes reviewable. The owner authorized pushing the review branches to GitHub for independent review on 2026-11-06; merging, publishing, and deployment remain out of scope.

## Current evidence status — 2026-11-06

The current pinned images are official v1.1.8 `sha256:19648d0ed947d72ba0b74292ecd91b3d92d4a37be3ac8063ab16e80a43bc864e` and current source image `00b0bf2a` (`sha256:17a0bbdc97e24c51f6c30746b4af5f35151089361cb11428edb669451d6471d1`, source revision `00b0bf2ab06b531938476d9d765c4c4e99a706b3`).

The exact-image route inventory contains 1,545 shared method/path pairs: all 1,545 are structurally dispatched, while current-image behavior is fully verified for 0, partially verified for 10, and unverified for 1,535. Structural coverage does not establish behavior parity. The 160 current-only method/path pairs include 81 non-synthesized operations; 2 are partially exercised and 158 remain unverified. The compressed, sanitized full matrix and its manifest are in `docs/dev/parity-evidence/review-bundle-r1972/`.

At the 2026-11-06 review-branch push, GitHub reported 108 open Dependabot alerts on the default branch: 13 critical, 54 high, 40 moderate, and 1 low. The configured GitHub CLI could not retrieve individual alert records because its token lacks the required security-alert access. This is a repository-level dependency backlog snapshot; the independent security review should fetch and triage the individual alerts. These parity and indexer/provider commits do not resolve or disposition those alerts.

R1967 added 29 exact-image comparisons for personal API-token list/create/revoke behavior. All status, normalized body, and redirect-location comparisons matched. Cases include member/other/admin/child roles, missing CSRF, malformed JSON, invalid name type, unknown preset, scope restrictions, ownership, repeat revocation, and active/revoked bearer use. Mutations stayed in disposable cloned databases; external egress was blocked; cleanup passed. These are selected cases, so the three API routes remain partial. Sanitized evidence and the follow-up ledger are in `docs/dev/parity-evidence/review-bundle-r1972/`.

R1969 captured direct `/tokens` navigation and the signed-in account-menu token panel on both exact images at 1440px and 390px. Both returned 200, showed matching token-page headings and empty state, opened the API tokens dialog, and produced zero page errors. Document/body width matched the viewport. R1970 confirmed in fresh 390×844 contexts that the legacy rail is visible over content while current hides it off-canvas and marks it aria-hidden. The owner approved keeping current rail behavior on 2026-11-06. `GET /tokens` remains partial because its other behavior and UI states are not fully verified; see the sanitized R1969 reports and R1970 fresh-mobile evidence in `docs/dev/parity-evidence/review-bundle-r1972/`.

R1972 compared the mobile token lifecycle in the signed-in account panel on both exact images at 390×844. Create returned 201; the one-time secret was shown in the expected format, copied, then cleared on Done; thin scopes persisted; revoke returned 200 and the cloned database row was marked revoked. The account panel and `GET /api/tokens` continued to list the revoked token on both images. No page errors occurred, and all disposable apps, databases, volumes, proxies, and network resources were removed. The lifecycle outcomes matched. Screenshot bounds for the visible account panel match on both images (x=16, y=155, width=358, height=534). The earlier DOM metric compared different elements: the legacy `role=dialog` is the panel, while current `role=dialog` is the full-screen scrim. Keep the visible panel sizing classified as equivalent; ask the independent review to inspect the dialog/focus semantics. Sanitized evidence: `docs/dev/parity-evidence/token-ui-lifecycle-r1972.json`. The account panel and route remain partial while other states and semantics are unverified.

## Next execution batches

1. Have the independent review inspect R1972 dialog/focus semantics; then cover remaining token failure, populated, keyboard, and accessibility states plus database-failure/expiry API cases.
2. Continue through shared routes in risk-ranked families; keep synthesized HEAD/OPTIONS explicit and verify current-only operations on their own track.
3. For every mismatch, decide whether it is a confirmed regression or an owner-approved improvement, implement only supported corrections, and rerun the affected exact-image cases.
4. Run the targeted regression/security checks for accepted fixes, refresh the route ledger and hub status, and make small local commits.
5. Report verified cases separately from route completion; no route is complete solely because its tested subset passed.

## Independent clean-main fixes

The clean-main worktree `C:\Users\cephyrix_zyth\.codex\worktrees\parity-fix-lane\Oneirodex` has two local commits on `codex/parity-indexer-https-guard`: native indexers require HTTPS, and metadata-provider errors redact API keys. The first pytest invocation stopped at the repository safety guard because `TEST_DATABASE_URL` was not configured. Five database-independent tests covering HTTPS indexer save/use/redirect guards and metadata-provider key redaction passed. Database-backed tests remain unrun until a dedicated disposable test URL is configured. The owner has now authorized pushing both review branches to GitHub; no merge or deployment is authorized.

## Independent repository review handoff — 2026-11-07

The supplied independent review package evaluates snapshot `fd2683e5` and explicitly forbids implementation by itself. The current user handoff authorizes incorporating its claims, correcting confirmed issues in the existing parity/security scope, and updating evidence. Its attached audit prompt is treated as historical evaluation scope, not as an instruction to restart the whole audit or implement its broad roadmap.

### Claims checked against the current checkout

| Finding | Audit evidence classification | Current disposition |
|---|---|---|
| BE-001 save slot overwrite / commit loss | Reproduced at audit snapshot | Current status unknown; data-integrity fix remains outside this focused security batch. |
| BE-002 favorites adapter error | Reproduced at audit snapshot | Already resolved in current source: `FavoritesData.payload` imports the ACL helper locally. Focused native route regression remains useful. |
| BE-003 password validation error | Reproduced at audit snapshot | Already resolved in current source: `_validated_body` imports its formatter locally. |
| BE-004 export truncation/filter order | Reproduced with 501 fixtures at audit snapshot | Current status unknown. |
| BE-005 missing-image scan repair | Reproduced at audit snapshot | Current status unknown. |
| BE-006 blocking cover search / skipped cleanup | Reproduced in an isolated test at audit snapshot | Current status unknown. |
| BE-007 reusable credentials in database fields | Storage observation confirmed; disclosure impact conditional | Current status unknown; no secret values were inspected. |
| BE-008 persistent remember cookie age/revocation | Reproduced with synthetic clock at audit snapshot | Current status unknown. |
| BE-009 user deletion foreign-key failure | Reproduced on SQLite; PostgreSQL pending | Current status unknown; backend-specific behavior remains unverified. |
| BE-010 delegated bearer scopes | Reproduced at audit snapshot | Already resolved in current source: exports and VR catalogue/detail require `read:library`. |
| BE-011 child save entitlement | Product policy observation; desired behavior undecided | Still unknown pending product decision. |
| BE-012 undefined-name branches | Static branch observations | Still unknown; reachability and current source were not rechecked. |
| BE-013 native theme upload Flask-only call | Reproduced with actual adapter and temporary files at audit snapshot | Current status unknown. |
| FE-001 VR service-worker private cache | Synthetic exact-worker reproduction; browser exploit not demonstrated | Confirmed and fixed in this checkout; real-browser/headset cleanup remains unverified. |
| FE-002 librarian version cleanup control | Source/API permission mismatch at audit snapshot | Current status unknown. |
| FE-003 mods error state disappears | Deterministic source control-flow defect at audit snapshot | Current status unknown. |
| FE-004 profile navigation stale identity/error | Source state-transition defect at audit snapshot | Current status unknown. |
| FE-005 related-media modal focus handling | Source accessibility gap at audit snapshot | Current status unknown. |
| FE-006 calendar query/display window mismatch | Source/data-window mismatch at audit snapshot | Current status unknown. |
| FE-007 shared-browser recent titles | Synthetic localStorage reproduction at audit snapshot | Fixed in this checkout: local names are no longer written/read, the legacy key is removed on member-app mount and logout, and delayed suggestion responses are discarded after viewer changes. Focused unit coverage passes; real multi-account browser verification remains open. |
| FE-008 missing React error boundary | Absence confirmed by source search; crash impact inferred | Current status unknown. |
| DT-001 concurrent install record loss | Forced interleaving reproduced at audit snapshot | Current status unknown. |
| DT-002 cold offline launch limitation | Source-based; runtime journey pending | Current status unknown. |
| DT-003 lifecycle write non-atomicity | Source-based; crash/disk failure pending | Current status unknown. |
| DT-004 nested patch/mod staging failure | Source contract mismatch at audit snapshot | Current status unknown. |
| DT-005 archive resource/destination risk | Source-based; hostile archive not run | Current status unknown. |
| DT-006 child-process reaping | Source/Rust contract; OS test pending | Current status unknown. |
| DT-007 twelve-title companion preview | Documented product limitation | Current status unknown; no product change authorized. |
| OP-001 native installer/factory mismatch | Source plus factory import reproduced at audit snapshot | Current status unknown. |
| OP-002 Windows worker count | Source-based; multiworker test pending | Current status unknown. |
| OP-003 container root privilege | Compose/Docker source observation; runtime pending | Current status unknown. |
| OP-004 incomplete build pinning/integrity | Source/build trust observation; no compromise found | Current status unknown. |
| OP-005 Pillow/Authlib advisory matches | Version/advisory matches reported; applicability conditional | Current status unknown/current triage needed; not 47 proven exploits. Recheck current resolved versions and advisory applicability before changing pins. |
| OP-006 docs/validation lag | Source/docs/link checks at audit snapshot | Current status unknown. |
| OP-007 template sync failure | Historical workflow job failure | Current status unknown; historical result is not current release status. |
| UC-001–UC-004 validation candidates | Follow-up validation questions, not confirmed findings | Still unknown; retain as validation work. |

The independent report's 35 finding rows and four validation candidates remain distinct from the parity matrix's 1,545 shared route/action pairs. Neither structural route dispatch nor this triage closes parity. The existing GitHub Dependabot alert count remains untriaged because individual records were unavailable; the independent package's advisory ledger is version evidence only and does not disposition GitHub alerts.

### FE-001 correction

The VR page still registers `/vr/sw.js` so existing installations can receive the retirement worker. On activation it removes `oneirodex-vr-v1`, claims clients, and unregisters; it has no fetch handler, cache-write path, or offline fallback. Its logout message also clears the retired cache. `tests/test_pwa_install.py` guards these properties. The user guide now describes the online update requirement. No live headset/browser account-switch test was run, so do not claim practical cross-account exposure is eliminated in already-offline clients until their worker updates.

### P0-07 correction: remove origin-global title history

The command palette now renders only recent/popular rows returned by the server for the active viewer. Open-title actions no longer persist names or IDs. The palette clears its old localStorage key on mount and resets/aborts suggestions when closed or when the viewer ID changes; a failed suggestions request reports an unavailable state without restoring old local titles, while title search remains usable. The shared sign-out helper also removes the legacy key before attempting service-worker messaging. `CommandPalette.test.tsx` and `recentTitles.test.ts` cover legacy-key removal, suggestion failure, normal search and stale-response rejection after an account switch. User guides now describe server-authorized suggestions and no browser history.

**Verification:** Node `22.23.4` via the temporary `node@22` runner: member-app command palette/history tests **22 passed** and member-app TypeScript typecheck passed. Python `3.14.10` (not the planned 3.12): PostgreSQL 17.6 disposable review DB on the isolated `oneirodex-review` Compose project; focused password/favorites/export/VR tests **33 passed**. Database guard tests **27 passed** with `--noconftest`; PWA worker/logout assertions **2 passed** with `--noconftest`. These tests do not replace a real Chromium/headset cross-account cache/recents check.

**P0-01 baseline remains partial:** Node 22 and the isolated review PostgreSQL service are available. `uv python install 3.12` could not fetch its CPython archive from Astral/GitHub, so Python tests used 3.14.10. The installed environment's `pip check` reports Playwright 1.64.1 requires `pyee<15` while 16.0.1 is installed, plus an incomplete `~uvicorn` distribution warning. Full baseline suite, all five SPA builds, desktop full/thin build, and native target checks remain outstanding. No root `.env` values were printed or file changes made; Compose may load `.env` for interpolation, while the review DB prefix and port were explicitly set for this isolated database-only service.

### Owner decisions received

- **D-P0-01 save history:** preserve prior committed generations; defer automatic garbage collection until the owner selects a time/space budget. This permits recoverable writes but means storage growth must be measured and surfaced.
- **D-P1-04 child personal progress:** allow a child's own save operations only for games currently accessible to that child, using a narrow save-specific permission and retaining existing library-write restrictions. Implementation remains sequenced after safe save storage (R02).
