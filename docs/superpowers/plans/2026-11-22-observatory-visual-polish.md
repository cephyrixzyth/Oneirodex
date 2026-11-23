# Observatory visual polish implementation plan

> **Doc status:** Active
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Preserve the current checkout and unrelated files.

**Goal:** Correct the rejected Aurora/Moonfall visual benchmark to deliver realistic-looking architecture, furniture, instruments, table hardware, materials, lighting and shadows throughout. The owner explicitly clarified that everything should look more realistic.

**Architecture:** Keep the approved Three.js/WebXR world and functioning game/progress contracts. Add a locally bundled, provenance-recorded material set, reflection lighting, detailed original hero geometry and furniture-integrated displays. Judge actual in-engine renders before repeating the long gameplay qualification.

**Tech stack:** Existing React/TypeScript/Three.js, original geometry and SVG art, CC0 scanned material maps; existing disposable CI.

**Spec:** [Approved eight-world design](../specs/2026-11-22-library-room-worlds-design.md), especially materials, architecture, composed lighting and rejected-benchmark revision. The owner rejected the initial rendered benchmark as too basic; this pass corrects that existing requirement.

## Global constraints

- Only C:/Apps/Oneirodex. Preserve history, ignored files, root .env and the immutable released 1.3.3 installation.
- No local actual backend/database/browser/GUI/game execution or provisioning. Pure/fake checks and builds remain allowed; actual previews run only in disposable CI.
- Preserve game rules, validated progress schema, auth/CSRF/scope, account isolation, catalog selection and cleanup. No dependency or version changes are planned.
- Aurora remains walnut, emerald upholstery, brass, a moonlit dome and aurora windows. Other seven rooms retain their current status until this benchmark is accepted.
- Reference images are art direction only. Use original meshes/art and explicitly licensed material assets with local URLs, hashes and provenance; no runtime third-party requests.
- Existing commit/push/CI authorization applies to the benchmark review branch. No merge, release or deployment.

## Review focus

1. Late texture/environment loads after switching rooms must not resurrect resources or mutate a later member's scene.
2. Rich surface detail must survive Low quality without hiding gameplay targets or silently lowering the game's simulation accuracy.
3. Actual cover artwork, table score and target identity must remain readable under physically lit surfaces and reflections.
4. Detailed geometry and contact shadows must be owned/disposed, with draw-call cost and texture sizes recorded rather than inferred from triangle count.
5. Entry, library, reading and table views must show coherent architecture and actual dimensional objects; a richer background image cannot satisfy this.

## Task 1: Material and reflection foundation

**Files:** new `frontend/member-app/src/pages/roomMaterials.ts`, `roomLighting.ts`; relevant focused tests; local material assets/provenance under `oneirodex/static/newstyle/rooms/aurora/`; modify scene/geometry ownership only where needed.

- [ ] Write RED checks for sRGB colour maps versus linear normal/roughness maps, bounded repeat/anisotropy, same-origin paths and resource disposal. Confirm the failure before implementing.
- [ ] Bundle selected CC0 walnut/floor/textile maps at bounded size with SHA-256 and license/source records. Implement role-based materials, retaining a usable fallback while maps load.
- [ ] Add an owned prefiltered lighting environment, warm fixture / cool sky balance and bounded contact shading. No per-frame environment capture.
- [ ] Run focused material/geometry/scene tests, typecheck and lint. These checks do not establish visual quality.

## Task 2: Authored table and room detailing

**Files:** `pages/pinball/render.ts`, original playfield artwork, `roomObservatory.ts`, small focused art modules if needed, `roomScene.ts` signage/case mounting, geometry tests.

- [ ] Pin actual gameplay/render alignment and cleanup before adding ornamental meshes. Add a regression where rich artwork could hide a moving target or score.
- [ ] Build a shaped cabinet, metal trims/fasteners, real inset playfield art, layered mechanisms, dimensional covers and instrument details. Preserve the actual colliders and moving targets.
- [ ] Compose the architectural envelope and furniture, believable texture scale and cabinet joinery. Replace floating billboard-like control surfaces with bounded mounted displays; retain accessible HTML equivalents.
- [ ] Run affected tests GREEN, the existing frontend slice, typecheck, CSS/button ratchets and production build.

## Task 3: Actual visual preview and acceptance

**Files:** existing disposable CI workflow/capture helpers, benchmark evidence, user guide and retained actual media.

- [ ] Provide an explicitly labelled visual-only CI mode for entry/library/reading/lounge/table views, without claiming the previous full game qualification on changed source.
- [ ] Push the review source and capture actual in-engine images; inspect composition, surfaces, geometry, lighting and readability. Fix demonstrated visual defects before broad qualification.
- [ ] Complete one fresh whole-change review as required by executing-plans, address Important findings with focused regression checks, then run the complete existing focused benchmark CI on the final source.
- [ ] Update docs/receipt/media with actual pass/fail/unknown results. Present real renders for human review; leave physical hardware and final visual/gameplay acceptance open.

## Execution record

Private working ledger remains `.artifacts/library-rooms-20261122/execution.md`. The owner's clarification replaces the initial stylized-realism assumption with a realistic finish throughout the approved cozy observatory. Fantasy is in the aurora setting; objects, materials, proportions, mounts and illumination must be physically convincing. The owner has not accepted a finished visual result. A material/model pipeline alone is not acceptance.
