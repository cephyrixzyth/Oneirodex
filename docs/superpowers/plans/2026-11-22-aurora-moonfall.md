# Aurora Observatory and Moonfall Pinball Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Doc status:** Active

**Goal:** Build the first complete themed library room and its original, replayable pinball game, with identity-bound saved progress and honest verification evidence.

**Architecture:** Keep the existing on-demand React/Three.js/WebXR room. Add an original observatory geometry module and a deterministic pinball model with a matching Three.js table, a single runtime/input adapter, an accessible HTML control surface, and a native progress API backed by a per-user ORM table. Keep the other seven room/game builds outside this first-pair plan.

**Tech Stack:** Existing TypeScript, React, Three.js 0.180, Vitest, Python/FastAPI/Pydantic, SQLAlchemy/Alembic/Postgres. No new package dependency is planned.

**Spec:** [Approved eight-world design](../specs/2026-11-22-library-room-worlds-design.md).

## Global constraints

- Work only in the current Oneirodex checkout on the feature branch. User instruction overrides worktree guidance. Preserve unrelated untracked and ignored operator material. Never read or overwrite root .env.
- Human explicitly approved planning and building the first pair. Execute inline without another design approval. Preserve the later benchmark review gate before multiplying the other seven games.
- On November 22 the owner explicitly authorized a commit, push to `codex/aurora-moonfall-benchmark`, and disposable CI/browser qualification. Merge, release and deployment remain outside that authorization. The completed 1.3.3 ship is immutable.
- No local real app/backend/database/browser/GUI/keyring/installer/game runtime provisioning or execution. Pure model/fake/AST tests and compilation are allowed. Actual app/DB/browser visual and end-to-end checks need explicitly disposable CI and authorized source publication; leave evidence gates open until run.
- First pair only: default Oneirodex observatory and game ID `moonfall-pinball`; no placeholder playable buttons or completion claims for the seven future games.
- Preserve catalog selection/favorites/page callbacks, same-origin assets, scene disposal and XR teardown. Keep dark mode, readable text and an ordinary library fallback.
- Progress: authenticated user only, CSRF on session mutations, bearer library scopes, allowed game IDs, 64 KiB request bound, strict versioned finite-number schema, optimistic revisions and account deletion cascade. No private persistent browser caching.
- No commercial game/music/model assets, external analytics, new engine, multiplayer or shared competitive score claims. The concept sheet is art direction, not an application screenshot.

## Review focus

1. A high-speed ball crosses a thin rail/flipper in one frame: fixed substeps and swept/segment collision must prevent tunneling; test a legitimate rebound and the deliberate bottom drain.
2. A slow/stalled ball, a full browser suspension or huge time delta: bounded catch-up, manual pause and safe recovery must not invent extra time, scores or balls.
3. A different account, stale save revision or delayed response after room disposal: isolate member data, preserve conflicts and ignore obsolete results instead of overwriting another run.
4. A theme/room change, XR end, focus loss or context loss mid-run: pause and preserve a resumable snapshot; release input and resources; require explicit resume.
5. An inaccessible or failed render/audio/controller/save capability: retain keyboard/HTML controls, visible save status, a normal library exit and honest failure messages.

## File map and shared interfaces

- `frontend/member-app/src/pages/pinball/model.ts`: pure deterministic game state and fixed-step physics/rules.
- `frontend/member-app/src/pages/pinball/table.ts`: shared normalized board/collision/target geometry constants; render and physics consume the same layout.
- `frontend/member-app/src/pages/pinball/model.test.ts`: rules, physics, save determinism and failure cases; no WebGL/app start.
- `frontend/member-app/src/pages/pinball/render.ts`: original 3D table and ball/flipper/mission display, `createPinballTable(): {group, update(state), dispose()}`.
- `frontend/member-app/src/pages/pinball/runtime.ts`: `createPinballRuntime(onSnapshot)` owns input/accumulated fixed steps, pause/resume, snapshot/restore and teardown; no fetch or React dependency.
- `frontend/member-app/src/pages/roomObservatory.ts`: original architecture/furniture/sky, `furnishObservatory(scene)` returning an update/dispose controller; no account or game rules.
- `frontend/member-app/src/pages/roomScene.ts`: central render/XR loop, visited room selection, existing library gallery and explicit pinball station; exposes game controls without making the React component step physics each render.
- `frontend/member-app/src/pages/pinball/progress.ts`: typed progress HTTP transport and revision ownership; shared `csrfHeaders` and `errorFromResponse`, no API token handling/localStorage saves.
- `frontend/member-app/src/pages/pinball/MoonfallPanel.tsx`: instructions, saved-run choice, controls/settings, accessible HUD, pause/resume/restart/results and saving/conflict state. Panel lifecycle owns account-scoped network requests.
- `frontend/member-app/src/pages/LibraryRoom.tsx`: room chooser, first-class default room and catalog integration; no global theme preference mutation.
- `frontend/member-app/src/pages/library-room-game.css`: token-consuming game/room controls imported by the component.
- `oneirodex/schemas/room_games.py`: strict original-game progress schema and save/delete request envelopes.
- `oneirodex/models/room_games.py`, `oneirodex/models/__init__.py`: per-user/game progress table and model export.
- `alembic/versions/6a7b8c9d0e1f_room_game_progress.py`: new table, parent revision `25b9de680b91`, cascade FK to users.
- `oneirodex/runtime_native/room_games.py`, `asgi.py`: native progress router, data adapter and mount.
- `tests/pure/test_room_game_schema.py`: standalone unittest validation tests, no app or DB creation.
- `tests/test_native_room_games.py`: fake-data router tests for disposable CI only.
- `tests/test_room_game_progress.py`: real DB revision/cascade tests for disposable CI only.
- Account-deletion evidence manifest and `tests/test_user_deletion_inventory.py`: add the new cascade FK to the exact inventory and populated fixture coverage.
- Existing user/theme/room docs and an original-game user guide: behavior, limitations and evidence; actual captures remain a separate qualified gate.

## Task 1: Deterministic playable pinball model

**Interfaces:** `newMoonfall(seed?:number): MoonfallState`; `stepMoonfall(state, input: {left:boolean,right:boolean,launch:boolean}, seconds:number): void`; `validateMoonfall(value:unknown): MoonfallState`; `moonfallMission(state): string`. Serializable state contains version1, uint32 seed/RNG state, phase (`ready`, `playing`, `game-over`, `complete`), tick, score/best, balls remaining, up to three balls (id/x/y/vx/vy), three mission hit counters, combo timer/count and earned-extra-ball flag. Bounds in the Python schema must match the TS validator.

- [x] Write tests for a fresh three-ball game; launch once per edge; gravity/restitution; active left and right flippers; scoring cool-down; all three missions/finale; extra ball once; exhausted balls; zero/negative/huge delta; finite-state rejection; immutable save round trip and deterministic continuation.
- [x] Run `npx vitest run frontend/member-app/src/pages/pinball/model.test.ts` from the root; observe missing-module/behavior RED before implementation.
- [x] Implement shared board geometry, substepped circle/segment collisions, deliberate bottom drain, input edge handling and deterministic rules. Maximum simulation catch-up is 0.1 seconds per runtime frame; fixed model step 1/120 second; no unbounded while loops. Keep the visual ramp lanes and their sensors in the shared layout.
- [x] Implement missions **Establish orbit**, **Lunar routes**, **Aurora finale** with progressively lit target sequences and explicit completion. Add a documented stalled-ball recovery with a limited recovery charge, never a silent score/extra-ball generator. Keep launches/flippers responsive and controls understandable.
- [x] Run the full model test slice GREEN, then simulate a seeded sequence through a result state and save/restore boundary. Record actual results in the execution ledger.

## Task 2: Progress schema, storage and native API

**Interfaces:** `RoomGameProgress` uses composite PK `(user_id,game_id)`, cascade FK, revision integer, versioned JSON state, updated_at. GET returns `{game_id,revision,state,updated_at}` with revision0/state null when absent; PUT consumes `{revision,state}` and returns the next revision; DELETE consumes `{revision}` and deletes only that member's matching revision. Conflicts return HTTP409 with a defined shared error code, never a silent overwrite. Only `moonfall-pinball` is implemented/allowed now.

- [x] Write standalone unittest schema RED cases for NaN/Infinity, bool-as-number, out-of-bounds coordinates/counters, unsupported version, unknown keys/game ID, too many balls and malformed request envelope; include a valid active and completed run. Run `python -m unittest discover -s tests/pure -p test_room_game_schema.py` before adding the schema.
- [x] Implement matching strict Pydantic schema, model and migration. Add the model export, exact FK inventory/fixture counts and evidence manifest row. Use the existing native model/session conventions.
- [x] Write fake router tests for unauthenticated access, inactive/revoked identity, missing read/write scope, missing/bad CSRF, oversize streamed bodies, invalid saves, account isolation and stale revisions. Add real Postgres tests for compare-and-swap races, insert races, read/replace/delete, and actual user-deletion cascade.
- [x] Implement `create_room_games_router(...)` and `mount_room_games_routes(...)` following the adjacent account preferences router's injected auth/database-scope adapter, bounded body reader, shared envelopes, security headers and session renewal. Enforce auth before revealing row presence; never return raw validation values/driver exceptions or file paths.
- [x] Run pure schema GREEN and Python compile/undefined-name checks locally. Mark actual router/DB tests pending disposable CI rather than executing a local server or DB.

## Task 3: Actual observatory and pinball table geometry

**Interfaces:** `furnishObservatory(scene)` adds independently authored curved library/dome/window/furniture with explicit lifecycle; `createPinballTable()` renders the same `table.ts` layout used by physics. Geometry uses original shapes, bounded textures and repeatable construction, not an image pasted over the room.

- [x] Add pure scene-contract tests using Three.js objects without a WebGL renderer: default/aliases map to `oneirodex`, observatory contains named major architecture/fixtures, table colliders/targets share the model layout, disposal is repeatable and lighting/mesh counts are bounded.
- [x] Observe RED; implement a curved/domed observatory, continuous aurora view, crescent/brass fixtures, walnut shelving, emerald seating, orrery/telescope and table. Author bevels, arcs, cylinders/lathe profiles and material differences. Reuse appropriate repeating details without turning everything into a cube.
- [x] Replace the default-only generic shell/furniture path; keep the other seven legacy rooms working. Preserve the actual authorized four-title shelf/detail callbacks and allow page/search/favorite access through existing library controls.
- [x] Build table rails, flippers, ball shadow, lit mission targets, orbital ramp lanes and original scoring/mission displays, with low/standard/high quality knobs. Pause nonessential motion under reduced-motion/hidden states.
- [x] Run pure Three geometry tests GREEN, member typecheck and source/asset/license checks. Record that visual quality/performance are not established by object-count tests.

## Task 4: Runtime, controls and room integration

**Interfaces:** game controller exposes `start(state?)`, `input(action,pressed)`, `pause()`, `resume()`, `snapshot()`, `tick(seconds)`, `dispose()` and an explicit status callback. Extend room engine with these methods and `move('pinball')`; preserve existing station methods. Controls release on blur, controller disconnect and every teardown.

- [x] Add fake-scheduler runtime tests for bounded catch-up, pause/resume, held/released input, ball/result snapshots, XR end/visibility/context loss, restore-paused behavior and idempotent cleanup; observe RED.
- [x] Implement one scene animation loop for desktop/XR, driving only active simulation. Keep pose changes explicit on station selection and never follow the ball with the room camera. Stop closed/hidden room work and expose real recoverable rendering errors.
- [x] Build keyboard/mouse/gamepad/XR mappings for left/right flippers and launch. Provide large reachable in-world controls and an HTML equivalent, with Escape pause, explicit resume, text/contrast/reduced-motion/volume settings, fixed-camera play and instructions/practice.
- [x] Add a room chooser defaulting to the account theme, plus **Follow my theme**. Visiting `oneirodex` does not change account preferences. Seven other choices retain their existing room behavior and do not advertise implemented original games.
- [x] Extend LibraryRoom integration tests with mocked renderer/controller to prove catalog callbacks, theme visits, unavailable rendering/headset, focus return and cleanup still work; run runtime/React tests GREEN, typecheck and CSS/button ratchets.

## Task 5: Account-scoped saving, result flow and usable game session

**Interfaces:** progress transport accepts AbortSignal and the known revision, rejects non-success with shared API error helpers and carries CSRF headers. UI states distinguish loading, ready-to-start, saved-run available, playing, paused, results, saving, saved, unsaved, denied and conflict. A server-rejected identity clears private game state and stops simulation.

- [x] Add transport/panel tests RED: saved run is never resumed automatically; restart requires deliberate action; delayed responses from another member/closed room are ignored; autosave coalesces; offline failure retains in-memory play and marks unsaved;409 offers reload/discard without silently overwriting;401/403 pauses and clears identity state.
- [x] Implement load/resume/start flow, checkpoint and bounded periodic autosave, explicit reset/delete revision handling, unsaved-navigation confirmation and per-member personal best. No browser persistence for private run state; no fetch per frame. Update instructions, mission progress and results so a real session is understandable.
- [x] Run model/runtime/transport/panel/library slices GREEN, verify consistent TS/Python save schema fixtures, and compile/typecheck. Review ordinary success and every error result before accepting.

## Task 6: Verification, documentation and benchmark review

- [x] Run only relevant pure/fake checks plus app compilation, API envelope, CSS-token/button ratchets, lint/format, Python compile and undefined-name checks. Check dependency files unchanged and the release still points to immutable 1.3.3; no version bump is part of this local feature build.
- [x] Prepare a disposable-CI real room/game qualification using the existing native populated fixture and real start script. Exercise authenticated progress, two-member isolation, bad CSRF/scope/body, save/reload/resume, deletion and network failure; exercise a real browser/table physics session, forced loss/result, graphics options and teardown. No fabricated successful API bodies. Seeded debug input belongs only in the disposable harness, not an unauthenticated product debug route.
- [x] Capture the actual populated observatory at entry/library/table and actual Moonfall gameplay/results at the verified source SHA. Inspect images against the approved concept. Record the seed, frame timings, settings and errors. Inventory real desktop/headset availability read-only; leave missing hardware checks open and never infer them from CI software rendering.
- [x] If source publication is needed for CI, first make the local diff/test results concrete and reviewable, then obtain any missing commit/push authorization. Do not substitute local backend/browser execution.
- [x] Update existing theme/preferences docs and add `docs/user/library-room-games.md` for the first implemented game, controls and save/error behavior. Record completed and pending evidence; refresh applicable README media only after qualified actual captures.
- [x] Use the executing-plans fresh whole-change review, fix important findings with RED/GREEN checks, and re-run only affected gates. Preserve the ledger and user files. No task is complete solely because a reviewer says so.
- [x] Present the actual room/game benchmark for human review. Do not start building the other seven games or ship/deploy this feature on the strength of concept art or partial checks.

## Execution ledger

Current verification and remaining acceptance: [benchmark evidence](../../dev/parity-evidence/aurora-moonfall-benchmark-2026-11-22.md). Source 89988495 passed disposable CI 45108321289, including actual results, failure handling, teardown and concurrent writes. Captures and a source-bound receipt are retained. Hardware/controller/headset qualification and human visual/pacing acceptance remain open; checked capture/presentation steps do not imply human approval.

The ignored working ledger is `.artifacts/library-rooms-20261122/execution.md`. Record task, source base, actual RED/GREEN commands/results, design rulings, changed files, runtime restrictions and remaining acceptance there. Keep private/operator material out of tracked evidence.

Fresh whole-change review identified eight Important findings. Their fix pass has focused regression coverage, and the final disposable CI passes the authored real browser/database checks. Tasks1–5 implement the first pair; task6 records automated qualification and presents actual captures. The other seven games remain deferred by the approved benchmark-first sequence. Physical hardware and human visual/gameplay acceptance are not inferred from reviewer comments or CI.

Automated qualification and documentation are complete for the first benchmark. Human acceptance and hardware evidence remain gates before the other seven games. The authorized outcome is a preserved, pushed review branch, with no merge or deployment.
