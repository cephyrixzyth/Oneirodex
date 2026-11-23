# Aurora Observatory / Moonfall benchmark

> **Doc status:** Reference
> Review implementation; not a release or accepted visual/gameplay benchmark.

The owner approved the [eight-world direction](../../superpowers/specs/2026-11-22-library-room-worlds-design.md) and implementation of the first room/game. The [execution plan](../../superpowers/plans/2026-11-22-aurora-moonfall.md) retains human benchmark review before the other seven games. The existing 1.3.3 deployment is unchanged.

## Implemented scope

- Original procedural observatory architecture, aurora, instruments and actual catalog cases; temporary world visits preserve account theme preferences.
- Original deterministic pinball physics, moving targets, elevated crescent ramps, return lanes, aimed-launch skill shots, three authored mission routes and terminal results.
- Desktop, gamepad and XR input adapters, explicit pause/resume, practice, HTML/in-world comfort controls, optional original synthesized audio and resource cleanup.
- Account-owned server progress, strict matching TypeScript/Pydantic schema, bounded requests, session CSRF, bearer scopes, optimistic revisions, reset tombstones and account-deletion cascade mapping.
- Explicit save/resume choices, conflict handling, memory-only continuation, stale-response cancellation and save-aware room/browser navigation.

## Local verification

| Check | Observed result | Limit |
|---|---|---|
| Focused frontend slice, button and Docker-import ratchets | 114 tests passed across 14 files | Pure model, synthetic DOM and mocked graphics/audio; no actual browser/GPU |
| Existing member bootstrap/router/App smoke slice | 28 tests passed across four files | Synthetic DOM; not an authenticated running app |
| Python schema/model/store/router/migration slice | 25 unittest methods passed | Fake sessions/authentication and direct endpoint invocation; no database/server |
| Production member bundle | Passed | Static compilation only; existing large-chunk warning remains |
| Member TypeScript | Passed | Includes test source |
| ESLint / Prettier / CSS tokens | Passed; zero CSS violations | No baseline increase |
| API-envelope / Python undefined names / syntax compile | Passed | No runtime qualification inferred |
| Disposable-capture fencing and backend fixture | 18 pure tests and workflow-selection guard passed | Local checks use fake transports; actual capture status below |

The primary frontend command scopes Vitest to `src/pages/pinball`, `LibraryRoom.test.tsx`, `LibraryRoomGame.test.tsx`, `roomSceneGame.test.ts`, `buttonLanguage.test.js` and `dockerStagedImports.test.ts`. Python uses `python -m unittest discover -s tests/pure -p 'test_room_game_*.py' -v`. The production bundle was written to an ignored evidence directory, without replacing served assets.

One deterministic replay uses seed 4, both flippers held during the first 27 ticks of each 60-tick period, and a launch whenever ready. It reaches the 99-step finale through ordinary simulation inputs, without positioning balls or injecting progress. This is a reachability check, not a measurement of human session length or real frame rate. The 15–30 minute pacing target remains subject to human playtesting.

## Independent review follow-up

| Finding | Disposition |
|---|---|
| Retry-read race could overwrite an existing save | Fixed; pending-load commands gated, busy notification emitted, current local-run choice evaluated at fulfillment |
| Offline pause could strand a memory-only run | Fixed; explicit continuation preserves the persistence block |
| Hardware resume bypassed session/station guards | Fixed; delegated session commands and station-bound simulation |
| Catalog query changes triggered exit warnings | Fixed; only pathname exits block; Back cancellation covered |
| Visit lifetime and live account-theme following | Fixed; close resets visit, theme transition uses save-aware flow |
| Score clipped by fixed camera; target progression unclear | Fixed in pure projection checks for desktop/narrow widths and three comfort modes; symbols/current objectives added; actual captures pending |
| Missing authored mechanics/practice | Added, with focused checks and shared mission content; real visual/play review pending |
| Empty/incomplete capture fixture | Harness expanded to populated collection scope, real selection, HTTP denial/isolation/CAS, saved reload, network failure, reset, seeded and played results; execution pending |

Deferred minor: acknowledgement text can say “Progress saved” while a newer checkpoint is already dirty. Dirty-state tracking and exit guards continue to retain that distinction.

## Remaining acceptance

Qualification [45104376838](https://github.com/cephyrixzyth/Oneirodex/actions/runs/45104376838), source `dc6e10047d0771386fce56b33eee3dacbcfeaf17`, passed frontend/build, migration/drift, all ten native request/PostgreSQL/deletion tests, 25 pure Python checks and capture fencing. Actual `startweb.sh` startup, authenticated populated catalog selection, observatory visit, launch and nonzero-tick progress save succeeded. Earlier clean-start migration adoption and room-selection defects have focused regression coverage.

The browser job remains **failed** at its bearer write-scope assertion: it used Playwright's signed-in session cookie jar alongside the restricted token. The shared resolver prefers the valid session, so this did not isolate bearer scope enforcement. The harness now uses the existing owned, cookie-free HTTP transport for those writes; its new body/identity transport regression failed before implementation and passes afterward. Live denial, subsequent reload/failure/result/CAS steps still require a successful run.

Follow-up [45106012467](https://github.com/cephyrixzyth/Oneirodex/actions/runs/45106012467), source `8e6b3b56`, passed those bearer/body denials, saved reload/resume, settings persistence, outage handling with an actual cancelled leave dialog, seeded result display and reset. It failed the 150-second normal-play result bound while still running on the third ball. A pure input-only replay of the recorded seed reaches game-over at 6,088 ticks (50.73 simulation seconds); software rendering stretches wall time because catch-up is bounded. The harness now allows at most 240 seconds and records elapsed time plus a fixed checkpoint projection. Natural browser results, teardown and concurrent HTTP writes remain pending.

Inspection also confirmed that the table backboard and game menu obstructed catalog covers at the library station. A ray-cast regression failed before correcting the desktop overview; it now checks all four cover centers and their top/bottom edges. The game menu is visible and ray-selectable only at the table station. XR eye positioning and the fixed desktop playfield camera remain separate. Actual captures of this layout correction are pending.

This attempt produced actual reading/library room images, not a complete benchmark capture set. The artifact ZIP SHA-256 is `bc7646ab1d6baf0236ea0d11c33a33e246de2308b44fcff14f75ac488f7481a9`; its manifest image hashes were checked before inspection. Chromium reported software rendering; its four frame samples had median 733.2 ms and p95 766.7 ms. Those poor software-renderer measurements do not establish desktop/headset performance. The focused run checked Tideglass only; the earlier separate eight-theme/populated-page baseline is retained in run [45070330759](https://github.com/cephyrixzyth/Oneirodex/actions/runs/45070330759).

1. Run the actual manual disposable-CI visual job and inspect its source-bound captures and report. No local app/database/browser run substitutes for this gate.
2. Finish browser-driven HTTP denial/isolation, simultaneous writes and account transitions. Ten real native/PostgreSQL/migration/deletion checks have passed; that does not imply these later browser steps passed.
3. Review the actual room, table readability, results and failure states against the concept direction; revise defects found.
4. Measure real desktop/headset frame timing and comfort on available hardware. Software-rendered CI metrics do not satisfy hardware targets.
5. Human playtest mission pacing, aiming and replay value, then accept the first benchmark before starting the other seven games.

No merge, release, version bump or deployment is authorized by this benchmark report.
