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
| Score clipped by fixed camera; target progression unclear | Fixed in pure projection checks for desktop/narrow widths and three comfort modes; symbols/current objectives added; actual table captures inspected |
| Missing authored mechanics/practice | Added, with focused checks and shared mission content; real visual/play review pending |
| Empty/incomplete capture fixture | Passed populated collection selection, HTTP denial/isolation/CAS, saved reload, network failure, reset, seeded and normally played results in disposable CI |

Deferred minor: acknowledgement text can say “Progress saved” while a newer checkpoint is already dirty. Dirty-state tracking and exit guards continue to retain that distinction.

## Engineering decisions and limits

| Decision | Reason and cost if wrong |
|---|---|
| Execute inline in the required checkout; preserve history and unrelated files | Honors workspace restrictions; shared-checkout edits require careful file ownership and diff review |
| Wait for explicit publication authority, then keep this on the review branch | Owner authorized commit/push/CI only; qualification takes longer than local runtime testing, but production remains unchanged |
| Use a purpose-built fixed-step simulation without another physics dependency | Bounded original table; replacing the model would require save-schema and physics requalification |
| Keep a null-payload revision tombstone on reset | Prevents stale saves from restoring erased payload; revision metadata persists until account deletion |
| Use React Router's data router for navigation blocking | Avoids history monkeypatches; broad routing regression risk is covered by the existing bootstrap/router slice, not claimed eliminated |
| Expand 12 prototype shots to 99 authored steps with ramp/return/skill requirements | Adds session depth; human pacing and difficulty may still need substantial tuning |
| Use focused disposable CI and retain the separate full page/eight-theme baseline | Limits repeated unrelated work; focused success cannot establish full-repository or all-theme parity |
| Isolate bearer checks from the browser cookie jar | Exercises the intended restricted identity; no product authentication precedence change was made |
| Use a fixed raised desktop library overview and station-only game menu | Clears catalog sightlines while preserving table/world coordinates; the camera height remains a visual preference for human review |
| Bound software-rendered play time and record a smaller gameplay viewport separately | Preserves real input/result assertions within CI limits; these measurements cannot qualify hardware performance |

Missing headset comfort, physical controller and human pacing evidence remains open. Pure geometry, simulation and software-browser checks are not substitutes for those observations.

## Disposable CI qualification

[Run 45108321289](https://github.com/cephyrixzyth/Oneirodex/actions/runs/45108321289) **passed** at source `8998849586a3f3db5cca6344ddbf64ac8dff0f12`. The later evidence commit changes documentation/media only. The [retained receipt](aurora-moonfall-ci-2026-11-22.json) records source identity, measurements, artifact SHA-256 and published image hashes.

| Actual check | Observed result |
|---|---|
| Frontend / build | 142 tests across 18 files, member typecheck and all five SPA builds passed |
| Native / PostgreSQL / deletion | Ten checks passed; Alembic upgrade and drift check passed, including clean-start adoption |
| Pure / capture safety | 25 Python methods and 18 capture/fixture methods passed; workflow-selection guard passed |
| Real startup / catalog | Owned startweb.sh listener, authenticated synthetic 14-title catalog selection, observatory visit and reading station |
| Actual launch / save / reload | Nonzero tick and launched ball persisted; explicit saved-run resume and quality/motion/contrast persistence passed |
| Denials / isolation | Anonymous 401, restricted read/write 403, peer save isolation, malformed JSON 422, oversized body 413 and session CSRF denial passed |
| Outage / reset | Aborted requests retained the run; actual leave dialog cancelled; seeded result display and payload reset passed |
| Normally played result | No result injection: game-over at tick 5915, zero balls, score 2800; 164.69 seconds wall time, 1000x800, Low quality, within the 240-second bound |
| Teardown / concurrent writes | Canvas detached after close; simultaneous HTTP writes returned 200/409; no page exceptions; owned backend/database cleanup verified |
| Images | Four actual populated captures retained, hash-checked and inspected; human visual acceptance remains open |

The result checkpoint corresponds to about 49.29 simulation seconds, not human session length. The receipt's saved_seed is the mutable RNG at the earlier saved checkpoint, not the original seed. A separate pure default-seed replay naturally loses after 47.73 simulation seconds; input timing changes moving-target interactions.

Full-size 1600x900 captures used software WebGL. Four sampled frame intervals had median 1150.1 ms and p95 1849.8 ms: poor software-renderer results, not a hardware performance pass. Only the long normal-play probe used the recorded 1000x800 viewport. The focused run checked Tideglass only; the separate full page/eight-theme baseline remains in [45070330759](https://github.com/cephyrixzyth/Oneirodex/actions/runs/45070330759), not counted as a new all-theme pass.

Actual images: [library overview](../../media/library-room-benchmark-2026-11-22/observatory-library.png), [reading desk](../../media/library-room-benchmark-2026-11-22/observatory-reading.png), [paused table](../../media/library-room-benchmark-2026-11-22/moonfall-paused.png), [normally played result](../../media/library-room-benchmark-2026-11-22/moonfall-played-result.png).

## Confirmed follow-ups during qualification

- Clean-start ORM adoption attempted to create an existing table. The migration now adopts it; pure and real PostgreSQL regressions pass.
- Pending visits and reused disposed canvases had independent synthetic regressions. Latest intent, immediate chooser state and per-world canvas ownership are covered. The live locator timeout also required an explicit accessible name.
- Bearer controls initially shared the signed-in browser cookie jar. The harness now uses the owned cookie-free transport; no product authentication precedence changed.
- Autosave failure could pause before the harness clicked Pause. The harness now waits for the actual failed-save state and verifies the leave dialog.
- Fixed two-second frame sampling and short normal-play wall limits were unreliable on software rendering. Bounded observed-frame sampling and a separately recorded smaller gameplay viewport retain actual input/result assertions.
- Actual captures exposed catalog covers behind the table and a large game menu in the library view. The corrected desktop overview and station-only menu have ray-cast regression coverage and inspected actual images. Camera height and visual quality still require human acceptance.

## Remaining acceptance

1. Human review of the actual room, reading station, table readability and results against the concept. CI does not accept the visual design.
2. Real desktop/controller/headset frame timing, input usability and comfort. Read-only inventory is retained privately; no local app/browser/game execution was performed.
3. Human playtest the 15-30 minute pacing target, aiming, difficulty and replay value; accept the first benchmark before the other seven games.

These focused checks do not establish full-repository parity/security or a full-suite pass. No merge, release, version bump or deployment is authorized by this benchmark report.
