# Eight library rooms and eight original games

> **Doc status:** Reference
> **Design status:** Human approved on 2026-11-22: plan and build the first room/game. Approval covers the eight-world direction and benchmark-first execution; not an implementation or shipping claim.

## Intent and decisions

The library rooms should be places worth spending time in: visually convincing interiors with the collection integrated into their furniture, and a substantial original game belonging to each space.

The human explicitly requested online reference research, stronger 3D rooms, games inside them, and a room that expresses each theme. They chose games substantial enough for a whole session and selected **eight rooms with eight distinct games**.

The human subsequently approved this design and selected **plan and build the first room/game**, Aurora Observatory and Moonfall Pinball. The other seven pairs remain sequenced after the human review of that finished benchmark.

This is a substantial feature program. Complete one room and one game as a quality benchmark, then build the other seven against that standard. Each finished pair must be independently reviewable. Completing a framework, a static room or a playable demonstration does not complete a pair.

## Approaches

1. **Chosen:** eight individually authored rooms and eight mechanically distinct games, sharing rendering, input, lifecycle, persistence and suitable low-level simulation. Strongest variety and theme identity; largest content and verification scope.
2. Eight individually authored rooms with three deeper shared games and themed variants. Less implementation work, but repeated mechanics between rooms. The human selected the first approach.

Keep the existing React/TypeScript/Three.js browser stack and optional WebXR entry. A separate Unity/Unreal application would fragment library access, introduce another deployment/install path and replace the existing browser experience; it is not proposed.

## Existing behavior to preserve

`LibraryRoom.tsx` loads the scene on demand and shares selection, favorites, catalog scope and server pagination with the ordinary library. It offers desktop operation, headset entry, seated/close-reach comfort, larger reading text and a usable catalog when the room cannot load.

`roomScene.ts` currently constructs a shared box-shaped room with a small library wall, reading station and lounge; `roomFurnishings.ts` mostly varies finishes and a few props. The default theme falls through to greenhouse furnishings. The lounge's themed WebP is a picture panel rather than a different 3D interior. These observations are static source findings.

Preserve catalog authorization and pagination, same-origin texture handling, stale-load protection, GPU resource disposal, focus return and XR shutdown. An unavailable game or room must not prevent access to the ordinary library.

## What every room must deliver

- A distinctive architectural silhouette and layout, recognizable in a neutral or desaturated view, with coherent furniture, fixtures and small details.
- Materials with visible depth: bevels, fabric/wood/metal/glass differences, appropriate roughness and authored or baked contact shading. Repeated plain box geometry is not sufficient as the final art treatment.
- Composed lighting with clear focal points, believable fixture sources, readable book/game cases and gentle peripheral detail. A collection display and the main attraction should be identifiable on entry.
- An exterior or distant view appropriate to the theme, plus restrained ambient movement. Sound starts only following user interaction, has separate ambience/game controls, and respects mute.
- Collection furniture containing actual authorized game artwork and metadata. Inspecting a case opens the existing detail/selection flow; there is no separate guessed launch route. Fast search, paging, favorites and return to the catalog remain available without physically handling every item.
- A physical home for its original game: a table, instrument, cabinet or console. Players enter it deliberately and can return to browsing quickly.
- A few responsive props with a clear use, reset/return behavior and optional sound. These support the room; a full general-purpose construction/physics sandbox is not part of this design.
- Theme-consistent lettering, controls, avatar display, placeholder covers and trophies. The default Oneirodex room has its own first-class identity and never aliases to Mosslight.

## Room and game designs

### Oneirodex — Aurora Observatory / Moonfall Pinball

**Space:** a moonlit observatory-library with a shallow domed ceiling, curved walnut shelves, dark green upholstery, brass crescents and a broad aurora window. The main pinball table sits under the dome; collection cases curve around the walls and a quiet reading alcove faces the sky. A small orrery and adjustable telescope provide secondary interactions.

**Game:** an original gravity pinball table with a crescent-shaped upper playfield, ramps, return lanes, moving orbital targets and a controlled black-hole capture/release feature. Responsive flippers, predictable drains, ball recovery and readable scoring take priority over visual effects.

**Session:** three balls, skill shots and a sequence of three missions: establish orbit, complete lunar routes, then light and finish the aurora finale. Earn extra balls through explicit table achievements, not purchases. A complete run ends when the balls are exhausted or the finale is completed; repeated runs pursue better scores and mission mastery. A run should be engaging for roughly 15–30 minutes once learned, with shorter failed attempts accepted.

**Controls:** separate left/right flipper actions and launch; keyboard, mouse buttons, gamepad and XR controller mappings. Large reachable virtual buttons provide an alternative to physical reaching. No forced camera following the ball.

### Mosslight — Conservatory Library / Glasshouse Keeper

**Space:** a glass-roof conservatory with planted bays, warm walnut shelving, climbing foliage, water channels and a potting workbench. Outside light filters through leaves; the interface remains dark and legible. Plants and furniture change the room's silhouette, not merely its color.

**Game:** a strategy board at the potting bench. Place plants, connect irrigation and manage light, water and limited nutrient supply. Species have different needs and neighboring effects. Growing a balanced ecosystem produces resources for subsequent rounds.

**Session:** a six-day scenario with changing weather and explicit restoration goals. Day transitions are player-controlled, so planning is unhurried. Win by meeting the final ecosystem targets; lose if the limited recovery reserve is exhausted. Scenarios introduce shade, drainage and competing species, with seeded challenge runs after the introductory sequence.

**Controls:** select/place/rotate/inspect through a common pointer or focus cursor; every drag has a select-then-place alternative. This is a resource strategy game, not a daily real-time maintenance obligation.

### Afterglow Arcade — Midnight Arcade / Ricochet Circuit

**Space:** an intimate arcade with staggered cabinet bays, shaped marquees, patterned carpet, repair details, coin-return buttons and cyan/magenta pools of light. Collection titles occupy inspectable display cabinets. The original game has a prominent dedicated cabinet; no external ROM is required.

**Game:** a top-down arena action game on the cabinet display, using bank shots, destructible cover and enemies with readable attack patterns. Choose between movement, lining up ricochets and collecting temporary upgrades.

**Session:** a sequence of five arenas, each with encounter waves and an ending challenge. Between arenas choose a meaningful weapon/defense modifier; a limited life pool creates a complete run with a final opponent and a score breakdown. Unlock further arena arrangements and difficulty settings through completion.

**Controls:** desktop movement plus aim/fire, gamepad dual-stick, and an XR cabinet control surface with stick-based movement and pointer aim. The playfield remains fixed in the cabinet; the player is never forced to move bodily through it. Include an aim-assist option.

### Graphite Studio — Precision Workshop / Marble Atelier

**Space:** an architectural studio with charcoal acoustic panels, pale work surfaces, articulated lamps, brushed hardware, drafting drawings and display plinths. A large central workbench holds the game; wall cases provide an orderly collection gallery.

**Game:** a mechanical construction puzzle. Arrange a finite set of rails, gates, ramps and deflectors to deliver marbles to ordered targets while respecting a parts budget. Marbles have consistent, inspectable motion; test, pause, revise and reset are core actions.

**Session:** at least twelve authored challenges teaching and combining the mechanics, grouped into three chapters. Completing the delivery order wins a level; dropped or stalled marbles end that test without consuming permanent resources. Optional efficiency medals and a sandbox support replay. Initial puzzles use a constrained workbench plane with visible height levels; a general 3D CAD editor is not required.

**Controls:** grid placement, rotation and select-then-place, with close inspection and a fixed overview. Simulate only the active puzzle, not an unrestricted room-wide physics world.

### Signal Room — Analog Control Room / Night Signal

**Space:** a timber-and-metal listening/control room with instrument racks, oscilloscopes, cable patch bays, amber meter lighting and acoustic treatment. Library cases occupy equipment-style racks; a mission receiver forms the primary play station.

**Game:** a signal-decoding puzzle campaign. Tune carriers, route channels and combine filters to recover messages under interference. Each stage introduces or combines a comprehensible rule; the player can inspect what every component does.

**Session:** twelve authored missions in three chapters, with a final multi-channel coordination puzzle. Failed decoding attempts return useful feedback; optional timed expert challenges are separate from the untimed campaign. Seeded interference arrangements provide repeatable challenge runs after completion.

**Controls:** accessible discrete dial steps and patch selection, not precision dragging alone. All required signal information has visual representations and captions; hearing or pitch recognition is never the only solution path.

### Tape Deck — Listening Den / Looproom Sessions

**Space:** a comfortable analog music den with rounded furniture, lavender controls, warm orange reels, record/cassette storage and a substantial mixing desk. The collection sits among original album-like displays and game cases, without copied cover designs.

**Game:** rhythm performance combined with a compact step sequencer. Build an arrangement from original stems, then play timed phrases that introduce and transform its layers. Mixing choices alter the arrangement and challenge without requiring external music.

**Session:** at least six original tracks or equivalently substantial authored arrangements, three progressive difficulty levels, a set-list mode and a freestyle sequencer. Track completion produces a clear timing/accuracy breakdown; practice supports sections, reduced speed and calibration. A three-track set is a complete session. No commercial tracks are bundled.

**Controls:** four accessible action lanes mapped to keyboard/gamepad/XR controls, plus optional virtual pads. Audio calibration, visual beat cues, manual timing offset and an untimed arrangement mode are required. Keep XR targets comfortably reachable and avoid large repeated arm swings.

### Deep Space Media — Orbital Lounge / Last Light Fleet

**Space:** a panoramic orbital screening lounge with structural ribs, silver-blue surfaces, upholstered recesses and a large tactical projection table. Slowly moving orbital scenery establishes scale; collection cases live in lit storage bays.

**Game:** a tactical defense run on the projection table. Place and upgrade modules, manage power and defend a ship through escalating enemy waves. Enemy routes and attack indicators must be readable before the player commits resources.

**Session:** ten encounters with planning breaks, two intermediate threats and a final flagship encounter. A run ends with victory or hull loss. Branching module choices and seeded encounter combinations provide replayability without persistent grinding. Pause and speed settings permit deliberate play.

**Controls:** pointer/focus selection, rotate/place, inspect and explicit start-wave action. The player stays in the lounge looking at the tactical world; the room camera does not become a moving spaceship camera.

### Tideglass Observatory — Undersea Archive / Lantern Depths

**Space:** an undersea archive with thick circular windows, brass instruments, rounded sea-glass fixtures and tiered shelves. Exterior silhouettes, drifting particles and restrained light movement suggest water depth. The main chart table faces a broad observation window.

**Game:** a sonar exploration and route-planning expedition on the chart table. Pilot a survey drone through a revealed map, choose sonar pulses and manage battery, pressure tolerance and return routes. Discoveries reveal navigation and environmental puzzles.

**Session:** a three-zone expedition with increasingly difficult hazards and a final recovery objective. Win by returning with the final discovery; lose the expedition when the drone cannot recover safely. Saved discoveries form a personal log; generated map arrangements support later expeditions. A complete initial expedition targets approximately 20–40 minutes, adjustable after playtesting.

**Controls:** choose destinations and sonar actions on a fixed chart, with an optional close inspection view. Exploration does not require underwater first-person locomotion or motion-heavy swimming.

## Shared game contract

Every game has an introduction, actionable controls, explicit start, tutorial/practice, playable challenge sequence, meaningful win/loss or completion, pause, restart, save/resume, result summary and replay motivation. Decorative score counters and a single repetitive interaction do not meet this contract.

Games are single-player in the initial scope. Personal bests and unlocked room trophies are private to the member. All eight games are available from their respective rooms without unlocking access to the library or buying anything. Gameplay must not require importing ROMs or owning a catalog title.

Share the action/input layer, lifecycle, settings, seeded random utilities, result presentation and appropriate simulation utilities. Keep each game's rules and state separate. Changing a room theme does not mutate one game's save into another game. Request confirmation before leaving a game with progress that could not be saved.

## Navigation, comfort and accessibility

- **Room selection:** entry defaults to following the member's current UI theme. A room chooser also lets every member visit any of the eight worlds and its game without changing their account-wide theme preference. Choosing a visit changes the 3D world and its scoped game controls only; ordinary library chrome keeps the account theme. Provide an explicit **Follow my theme** action to return to that default. A visit choice lasts for the open room session; do not silently persist it as an account preference. All games remain reachable from this chooser. This resolves the builder review's navigation question as a proposed design decision.
- Desktop: mouse/keyboard plus supported gamepad; navigation can use walking or direct station travel. Pointer lock is optional and Esc releases it and pauses the game.
- XR: existing immersive entry, controller rays, teleport and snap turning. Station travel, seated/close-reach positions and recenter remain available. No automatic camera acceleration, forced smooth movement or game-driven room-camera shake.
- Each room has authored collision/navigation bounds, clear station destinations and a visible return path. Walkable space must not intersect furniture. A fixed-spot fallback is always available.
- All menus and meaningful room actions have keyboard/focus equivalents outside the canvas. Do not claim every action game is fully screen-reader playable; expose instructions, settings, progress and results through accessible HTML and document the remaining gameplay limits honestly.
- Provide reduced motion, particle/light-effect controls, readable text size, captions, high-contrast interaction cues and sound controls. No rapid strobing. Low graphics quality preserves gameplay cues.
- Losing focus, ending XR, opening a blocking menu or losing the WebGL context pauses simulation. On XR end, return to a stable desktop view with the game paused. Resume is explicit.

## Progress, identity and security

Introduce a small native backend contract for original room-game progress; do not repurpose opaque emulator state uploads or invent desktop launcher commands.

Proposed endpoints: authenticated GET/PUT/DELETE `/api/room-games/{game_id}/progress`. Exact router placement and response/error-code selection follow the existing native conventions. Use shared JSON envelopes and CSRF headers for mutations. An allowlist identifies the eight game IDs; every read/write/delete filters by the authenticated member, never by a client-supplied owner ID.

One versioned JSON progress record per member/game, with optimistic revision checks, explicit conflict handling and a 64 KiB limit. Validate each game's schema, bounded collections, finite numeric values and versions. Persist checkpoint/run state, seeded random state, personal bests, settings and unlocks; never serialize scene objects, raw executable expressions, file paths or credentials. Unknown save versions receive an honest migration/unsupported response rather than silently resetting progress.

Autosave at meaningful transitions and periodically during an active run, coalescing requests rather than sending a request per frame. Show saved/saving/unsaved status. If the server becomes unreachable, a running game can continue in memory with an unsaved warning and retry. This design does not add persistent private browser caches or claim offline resume across browser restarts. Session rejection pauses the game and clears identity-scoped private state before reauthentication. Public hashed room assets may use the normal asset cache.

These are personal scores, not tamper-proof competitive leaderboards. Save validation protects resource usage and identity boundaries; it does not claim client-submitted scores are cheat resistant. Any future shared leaderboard requires a separate trusted-scoring design.

Apply existing account deletion policy to progress and trophies: delete member data after the database transaction commits and retain the normal security/audit history. Children may save these accessible built-in games under the existing household/account rules. Operator backup retention remains a separate policy. No analytics service or external account is introduced.

## Rendering, assets and performance

Load only the selected room and active game. Load assets progressively with a stable entrance/loading view; cancel stale requests when switching and dispose old GPU/audio resources. Distinguish unknown/custom themes from the eight shipped themes: use a named neutral/default fallback that respects interface tokens and disclose the fallback, without executing uploaded room scripts.

Use original meshes, materials, audio and game rules. Appropriately licensed dependencies/assets may be proposed with provenance and size budgets. Do not copy reference-product rooms, models, branding, recordings or games. Keep public technical design separate from the private reference catalog.

Provide low/standard/high graphics tiers covering resolution, shadows, texture sizes and effects. Prefer authored/baked lighting where it helps, reuse geometry where appropriate and limit dynamic lights. Game logic uses a bounded fixed-step update and bounded catch-up; rendering may interpolate. Hidden or closed rooms stop rendering and audio, and launching an actual catalog game suspends unnecessary room work.

Provisional qualification targets, not current claims: sustained 60 FPS on the selected desktop reference device and its native available refresh target, at least 72 Hz, on the selected supported headset. Before implementation planning, inventory available test devices without provisioning software and document the exact browser/GPU/headset, quality tier, resolution and scene used. If no real headset is available, headset qualification stays explicitly open; CI/software WebGL screenshots cannot close it. The builder may tune asset budgets and internal collision techniques against those measured devices, without changing game rules or cutting required content silently.

WebXR needs an eligible browser and secure context. The current plain-HTTP NAS URL is not evidence of headset usability. Reuse the existing supported secure-access instructions; do not weaken browser security or certificates to enable XR. Desktop room use remains available.

## Delivery and acceptance

1. **Benchmark:** Oneirodex observatory plus Moonfall Pinball, including real physics/game loop, all controls in scope, personal progress, teardown and a complete authored table. Capture the actual populated library and actual gameplay. Human visual/gameplay review is required before rolling the art/content pattern across the other rooms; a rejected benchmark is revised, not multiplied.
2. **Distinct mechanics:** Afterglow/Ricochet Circuit, Graphite/Marble Atelier and Mosslight/Glasshouse Keeper. Each pair meets the same complete-game contract; shared helpers may grow only from demonstrated reuse.
3. **Remaining worlds:** Signal/Night Signal, Tape Deck/Looproom Sessions, Deep Space/Last Light Fleet and Tideglass/Lantern Depths. Rhythm/audio calibration and expedition persistence receive their own verification rather than inheriting the first game's evidence.
4. **Whole set:** theme switching, account changes, deletion, refusal/failure paths, restart/resume, graphics tiers, accessibility, supported input/device checks, release packaging and documentation/captures.

Per pair, verify:

- The actual room matches its approved theme composition at entry and from the game station; the image backdrop alone does not establish this.
- The original game can be started, taught, played to completion or loss, retried, paused, saved, closed and resumed from the same validated state.
- Test deterministic rules, boundary/collision or placement cases, state migration/rejection and one legitimate complete game path. Exercise relevant denial, network failure, account separation and teardown paths.
- Existing library selection/favorites/pagination, accessible fallback, XR exit and focus return still work.
- Measure frame timing, loading, memory/resource cleanup and input behavior on the named devices. Record source SHA, assets, run seeds, quality tier, timings, screenshots and proof gaps.
- Run the focused frontend/backend checks and existing API envelope, CSS-token and button-class ratchets for touched files. Use disposable CI for actual app/browser/DB execution while the existing local-machine restrictions remain in force.

No merge, new release, installer provisioning or live NAS mutation is implied by approval of this design. Those actions require applicable existing user authorization at that time. Preserve the published immutable v1.3.3 release and the retained deployment backup.

## Explicit exclusions

No multiplayer/netcode or shared leaderboards, unrestricted room editor, external workshop downloads, commercial games/ROMs, licensed music, general-purpose room-wide physics sandbox, forced VR, additional native engine or forced progression gate on the library. These are scope boundaries, not claims they would never be useful.

## Reference evidence and documentation

The private research catalog and source observations are retained at `.artifacts/library-rooms-20261122/research.md`. Research compared official material for explorable home environments, original VR activities, physical collection rooms and 3D library applications. Those are design references, not runtime-parity evidence or permission to copy assets.

Implementation must update the existing theme art direction, preferences/theme guide, relevant room/game user help, account deletion/persistence docs and current README media. Add a dedicated user guide for the eight original games if the existing guide cannot explain them clearly. Keep evidence statuses explicit and document supported-device and accessibility limits.

## Approval checkpoint

Fresh builder review identified one material ambiguity: whether visiting rooms requires changing the UI theme. The room-selection rule above resolves it. No other blocking design questions were identified by that review.

Human design approval received: **Approve; plan and build the first room/game**. Write the first-pair implementation plan, then execute within the current checkout and existing local runtime restrictions. The later human review of the real benchmark remains required. This design is not evidence of implemented behavior.
