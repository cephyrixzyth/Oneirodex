# Changelog

All notable changes to Oneirodex are documented in this file. Historical entries keep the former public string GameTheca where the first rewrite left it; do not restore git history.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Surprise me on Discover** (INSP-4b, H-I). One title drawn from the **top twelve** of your own taste ranking — not the whole library, which is a coin toss that mostly lands on things nobody wanted, and not the single best match, which is the same answer every time. **Another** moves on without repeating what you were just shown. Your strongest genres, read from the stored taste profile, sit beside it as chips to steer the draw. Anything you have favourited, played or marked **Won’t play** is never offered. Nothing is drawn until you ask, and pressing the button is **not** read as a taste signal — treating it as one would teach the profile that you like whatever the dice showed. A member with no profile yet still gets a pick, labelled honestly as *well regarded* rather than *picked from what you play*. `GET /api/discover/surprise`.
- **Smart collections** (INSP-29, H-I). A saved filter can now tick **Show on Collections** and appear as a shelf beside the hand-made ones — held together by its question rather than by a list of games, so it keeps up as the library grows. It is the *same row* as the saved filter (`SavedFilter.is_collection`), not a second kind of thing to build and keep in step. Opening one links into the catalog with the tree applied, which needed `LibraryApp` to learn `filter_tree` as a URL param — its query parsing is an allow-list, so without that the link would have opened on an unfiltered library and looked like the collection held everything. The section renders nothing at all until a member makes one.
- **A Build tile on Admin → Dashboard and Admin → Ops.** After a deploy there was no way to confirm from inside the product that the running code was the code that shipped: the version was a literal in `__init__.py` while a tracked `VERSION` file held the same string and nothing read it, the Alembic revision was never read back (only the table’s *existence* was checked), and no commit or build time reached the process at all — the image tag was the only build identity and it is not readable from inside the container. The tile now answers it: version, the commit and date the image was built from, the schema revision **compared against the one this code expects**, and the themes generator. The comparison is the point — a revision on its own is a hex string nobody can check by eye, while *migration pending* is an answer. `VERSION` is now the single source for the version (a test asserts the two agree), `scripts/ops/unraid_ship_update_now.py` stamps the deploying commit through a new Dockerfile `ARG`, and **an unstamped image reads *no build stamp* rather than inventing one**. Every field degrades to `null` without taking the Ops poll down, the contract the GPU tile already set.
- **A filter builder in the catalog** (INSP-3, H-I — the UI half). Under the Signals chips, **Build a filter** opens a small editor for the nested tree the backend already compiles: rows grouped as **All of** / **Any of** / **None of**, nesting allowed, with a live count of how many titles match and **Save** to keep it under a name. Applying one is a *conjunct beside* the chips, never a replacement. The field list is served from the backend registry rather than copied into the SPA, so the builder can only ever offer what the chip row already offers and cannot go stale. A flag row is **Yes / No**, not a checkbox, because a false flag means *not this* on the server and an unticked box would read as *ignore this*. When the server refuses a tree it names the offending node, and the builder outlines **that row** instead of putting "invalid filter" above a form with fifteen of them.
- **Filters that can say "or"** (INSP-3, H-I). The chip row can only ever mean *and* — tick three chips and you get titles matching all three — so a question like *VR titles that are behind, or anything imported this fortnight* had no expression at all. Filters are now a nested AND / OR / NOT tree (`utils/filter_tree.py`), and a member can **name and save one**: `GET|POST /api/filters/saved`, `PUT|DELETE /api/filters/saved/<id>`, `POST /api/filters/preview` for a live count as the filter is built, and `GET /api/filters/fields` for what a builder may offer. Saved rows are per-member (Alembic `c3d4e5f6a7b8`) — one person narrowing their own view does not change anyone else’s — and carry `is_collection`, which is what will make the same row a smart collection. **A tree can only name the fields the chips already offer**, and both faces compile through one registry, so the tree cannot reach a column the chip row cannot and the two cannot drift apart; shape is bounded at 6 deep and 60 parts. A tree we will not run comes back as a 400 naming the offending part rather than being quietly dropped, because ignoring a filter hands back the whole library and lets it read as the answer. Negation folds away SQL’s third value: *not behind* includes the titles the field was never set on, which plain `NOT (x IN (...))` silently excludes.
- **BYO VR runtime runbook** (INSP-41 / VR-XR-1…4, H3b). `docs/runbooks/vr-byo-runtime.md`: the four layers a headset seat needs around Oneirodex — OpenXR runtime, OpenVR adapter, streamer, tweaks — which fills each on Windows and Linux, the wired USB-NCM link for a Quest-class headset (0.7 ms RTT / ~756 Mbps measured) step by step, and upscaler / foveation as documentation only. Cites the Linux VR wiki instead of restating it. Oneirodex ships, installs and injects none of it; docs index, FAQ and README rows added.
- **An arcade play path, opt-in** (INSP-43, H4b). Admin → Emulators can now pick an arcade core from `ARCADE_COMPANION_CORES` — deliberately *not* through `platform_emulator_mapping`, which stays empty because ARCADE is a locked, no-WASM platform and a mapped core is what would make a browser session look possible — and **choosing a core is what lifts the catalog-only lock**: until then the arcade shelf still reads *catalogue*, because promising Play with no core chosen would be a lie (every other locked platform stays locked). `Game.input_family` (`joystick` / `spinner` / `lightgun` / `trackball`, Alembic `b2c3d4e5f6a7`) says how the cabinet was driven; `PATCH /api/games/<uuid>/input_family` (librarian, `validate_body`) sets it, `game_card_flags` carries it, and the desktop companion appends the matching RetroArch input remap on launch. No ROMs, no MAME sets, no file paths.
- **A BYO notification bus** (INSP-6, H4d). `utils/notification_bus.py` fans the alerts you already get in-app out to an **Apprise API** server (`NOTIFY_APPRISE_URLS`) and/or an **ntfy** topic (`NOTIFY_NTFY_URL`) through `safe_request`: one event per admin alert, riding the existing `admin_notify_*` flags; social kinds (friend requests, mentions, DMs, free games) only when `NOTIFY_SOCIAL_TO_BUS=true` and the member's own preference allows. `POST /api/admin/notify-bus/test` sends one test event and says what was delivered. Plugins `notify.apprise` / `notify.ntfy` and an Integrations row. Nothing bundled; a dead endpoint is logged and never breaks the in-app notice.
- **A headset record per title** (INSP-40, H3a). `GameVrProfile` — one row per (game, kind): `native` / `injector` / `flat`, the runtime side (`openxr` / `openvr`), the community **profile page** URL (http(s) only; files and paths are refused) and a note. `vr_compat` derives from the rows when a librarian did not set it, the `/vr` hub and its filters admit profile-backed titles, and the details VR line adds the runtime and a *Community profile page* link; librarians get *Add / Edit headset record*. `GET|PUT|DELETE /api/games/<uuid>/vr_profiles[/<kind>]` with `validate_body`. Alembic `a1b2c3d4e5f6`. A record and a link — never a shim.
- **Xbox and PlayStation ownership registers — unofficial, opt-in, register-only** (INSP-42, H4a). `store_ownership_xbox.py` (xbox-webapi title history) and `store_ownership_psn.py` (psnawp title stats) on the per-store pattern: connect / disconnect / sync / CSV routes with validated bodies, IDs and names into the register, a 401 fails closed with one sentence. CSV import always works; **live sync is off by default** — `ENABLE_UNOFFICIAL_STORE_SYNC=xbox,psn` opts a store in (decision G5), and the optional clients live in the new `requirements-optional.txt`, imported lazily, so the plugin and Integrations rows read *disabled* / *available* / *configured* truthfully. `store_sync_mode()` promotes the two to `live` only while opted in and the poller enrols them the same way; the ownership summary carries `unofficial` / `opt_in` per store so the page says *snapshot* honestly. Ownership page gains the two cards. Nothing downloads; Nintendo stays CSV.
- **Assists links in the companion overlay** (INSP-45 under the cheats ruling's Option A, H4f). An assist pack can carry `overlay_links` — maps, guides, clips, a wiki — validated as **http(s) pages only** (`@validate_body`; a `file:` URL or unknown kind is refused), and every PC title gets a PCGamingWiki deep link even with no pack. The stay-open Friends window shows them for the game on screen: the desktop companion passes the last launched title as `?game=<uuid>`. Links beside the game — **no memory access, no injection, nothing read from the running process**. `get_json` baseline 100 → 99.
- **Mod compat gate, dependencies, update discovery, download integrity** (INSP-38/39, H2e). A row can `requires` other rows (the companion stages them first, whatever the load order); `GET …/mods` reports `loader_conflicts` — enabled rows whose loader disagrees with the pack default — the panel says *Loader mismatch* and the companion refuses to apply that set until the rows or the default agree. The catalogue drawer marks hits already tracked (by source URL) with **update: vX** when the registry is newer and offers *Mark updated*; Thunderstore hits carry `dependencies` and *Add with N needed* files them in one action. The companion refuses an empty or `Content-Length`-short download before writing it and re-stages on the next apply.
- **Save location on PC details pages** (INSP-1 PC half, H4e). `utils/save_paths.py` wraps the community save-location manifest — one keyless fetch a day, a compact JSON index built beside it so no request parses the YAML — and answers by Steam id, then exact name, PC shelves only; `None` when silent. The details facts grid gains **Save location** with one templated path per OS and, with the companion online, **Open save folder**: the companion expands `<winAppData>`-class placeholders for its own PC and refuses when one is unknown there. Plugin `compat.save_paths`, Integrations row, `ENABLE_SAVE_PATHS`. The folder, not a backup — nothing is synced or copied.
- **Mod profiles and a shareable code** (INSP-37, H2d). A game's pack holds named sets of tracked mods; **Activate** is the one-click enable set — the profile's rows on, every other row off — which is what the companion's next *Apply mods* stages (its result now names the profile). **Copy code** gives `od-mod:` + base64url JSON (name, default loader, each mod's name / version / loader / source page — never a file); importing it on another game matches what that game already tracks (by id, then source URL) and lists the rest as *missing* instead of inventing rows. `utils/game_mod_profiles.py`, six routes under `/api/games/<uuid>/mods/profiles` (writes librarian, export readable by members), `ModProfiles.tsx` under the Mods panel. JSON pack, no migration.
- **GameBanana and Nexus Mods in the catalogue drawer** (INSP-22, H2c). GameBanana (keyless, rate-limited: the game's mod feed, filtered by name) and Nexus Mods (**browse only** — trending then latest for the game's domain, behind a personal `NEXUS_API_KEY` the operator places; its terms forbid third-party download automation and nothing here downloads). Without the key the Nexus tab says so instead of returning nothing; plugin and Integrations rows read *available* until the key exists. CurseForge stays *declined*.
- **A GPU tile on Admin → Ops** (INSP-44 / MISS-OPS-3, H4c). `system_stats.get_gpu_usage()` reads NVIDIA's own management library when the optional `pynvml` package and a device exist, else a **BYO sensor reader** on a household PC — LibreHardwareMonitor / HWiNFO-class JSON at `TELEMETRY_READER_URL`, polled read-only through `safe_request` with a generous parser — and returns `None` when neither answers; the tile then reads *n/a* with *no NVML or reader* as the hint, otherwise the first GPU's load, name, VRAM, temperature and source. **Nothing bundled, no sensor tool, no kernel driver.** The touched `system_stats` functions moved `print()` → `logger` (print baseline 591 → 587).
- **A Mods panel on the details page, with a read-only catalogue browse** (INSP-22, H2b). Everyone sees the tracked mod list (name, version, loader, source); a librarian gets the pack's default loader, an add form and **Browse catalogue** — Thunderstore (BepInEx / MelonLoader communities) and Modrinth (Minecraft), both keyless, through `utils/mod_catalog/` and `GET /api/games/<uuid>/mods/catalog?source=`. A hit is a name, a version, the loader it needs and the registry page; *Add to list* records that page as `source_url`. The answer is `ok` with hits or `unavailable` with `hits: null` and a note — never a silent `[]`. Plugins `mods.catalog.*` and Integrations rows, with CurseForge listed as *declined* on its API terms. `ENABLE_MOD_CATALOG` (default on). Nothing downloads.
- **Mods say which loader they need** (INSP-36, H2a). Each tracked mod row carries `loader` (`bepinex`, `melonloader`, `smapi`, `lovely`, `forge`, `fabric`, `quilt`, `neoforge`, `manual`, `none` suggested; any slug kept) and the pack a `default_loader` rows inherit — `PATCH /api/games/<uuid>/mods/pack`, or on the bulk `PUT`. The mods API bodies are now validated (`422` on unknown fields; three `get_json` sites retired, baseline 103 → 100). The desktop companion reads the loader into its apply result — *Needs BepInEx installed — not managed here* — and installs nothing. No migration: the pack is JSON.
- **Anti-cheat on the details page** (INSP-35, H1e — and gate 2 for the cheats policy's Option B). A PC title the community anti-cheat list knows gets an *Anti-cheat* fact: Supported / Running / Planned / Broken / Denied, the anti-cheat's name, and a link to the report page, worded as *community reports* never a guarantee. `utils/anticheat_compat.py` fetches the public list once a day (keyless, through `safe_request`) into `static/library/anticheat/` and answers from that cache only — a details page never waits on the network, and a title the list does not know shows nothing. `game_card_flags` emits `anticheat`; plugin `compat.anticheat` and an Integrations row say whether the first fetch has landed. `ENABLE_ANTICHEAT_COMPAT` (default on).
- **DAT repair preview, a dry run** (INSP-24, H1f). Admin → ROM reference sets gains **Preview repairs**: for one platform (one region's set or all of them) it sorts every owned file against the set — hash matches under another name (rename candidates, with the set's name), names that match under another hash (bad dump / revision / header), clone-named files with whether the parent is owned, and files the set never listed — plus counts of verified and not-yet-hashed files. `POST /api/reference-sets/repair-preview` (admin, `validate_body`, `api_ok`) in `utils/set_repair.py`; a `mame` set never proposes renames (its files are named by machine short name). Report only: nothing is renamed, moved or marked.
- **An agreement floor before auto-import** (H1d, the pass-8 finding). `IDENTIFY_AGREEMENT_MIN` (default 1 — today's behaviour) says how many sources must name a title before the scan creates a game: IGDB counts one, each agreeing catalogue row one more. At 2, a title only IGDB named goes to Review with `insufficient_agreement` and a proposal sidecar that says how many agreed, instead of importing. One decision point in `scan_identify`, beside the existing catalogue-disagreement branch; the scan tests are the net.
- **Keyless hash identify for console ROMs** (INSP-31, H1a). After an IGDB miss *and* a local-DAT miss, the file's own CRC/MD5/SHA1 (outer, then inner dumps) are asked of a community hash-lookup service (`HASH_IDENTIFY_BASE_URL`, default hasheous.org; no account). A named answer creates the same custom-range Game a DAT hit would, with a summary naming the service, the digest that matched and the proxied IGDB id; every miss, error or unparseable body is a plain miss. Identity only — never enrichment, never a download; every call through the SSRF-guarded client; off under pytest. New switch under Integrations → Metadata (`hash_identify`, default on), plugin + inventory rows. `GENERATOR_VERSION` 40 → 41 because the switch's handler lives on the themes volume.
- **One game, one ROM** (INSP-5 / 1G1R, H1c). Reference-set entries carry the DAT's `cloneof` parent (`ReferenceSetEntry.parent_name`, Alembic `f1a2b3c4d5e6`); set completion counts parents only, so a MAME set with forty clones of one game counts it once; when a DAT lists a title for several regions the kept row is the preferred region (USA → EUR → JPN …), not the first listed. The Unmatched *Duplicate* glance says *Reference DAT lists this dump as a clone of a game already in the library* (`clone_of`) when that is what happened — advisory only, nothing is marked or deleted on it.
- **TOSEC and MAME reference sets** (INSP-34, H1b). `tosec` and `mame` join `nointro` / `redump` as DAT sources, so home-computer and arcade shelves get set completion and hash identify. TOSEC's `(1991)(Publisher)(EU)[cr Group]` groups peel to the title with the scanner's own rules; MAME `-listxml` machines and softlist `software` entries are titled by `<description>` (the set id stays the attribute), and nested `<part>/<dataarea>/<rom>` hashes are read. No new platform enum — `ARCADE` is the platform. Same replace-on-upload, same ambiguity rule (a CRC shared by clone sets never auto-creates).
- **Ways to play → In a headset** (VR-L4b / VR-FILTER, the UI half of rider R3). Three rows — *Plays in VR*, *VR via community profile*, *Plays flat* — each a deep link and nothing more: a community profile is named and linked, never shipped, installed or pointed at as a file. The details page carries the same line under the play row; the `/vr` hub now admits librarian-stored `native_vr` / `injector_profile` titles (a stored `flat` removes one), filters with `?vr_compat=`, and marks community-profile cards; the VR badge says which. `controllers-and-vr.md` gains a PSVR2-on-PC walk-through and the README's VR line says what the headset path actually is.
- **Ops → Companions has a device list** (TC-4). `GET /admin/api/ops/devices` returns every companion, thin seat or browser shell that has sent a heartbeat — kind, name, member, version, last seen — with `online` judged on the same 3-minute window as the tile, and the Ops page renders it under the by-kind table. FAQ, troubleshooting and the thin-client guide say where a seat appears and why it might not.
- **`vr_compat` beside `is_vr`** (rider R3). Every card and details payload says how a title plays in VR: `native_vr` (derived from the VR perspective unless a librarian set otherwise), `injector_profile`, `flat`, or unknown — never a guessed `flat`. Librarians set it with `PATCH /api/games/<uuid>/vr_compat` (`VrCompatBody`, `null` clears); Library filters take `?vr_compat=`, where `native_vr` also admits derived VR so the filter and the badge agree. Alembic `e5f6a7b8c9d0`. Catalogue data only — nothing here ships, installs or points at a shim.

### Fixed
- **"Won’t play" now means something** (INSP-4, with INSP-21 folded in). The status has been recordable on every tile for a long time and **nothing read it** — a member could say no to a game and Discover would keep offering it, which looks like not listening. Titles marked Won’t play are now excluded from the personal recommendation rows, per member. Two smaller holes closed with it: the multi-select bar could set four of the five statuses and **silently refused the fifth** (it was missing from the batch allow-list), and the vocabulary itself was spelled out as literals in four backend modules and two SPA files, which is how they drifted apart — it now has one definition in `utils/play_status.py`. Deliberately narrow: one "won’t play" suppresses **that title only** and is not read as evidence against its genre, because letting a single click reweigh every facet it touches would quietly narrow the shelves.
- **Save states never reached the server, and the ones that did could not be loaded** — the other half of the same report (*"the badge doesnt update and loading manually does not load the save state"*), reproduced in the browser against the live box. Two faults. **One:** the play room is a static file under `/static`, so its `<meta name="csrf-token">` is never rendered and the CSRF cookie is `HttpOnly` — the room had no token to send, and every upload and delete it attempted came back *"The CSRF token is missing"*. The saves listing now hands the room a token (same exposure as the SPA’s rendered meta: login required, same-origin, no CORS anywhere in the app), and the room remembers it. **Two:** RetroArch writes a state’s 8-byte RZIP header at once and compresses the payload over the next second or three, while webretro copies the file into IndexedDB from its write callback — so a read taken straight after the save command returns the header alone, and the bridge accepted the first non-empty read. Measured live: the first export returned **9 bytes** of a 741-byte state. The export now reads the file being written in preference to the cached copy and retries until the size stops growing and is big enough to be a state (~0.6 s on a warm core). Verified end to end afterwards: *Sync now* stored 741 bytes, *Load* restored them into the core, *Delete* worked for the first time. The `?v=` shell cache key moved to `save-states-4`, without which none of this reaches a member who has played before.
- **NeoGeo CD (and any RAR5) ROMs would not play** — reported on the Human Queue, reproduced on the box. Three faults in a row: the 7-Zip in the image *lists* a RAR5 it cannot decompress (28 zero-byte files, *Unsupported Method*); the extractor assumed the tool that listed could also extract, so bsdtar — which decodes the archive perfectly — was never reached; and bsdtar could not be handed the member anyway, because ROM names like `[!][NGCD-058]` are glob character classes to it. Now: the listing tool is tried and then the other one, a zero-byte result counts as a failed decode (and the husk is deleted so it cannot be cached), member names reach bsdtar backslash-escaped so an exact name matches literally instead of reading as a character class; and a short `rarfile` read is refused instead of writing half a ROM. A damaged member no longer costs the whole rip: bsdtar stops the entire run on a CRC error, so one bad audio track in a 34-track CD image used to hide the `.cue` sitting at member 34 — the extractor now drops the member bsdtar named, asks again for the rest, and logs which track was damaged. The rar path also stopped reporting a generic *Failed to read rar archive* over the top of the CLI’s actual diagnosis, which is what made this look for months like a missing unrar tool. New `scripts/ops/playability_report.py` answers the rest of the report — *"we should run a test for each system that has games in our library"* — by opening one real file per platform through the play route’s own resolver.
- **The Thunderstore catalogue could never find a community.** Its community list is paginated at 100 and Oneirodex read only the first page, so *Browse catalogue* answered *no data* for Risk of Rain 2, Valheim and Lethal Company — titles the registry certainly knows. It now follows the `pagination.next_link` cursor (capped at 20 pages). Found by calling the source live from the box after the deploy, not from reading it.
- **Librarian controls on a details page could never appear.** The page has read `game.can_edit` since the PC cheats panel shipped — and the details payload never sent the field, so the cheats form, the new Mods panel and the headset-record editor were all gated on `undefined`. The payload now emits `can_edit` (librarian or above, the same rule the routes behind those controls apply); `is_admin` is unchanged. Found by reading the live page after the H2–H4 deploy: the API answered with mod and save data the page would not show.
- **Lazy member pages no longer blank the SPA.** `/chat`, `/calendar`, `/ways-to-play` and every other lazily loaded route that reads `useViewer()` / `useShellConfig()` threw *must be used within a Provider* and unmounted the app. Cause: `dist_asset` versioned the module `<script>` with `?v=`, while the route chunks import the entry by its bare path — two URLs, two module instances, two copies of every React context. The JS entry is now linked bare (its freshness already comes from `asgi.py` serving unhashed `static/dist/` files `no-cache`); the stylesheet keeps its token. Regression test in `test_theme_asset.py`.
- **A thin seat is never offered a companion action it cannot finish** (TC-3, the rest of UID-061). Beyond the action bar and Big Picture, the Versions, Translations and Extras sections, the Updates page, the open-path dialog and the Ways-to-play companion card used to show *Apply with companion* / per-update *Download* / *Open in file explorer* whenever the member's companion happened to be online somewhere. On `?seat=thin` they now say the work happens on the desktop companion (`seatCanUseCompanion()`, one `ThinSeatNote`), the open-path dialog copies the path instead of queuing, and the Guide link stays.
- **vitest 3.2.7 → 4.1.11 in every workspace** (GHSA-82fw-gwwq-j7x9, `@vitest/mocker` redirect-mock path traversal; Dependabot alerts 1 and 3–9). One lockfile change for all six packages; vite stays 6.4.3. Every suite is unchanged under vitest 4: shared 125 · api-client 51 · ops-glance 6 · admin 382 · desktop 124 · member 1,017. The remaining alert (`glib` 0.18 in the desktop `Cargo.lock`, Linux target only) is pinned by tauri 2.11.5 → gtk 0.18 and has no upstream fix; dismissed with that reason.
- **The admin app's TypeScript was never linted.** `eslint.config.js` listed `shared`, `ops-glance` and `member-app` under the typescript-eslint block and not `admin-app`, so `npm run lint` — and the CI lint job — checked only the admin app's `.js` test files since its TS conversion. Added; it surfaced three dead bindings (fixed) and two `useMemo` dependency warnings in `DashboardPage` / `OpsPage` (left for their decomposition).
- The image build type-checks SPA source only (`tsconfig.build.json`). After every test file became TypeScript, the Docker build's `tsc --noEmit` also checked tests — and `cssTokenLint.test.ts` imports `scripts/css-token-lint.mjs`, which the build context deliberately does not stage, so `compose up --build` failed on the box. Tests are still type-checked by CI's `typecheck` jobs.

### Changed
- **README and docs media rebuilt from a live capture instance.** A new README (section headers and feature cards drawn from the theme's own tokens and the shared rail icons, a composited hero, a screens gallery, a how-to gallery), **49 fresh stills** across every member and admin surface, and **20 narrated how-to videos** (AI voice via `edge-tts`, in-page captions, WebVTT tracks, transcripts, poster frames) replacing the ten silent clips. Five scripts make it repeatable: `scripts/serve_capture.py` stands a throwaway capture instance up in one command, `capture_common.py` holds the health gate and the title card, `capture_docs_media.py` and `capture_howto_videos.py` shoot against it, and `render_readme_art.py` draws the hero, banners, cards and poster tiles. A still whose page errors, comes up empty or loads unstyled is skipped and exits non-zero; a clip whose subject step the UI cannot perform writes no file at all. Recipe and gates: [CAPTURE.md](docs/assets/readme/CAPTURE.md).
- **Six system-family theme presets** (`GENERATOR_VERSION` 39 → 40). A third picker group, *System families*, between the decade rooms and the colour cabinets: Cartridge red, Disc-tray blue, Signal green, Deep blue 16-bit, Woodgrain amber, Terminal teal — the shell language of one console family each (red-trimmed grey shell, blue LED, green ring, blue stripe, woodgrain and silver switches, teal phosphor), in the era room that family lived in, with its own icon pack and geometry. Names and copy describe the look, never a maker. Existing presets are byte-identical; the bump is what makes **Reset Themes** install the six new folders. E1 from `theme-art-direction.md` closed.
- **One platform-family table.** `FAMILY_BY_PLATFORM`, `FAMILY_META` and `platformFamily()` moved to `@oneirodex/ui` (`frontend/shared/src/platformSkins.ts`); the member and admin copies had drifted (`pc` accent, null semantics). Each app keeps its thin wrapper — member returns `null` for an unknown platform, Art Studio previews fall back to the system green — so no behaviour changed, only the source of truth.
- **The decade rooms and system-family packs draw their own rail glyphs** (E4, second half). Eight destinations — discover, library, systems, downloads, favorites, collections, playtime, chat — are redrawn in three hands: stepped 1-bit *pixel* for the 80s den and the arcade, thick *rounded* toy-plastic for the 90s rooms, thin-diagonal *angular* for the 2000s media centre and the desk. `RailIcon` picks the room's hand from `<html data-theme data-era>` and falls back to the shared drawing for any other glyph; colour cabinets and the default theme are unchanged. SPA code only — no theme-volume change.
- **Admin › Emulators is one React page.** `EmulatorsPage` owns the preferred-core form (was `templates/admin/emulator_profiles.html` + `static/js/od_admin_emulator_profiles.js`, same `/api/emulator-profiles` contract) and the browser-player pilot, RetroAchievements and firmware panels that used to mount as a React island under the Jinja form. The island mount in `main.tsx` is gone with the template body. H-D.5 port 2; the inventory count is 28 pages + 3 partials.
- **Admin › Detail layout is a React page, and the admin Jinja tail is a census.** `DetailLayoutPage` replaces `templates/admin/detail_layout.html` + `static/js/od_admin_detail_layout.js` — same `/api/layouts/detail` contract (ordered `{ id, visible }`, empty list = reset), keyboard-reachable Up / Down buttons with accessible names, a retry on a failed load. `docs/dev/admin-jinja-inventory.md` lists the 29 admin pages (+ 3 partials, 5,032 template lines, 34 handler files) still server-rendered, what each depends on, and the port order — Tier 1 small panels → Tier 2 forms → the Libraries & scans hybrid last.
- **Five more backend modules under 1,000 lines, as pure moves (H-D.4 batch 2).** `software_identify.py` 1,403 → 736 (`software_identify_store` Stage D candidate rows · `software_identify_custom_game` custom kinded games · `tgdb_platform_match` Stage E platform matching); `preset_themes.py` 1,405 → 748 (`preset_themes_catalog` is the preset table, `preset_themes_geometry` the per-system chrome geometry — `GENERATOR_VERSION` unchanged, no theme output changed); `rom_archive.py` 1,227 → 660 (`rom_archive_types` extension tables · `rom_archive_select` member choice · `rom_archive_zip` zip / gzip / bundle — the 7z / rar extractor shims stay); `store_ownership.py` 1,113 → 267, one module per store (`store_ownership_common` · `_gog` · `_epic` · `_amazon`; Steam, CSV import and the summary stay); `routes_apis/game.py` 1,007 → 385 with the five batch routes in `game_batch.py`. Every original module re-exports what callers import; eight test patch targets followed their functions (`_outbound` per store, the batch routes' `user_can_access_game` / `run_in_background`). Ratchets re-homed at identical totals: api-envelope 11, get_json 103, print 591.
- **`routes_apis/scan.py` is 370 lines, not 1,769; `cover_art_studio.py` is 567, not 1,626.** First two of the H-D.4 backend god-module splits, both pure moves: the unmatched-folder surface now lives in `scan_unmatched_rows.py` (row / glance payload builders), `scan_unmatched.py` (list, duplicates, export, fix logs, reclassify / backfill, bad-match feedback) and `scan_unmatched_edit.py` (amend, mark kind, fix — single and batch), each registered on `apis_bp` when `scan` is imported; the cover renderer's tokens, Pillow painters and title typography are `cover_art_tokens.py`, `cover_art_paint.py` and `cover_art_title.py`, with `cover_art_studio` re-exporting every name callers imported. No route, URL, payload or test changed (one test patch target followed its function). The `get_json` ratchet's 103 call sites are re-homed, not reduced.
- **Every SPA test file is TypeScript, and `tsconfig.base.json` is `strict: true`.** 173 `.test.js(x)` files (member 104, admin 50, shared 17, ops-glance 2) plus the JS test harness modules are `.ts(x)` and strict-clean; the per-package `strict` overrides are gone. The types caught real drift on the way: the api-client's `UpdatesInboxItem` said `game_uuid` where the server writes `uuid`; `EditionsResponse.tags` said `string[]` where the server also sends `{ label, kind }` chips; and `testConventions` would have scanned nothing after the rename. `checkJs` stays off on purpose — the classic theme JS that admin tests import is not SPA source. `@types/node` is a new dev dependency for the tests that read repo files.
- **`GameDetailsPage` is 463 lines, not 1,283.** Seven sections (cover column, quick rows, summary, facts, translations, versions, extras) and three hooks (`useGameDetails`, `useVersionActions`, `useFreshnessCheck`) moved into `pages/gameDetails/`, each owning the state only it read; markup unchanged. The extracted props got real types — `DetailsGame`, `VersionRow`, `CatalogHit`, `ExtrasModel` — which is how `playtime` and `rom_ai_translate` turned out to be objects the old `any` had hidden. `any` ratchet 1,265 → 1,259.
- **`ChatPanel` is 497 lines, not 1,097.** The rooms column, thread header, message list and composer are components under `components/chat/`; mute / archive / leave and the attachment uploader are hooks; the module-level helpers moved out with them. Markup unchanged. Typed props (`ChatChannel`, `ChatMessage`, `ReactionItem`…) showed `message.mine` is the list of emojis you reacted with, not a boolean. `any` ratchet −5.
- **`DupeGlance` is 597 lines, not 1,008.** The compare sub-components, status/reason tables and the exported formatters moved to `components/dupeGlance/DupeCompare.tsx` (the old import path still re-exports them). `CompareField` takes `ReactNode` / `unknown` instead of `any`. `any` ratchet −3.
- **No SPA component is over 600 lines any more.** Second batch of the decomposition: `ArtStudioPage` 895 → 567, `ImagesPage` 869 → 426, `LibraryApp` 858 → 590, `TrailersPage` 854 → 425, `GameCard` 826 → 562, `AccountModal` 809 → 147, `LibrariesPanel` 741 → 433, `OpsPage` 707 → 243, `opsWidgets` 699 → 287 (+ `opsFormat.ts`), `NewsPage` 696 → 323, `EmulatorFirmwarePanel` 640 → 432. Every cut is at a component's own boundary with its markup unchanged; helpers and sub-components that were already separate definitions moved to sibling modules with the old paths re-exporting. Where props were typed (`BrowseResult`, `CardGame`, `NewsItem`, `TrailerFilters`…) the `any` count fell: **1,265 → 1,224**. `OpsPage`'s widget map is a plain builder now, so its `useMemo` finally lists exactly what it reads. New ratchet **`scripts/component_size_lint.mjs`** (threshold 600) runs in CI.
- **`<Modal>` and `<DataTable>` are `@oneirodex/ui` primitives.** `Modal` owns what every dialog was hand-rolling — a portal to `body` (so no host page's stacking rule can pin it into the flow), Escape, backdrop-click-closes / panel-click-does-not, `role="dialog" aria-modal`, initial focus, a Tab cycle inside the panel, and focus returning to the opener on close. The admin Open-path, Ops-log and Scan-conflict dialogs and the member Open-path dialog sit on it, keeping their own CSS. `DataTable` (+ `PM_IGNORE`) moved from the admin app into the package so member tables can share it; admin keeps re-export shims.
- **Every SPA button is `<Button>`.** 112 hand-spelled `<button className="od-btn …">` sites across 32 files moved onto the `@oneirodex/ui` primitive, which grew `secondary` / `quiet` variants, `size="lg"` and `pill` — all mapped onto classes already in `od-primitives.css`, no new CSS. `od-btn--accent` (admin-only `ops.css`) stays a `className` pass-through. New ratchet `scripts/od_btn_lint.mjs` runs in CI with an **empty** baseline, so a new raw site fails the build. `.od-cbtn` context-bar buttons are a different family and are untouched.
- `showToast` is one module. The member and admin apps each carried a byte-alike copy of `frontend/shared/src/toast.ts`; both paths are now re-export shims of `@oneirodex/ui`, and the two app test suites merged into one shared suite (ten cases, the union of both). `any` ratchet 1,276 → 1,266.

## [1.0.0] — 2026-09-18

First stable release. Everything below shipped on top of `1.0.0-beta` (2026-08-06):
the modernization program, the review of the Cursor run, the emulation track
(audio clocks, EmulatorJS as a second engine, save states, RetroAchievements),
drawn theme rooms, and an installable app.

**Upgrading from `1.0.0-beta`**

1. Pull and rebuild: `docker compose up -d --build`. The entrypoint runs `alembic upgrade head`; this release adds three migrations (scan-job schedule fields, `user_preferences.browser_player_engine`, and the RetroAchievements index + `games.ra_*` columns). All three are idempotent, so a boot that already created the columns from the model is not an error.
2. **Reset Default Themes** — Admin → Themes, or (admin) Preferences → Look & density. `GENERATOR_VERSION` moved 36 → 39 across this release (drawn room art, per-console motif colour, the wrapping segmented strip), and themes are served from the library volume, so without this the rooms stay flat.
3. Optional, operator-owned: `scripts/fetch-emulatorjs.sh` into the `EMULATORJS_HOST_PATH` bind to offer EmulatorJS as a second play engine; `RETROACHIEVEMENTS_USERNAME` + `RETROACHIEVEMENTS_API_KEY` in `.env` to match achievement sets. Both are inert when absent — no badge, no promise.
4. The installable app needs **HTTPS**. Service workers require a secure origin, so on a plain-HTTP LAN address the *Install this library* row stays hidden by design.

Nothing in this release requires a database restore, and no configuration key was removed.

### Added
- **Install Oneirodex as an app.** A web manifest at `/manifest.webmanifest` and a service worker at `/sw.js` (root scope) make the member app installable — its own window, its own icon, opening on your shelf. **Preferences → Install this library** prompts on Chromium and says where the control is everywhere else; it hides itself when already installed, dismissed, or the origin is not secure (service workers need TLS). This is the thin-seat path for Chromebooks and locked-down laptops (TC-2b) and the Quest path per the PWA-first ruling. The worker caches **only** versioned static assets — never HTML, never `/api/**`, never cover art — because a service-worker cache is per-origin and outlives a sign-out on a shared machine; offline lands on `/offline`, which carries no library data, and signing out clears the cache.
- **Themes have rooms now, not gradients.** Every era ships drawn scene art (`art/era/<era>.svg`) painted as its own layer behind the product — window, shelves of cartridges and a CRT in the 80s den; posters, a shelf and a portable set in the 90s bedroom; blinds, a big CRT and a disc spindle in the late-90s den; a wall panel and glass AV rack in the 2000s media centre; a lit cabinet row in the arcade; a monitor, tower and keyboard at the desk. The room keeps its era palette and one sentinel colour follows the theme accent, so fifteen presets stop reading as one room fifteen times. `GENERATOR_VERSION` 37 — **Reset Default Themes after deploying**. Art direction: [theme-art-direction.md](docs/dev/theme-art-direction.md).
- **EmulatorJS as browser play engine B (BP-2).** Operator-installed, never vendored: `scripts/fetch-emulatorjs.sh` drops a release into the `EMULATORJS_HOST_PATH` bind, the app offers it only when `loader.js` is there, and Admin → Emulators gains a default-engine choice (disabled with the reason until installed). Play on a supported system (NES, SNES, GB/GBC, GBA, DS, VB, N64, Mega Drive, Master System, Game Gear, 32X, Atari 2600/5200/7800, Lynx, Jaguar, PC Engine, Neo Geo Pocket, WonderSwan, ColecoVision) opens `/static/vendor/emulatorjs/play.html`, which streams the ROM from `/api/downloadrom` like every other engine; anything else stays on WebRetro. Runbook: [emulatorjs.md](docs/runbooks/emulatorjs.md).
- **RetroAchievements: titles say when a community achievement set exists, and members can see their own progress.** Opt-in with `RETROACHIEVEMENTS_USERNAME` / `RETROACHIEVEMENTS_API_KEY`; Admin → Emulators → RetroAchievements matches each cartridge system by the hash RetroAchievements itself uses (iNES/SNES/Lynx/PCE/7800 headers stripped, N64 normalised to z64 — not `file_md5`), and game details grows an Achievements section. Disc systems are left unmatched rather than matched wrongly, a matched set with no achievements promises nothing, and nothing played in the browser unlocks anything — there is no achievement runtime in the WASM shell, and the copy says so. Runbook: [retroachievements.md](docs/runbooks/retroachievements.md). Alembic `d3e4f5a6b7c8`.
- **Save states you can actually use.** Tiles read **Resume** when a state exists (`resume_state` on `/browse_games`, one query per page); the details page lists your states under *Saved states*, each a Resume; the room asks *resume or start fresh* instead of loading a state behind your back; **← Game Catalog** / **Power** / a hidden tab take a state on the way out (`auto`, keepalive upload); and the play bar's **Saves** panel names saves, loads, deletes and syncs. `GET /api/games/<uuid>/saves` lists newest first and flags `is_state`. Play asset cache key `save-states-1`.
- **Members can choose their browser play engine.** Admin → Emulators → *Let members choose their engine*; with it on and both engines installed, Preferences gains a *Play in browser* section (server default / WebRetro / EmulatorJS). Stored per member, honoured only while the admin allows it and the engine is installed; a system the engine cannot run still opens in WebRetro. Alembic `c7d8e9f0a1b2`.
- Admin shell shows the AGPL source offer again when `source_url` is configured.
- **Five architecture decision records** — [0006](docs/adr/0006-asgi-bridge-a2wsgi.md) the a2wsgi ASGI bridge, [0007](docs/adr/0007-four-frontends-one-shared-package.md) three SPAs over the Jinja admin hybrid, [0008](docs/adr/0008-npm-workspaces-single-lockfile.md) npm workspaces, [0009](docs/adr/0009-api-envelope.md) the `api_ok`/`api_error` envelope, [0010](docs/adr/0010-pydantic-request-validation.md) pydantic `@validate_body` — plus [an index](docs/adr/README.md) that records what supersedes what.
- [ci-gates.md](docs/dev/ci-gates.md) — what each CI job actually gates, and the two still owed. Replaces the tracks-era `ci-wishlist.md`, now removed.
- [test-suite-failures-2026-09-16.md](docs/dev/test-suite-failures-2026-09-16.md) — the full-suite failures named and grouped by cause, replacing an unnamed count that no ticket tracked.
- **Agent-harness files stay untracked, and CI now enforces it.** `CLAUDE.md` / `AGENTS.md` were briefly tracked (2026-09-16) on the theory that a fresh clone needed instructions; the maintainer ruled the next day that anything describing how an agent is run against this repo stays off GitHub, whichever agent or model. The contributor-facing conventions they carried (ratchets, test database, route rules, `.env` warning) moved into [CONTRIBUTING.md](CONTRIBUTING.md); `tests/test_repo_hygiene.py` (in the CI core list) fails if any of `CLAUDE.md`, `AGENTS.md`, `.claude/**`, `.cursor/**` become tracked — the three `.cursor/` environment-bootstrap files are the one documented exemption.
- [architecture.md](docs/dev/architecture.md) and root [CONTRIBUTING.md](CONTRIBUTING.md).
- `docker-compose.artwork-local.yml` — SD.Next + GPU only, for a Windows workstation (not the NAS stack). Runbook: [artwork-gpu-workstation.md](docs/runbooks/artwork-gpu-workstation.md).
- [api-envelope-keeps.md](docs/dev/api-envelope-keeps.md) — why eleven JSON sites stay off `api_ok`.
- **Tile preview shows GOG / Epic marks and a trailer source.** Browse still sends only Steam per cover. `GET /api/games/<uuid>/editions` merges store URLs and the first YouTube `video_urls` entry across copies the member can see. The popup paints those marks the same way details does; YouTube is a link, not a second player. A copy in a library they cannot see does not contribute a link.
- **Page-owning SPA loads use the shared status block.** Remaining admin Remote play / Libraries table / Integrations inventory / Images queue / Stock catalog / **Users save** / **Images `IMAGE_SAVE_PATH`**, member Systems / Cheats / Big Picture / **Chat / Notifications / Activity** / **Library browse / FilterBar / Tokens** / **Acquire / Report / Friends dock** / **space rail / voice / store search / wishlist / collections / add-to-shelf / details update-check / invalid trailer URL**, and **Ops glance** use `PageStatus` instead of a bare “Loading…” paragraph. A failed first Ops poll no longer paints empty host panels. Failed Acquire status no longer looks like the module is off. Trailers **Another one** keeps the current player up and floats `LoadingOverlay` (250ms) so the frame does not collapse. Tokens clipboard-unavailable copy and Set completion’s missing-set empty stay inline on purpose.
- **Blank downloaded covers become titled studio art.** A cover that HTTP-200s as a 1×1, a stub, or a near-solid wash is replaced on download (scan, queue, turbo, retry) so the library tile is not an empty hole. Screenshots are left alone.
- **Admin firmware collection scan.** Admin → Emulators can point at a folder of dumps you already own (subfolders included), install every name the service asks for, pick which dump to use when filenames collide, and copy a markdown list of what is still missing. Same walk as `scripts/import_bios.py`. Oneirodex still never downloads BIOS.
- **Set completion and Playtime use bar two.** Platform/region identity, owned count, **Systems** / **Browse library**, and the region filter live in the context bar; Playtime totals (`duration · n games`) sit in the trail instead of a page title card.
- **Admin Users roster is the editor.** Invites / Support sit in the top bar; **Edit** saves role through the existing user API. The classic second editor is gone.
- **Oneirodex public string (ADR 0003 phase 1).** UI, Help, README, user/admin docs, and the desktop window title say **Oneirodex**. Package path, Docker image, GitHub repo, `GT_*`, and `gt-` CSS stay `oneirodex`. Danger-zone confirm is `RESET ONEIRODEX`; `RESET ONEIRODEX` still works.
- **Play-mode matrix for every platform.** Tests and play-skins cover the full `LibraryPlatform` enum — not only NES and Game Boy. SG-1000 and Neo Geo Pocket Color browser-play via already-shipped WASM. Legal sample fetch adds Game Boy Color (`cgb-acid2`) and SNES (`SuperBossGaiden.sfc`). Remaining browser systems stay documented as skipped until a licensed URL exists.
- **Catalog disagreement goes to Review.** A high-confidence IGDB hit is still checked against Steam / GOG plus unique-exact MobyGames / TheGamesDB. Folder `Doom` / IGDB `Doom 3` writes `catalog_disagreement` instead of auto-importing or peeling the name until it fits. Remaster/subtitle store titles are no-signal, not a veto.
- **Remaining sheets use radius, type, and semantic colour tokens.** Member Chat / News / Big Picture / Calendar / Collections / details / filters / cheats / dock, admin styles / Dupe glance / Ops, plus classic scan jobs, game details, base, account, profile, and setup. Hardware-family marks are `--od-family-*`. Token ratchet **1074 → 0**. Member SPA needs an image rebuild; classic admin needs **Reset Default Themes**.
- **More small sheets use radius and type tokens.** Scan conflict, Open path, Propose leaves, Command palette, Chat slide-out, store links, library selection bar, DataTable, game preview, glass, Loading overlay, Cheats, plus classic admin Help / Dashboard / Server status / shell / Identify. Token ratchet **1195 → 1074**.
- **Classic admin JSON failures use the shared envelope.** `api_error` can put job/queue `status` and honesty `code` on the body (`body_status` / `body_code`) without colliding with HTTP `status=` or envelope `error_code`. Scan-queue rejected/started, library reorder/delete confirm, unmatched delete, and download `path_missing` / request status migrated. Ratchet **41 → 11** annotated keeps (`/healthz`, batch `ok`, Ollama, hardlink preview, game-details play status, OIDC report).
- **Arr refusals use the shared envelope.** A UTF-8 BOM on `routes_arr.py` made the lint skip the file. The ratchet now reads `utf-8-sig`. Arr module/indexer/search/download/hardlink errors go through `api_error`; job-state payloads through `api_ok`. Remainder still **11** keeps.
- **Trailers and Ops failures use the shared envelope.** Empty trailer results stay HTTP 200 with `code` / `message` as data. Trailer 500s and Ops/library-health 503s no longer return `str(exc)`. `/healthz` is still `{status: 'ok'}` for probes. Ratchet **50 → 41**.
- **Thirteen small stylesheets use radius and type tokens.** Help, Trailers, VR, Ownership, mobile density, plus form-components, sidebar, table-components, settings shell, system logs, integrations tabs, whitelist, and IGDB settings. Classic CSS needs **Reset Default Themes**; member SPA pages need an image rebuild.
- **Preferences opens again.** The grouped room-card picker crashed because Jinja treated `group.items` as `dict.items`. It now walks `group['items']`.
- **Nineteen more APIs report failure through the shared envelope.** Playtime, SMTP, IGDB settings, filters, assists, folder browse, layouts, LiveKit tokens, VR browse, ambient lighting, challenge solver, remote play, plus libraries crop preview, whitelist delete, Playnite import, loading icons, metadata search, invite delete, and preferences. Ratchet **130 → 50**. SMTP/IGDB save still include `status: 'success'` for classic admin JS; error bodies use `ok` / `success` / `message` (`api_error` cannot carry a body `status` key). IGDB no longer returns raw exception text.
- **Twelve more APIs report failure through the shared envelope.** Calendar, locale, admin games search, scan/match, notifications, SSE fallbacks, updates store-search, malware-scan refusals, plugins/activity stream, librarian decorator, Flask download/ROM ASGI fallbacks.
- **Decade room themes.** Preferences is no longer a tiny colour-chip grid. Six era rooms (1980s wood den, 1990s teen bedroom, late-90s carpet den, 2000s media centre, arcade floor, computer desk) plus the existing colour cabinets sit in the same wallpaper/window/floor language as browser play, on member *and* admin chrome. Untitled-game placeholders and Art Studio backup packs follow the room. Needs **Reset Default Themes** (`GENERATOR_VERSION` 17) so volume copies pick up `od-era.css`.
- **Amazon Games live ownership register sync.** Same shape as Steam / GOG / Epic: IDs and names into `UserOwnedTitle`, never a download. Unofficial Nile / Heroic entitlements; paste a token JSON (or household env). Fail honestly on 401. CSV still works.
- **Disc chips on game details.** Multi-disc titles show count + Disc N on the details identity row. Tiles stay at the UID-001 badge cap.
- **Oneirodex identifier phase 2 started (dual names).** Compose `APP_IMAGE` / `APP_CONTAINER_NAME` keep existing `oneirodex-*` defaults. Preferred Hub image once published: `chrisjrovira/oneirodex`. Package / `GT_*` / `gt-` unchanged.
- **GOG and Epic live ownership register sync.** Same shape as Steam: IDs and names into `UserOwnedTitle`, never a download. Unofficial Galaxy / launcher surfaces; paste a refresh token or Epic device-auth JSON (or household env). Fail honestly on 401. CSV still works.
- **Operator notes for snes9x / genesis_plus_gx non-commercial clauses.** Quotes from upstream plus questions to take to a lawyer — [webretro-core-clauses.md](docs/admin/webretro-core-clauses.md). Not counsel.
- **Operator privacy / data-handling notes.** What the host stores, what can leave if you enable SMTP / metadata APIs / OIDC / LiveKit / GitHub support, and how `child` accounts are denied download and Acquire — [privacy-data-handling.md](docs/admin/privacy-data-handling.md). Not a public ToS.
- **Toasts are dismissible on admin too, and new games wait for the scan to finish (UX-B7).** Classic `$.notify` calls the same aurora toast. A running scan no longer announces "N games added" mid-pass.
- **Report takes ideas as well as defects.** "Report issue" collected feature requests into the same
  pile as bugs, so triage had to read every title to sort them and a request filed as a defect read as
  a broken product. The form asks first, the `kind` rides through to the GitHub issue title and labels,
  and the rail entry is now just **Report**
- **Notifications archive themselves.** Reading one changed a dot and nothing else, so the list only
  ever grew. Inbox now holds what is outstanding and everything read moves to **Archive** — available,
  not deleted, and not in the way
- **Choose which sites headlines come from.** The feed list was a hardcoded tuple. `GT_NEWS_FEEDS`
  replaces it for the operator (http/https only — the server fetches this list), and each member can
  switch individual sites off on the News page. Every configured source is listed whether or not it has
  an article today, so a quiet site is still switchable
- **Rail sections fold away.** Twenty-three destinations is a long column and most sessions live in one
  part of it. Each group heading is now the control that collapses its group, remembered across
  sessions. A collapsed rail forces every group open — at icon width the headings are hidden, so a
  folded group would be destinations that vanished with no visible way back
- **Rail icons animate on hover** — a one-shot pop that settles slightly larger, so the row the pointer
  found is distinct in a column of similar marks. Reduced motion keeps the size change and drops the
  travel
- **Scan locations beyond the server's own disk** (`GT_LIBRARY_ROOTS`). The folder browser and the
  path allowlist both keyed off a single `BASE_FOLDER_*`, so a NAS share was unreachable even when
  the host had it mounted. Roots are declared as `Label=/path` pipe-separated, join the allowlist in
  one place (`get_allowed_base_directories`), appear as a **Scan location** picker on Auto Scan and
  Manual, and get their own Ops path-health row — a share that stops being mounted now reads as
  *not mounted* instead of as an empty library. New `GET /api/library_roots`
  ([remote-scan-locations.md](docs/runbooks/remote-scan-locations.md))
- **macOS and Windows installers** — `install-macos.sh` (Homebrew, PostgreSQL 17, launchd notes) and
  `install-windows.ps1` (winget prerequisites, `psql.exe` discovery off `PATH`, mapped-drive warning).
  Native install was Linux-or-manual before. `install-linux.sh` gains `--library-roots`, and all three
  write `GT_LIBRARY_ROOTS`. Service units for all three OSes in
  [install-native.md](docs/runbooks/install-native.md)
- **Account modals** — profile, avatar, password, invites and API tokens were five server-rendered
  pages in three visual idioms; reaching one meant leaving the app and losing your scroll position.
  They open as one modal over the current page now, built as the same object as the game preview
  popup (same scrim, z-index band, panel radius, glass, close affordance) with a segmented switcher
  between the five panels. New `/api/account/*` endpoints back them; the Jinja pages remain as the
  no-JS and Big Picture fallback and every menu entry keeps a real `href`
- **Invites without an email address.** The link *is* the invite — email was only one way to deliver
  it — but the form demanded an address and handed it to a mailer that a household without SMTP had
  never configured, so the link was created and shown to nobody. The address is optional now and the
  response reports `emailed` honestly instead of implying delivery
- **Admin: add a member with no email at all** (Admin → Invites). For a child's console login or the
  living-room account, where an invite has nowhere to go. `users.email` is `NOT NULL UNIQUE` and is
  read unchecked in several places, so these accounts get an unroutable RFC 2606 `.invalid`
  placeholder rather than a relaxed column; it is never displayed as an address
  ([members-and-invites.md](docs/admin/members-and-invites.md))
- **Fonts and firmware install with the server.** Both were scripts nobody ran: the picker offered
  five faces and shipped none, and a populated local BIOS folder still read as empty. Fonts install
  in the background and never block startup (`FETCH_FONTS_ON_BOOT`); firmware imports from
  `BIOS_IMPORT_SOURCE` and never overwrites
- **Editable cover text in the Art Studio** — headline, subtitle and a title-size slider. The
  renderer always accepted these and only the preview forwarded them; Generate now matches what the
  preview showed
- **API envelope ratchet** (`scripts/api_envelope_lint.py`) — the shared response envelope landed
  with two files migrated and the problem then grew from ~699 call sites to 1194. Existing sites are
  recorded; a file may never exceed its count
- **Two-bar chrome** — side rail + top bar (`SideRail`, `TopBar`, and the `partials/rail.html` ·
  `partials/topbar.html` Jinja equivalents) so React and classic pages present one shell. Page views
  moved into bar two across both stacks; admin adopted the same bar one and its pages retired their
  now-duplicated titles
- **Chat pop-out** — `openChatPopoutWindow()` plus a `?popout=1` chrome-less host, matching the pattern
  the Friends dock has used since the social wave. Chat no longer blocks library interaction
- **Bad-match feedback** — operators can say a proposed match is wrong, on both the React `DupeGlance`
  and the classic unmatched table, so the two surfaces do not disagree about whether feedback exists
- **Game preview popup** — hover surfaces the state that actually decides whether a title can be played
- **Local installer builds** — `scripts/build-installers.sh` + [local-installers.md](docs/runbooks/local-installers.md);
  desktop installers no longer require GitHub Actions. Per-host limits are stated rather than implied —
  a `.dmg` genuinely needs a Mac
- **BIOS import** from an operator-supplied local collection (`scripts/import_bios.py`), preferring the
  majority copy when candidates disagree
- **Cabinet playback on the WebRetro play bar.** Save / Load / Rewind (hold) / fast-forward / Picture (CRT · Sharp · Soft) / shortcut help. RetroArch rewind is on for light cores with a 10 MB buffer; it stays off on N64/PS1/Saturn/Dreamcast/PSP. No shader packs, no run-ahead — [browser-play.md](docs/user/browser-play.md)
- **Ownership polling** (`oneirodex/utils/ownership_poller.py`) and a `/styleguide` route
- **CSS token lint** (`scripts/css-token-lint.mjs`) with a baseline — 2365 violations down to 1317
- **Sortable classic tables** (`js/od_sortable_table.js`) — the Jinja counterpart to the React
  `DataTable`, so a table sorts the same way on both stacks instead of per page or not at all. Adopted
  on **Active Scan Jobs**, which had no sorting at all, and on **Unmatched**, which had its own
  private implementation. A page opts in with two attributes and the module wires itself up, because
  a page that must remember to call something eventually will not. A table that should arrive already
  ordered declares it in markup (`data-od-sort-default`) rather than being re-sorted after each render
- **Theme asset freshness check** (`oneirodex/utils/theme_freshness.py`), surfaced as a **Theme assets**
  panel in the Ops console. Theme CSS only reaches `static/library/themes/` on a **Reset Themes**, and
  nothing reported the drift — the only symptom was "the fix didn't work". The panel hashes source
  against deployed and distinguishes *behind* from *never deployed*, since those are different problems
  wearing the same number. It never copies anything; the fix stays an operator decision

### Changed
- **A console's loading motif now carries that console's colour.** Every motif was already drawn in `currentColor` and `--od-platform-accent` was already set per system family, but `.od-loading-motif` read `--od-accent` — so a Mega Drive cabinet spun in the theme accent like everything else. Non-system pages are unchanged (the fallback is the theme accent). `GENERATOR_VERSION` 38 — Reset Themes after deploying.
- Discover shelves: the News / deals / Upcoming rows' scroll bar sits at the same gap under the tiles as every other row (article tiles overlay their caption, so the row no longer reserves a caption strip for them); a **mouse drag anywhere on a row — first tile included — pans it**, with the click after a drag swallowed so a tile does not open; a Steam free-game tile whose 2:3 capsule does not exist falls back to the store's `header.jpg` instead of an empty frame.
- Discover **Upcoming** shows what you do not hold: library titles still ahead of release appear only if *you* favourited or requested them, and the rest of the shelf comes from the IGDB release cache for the systems your libraries hold — titles with no library row, as tiles with a `Coming · <platform>` badge and the date, linking to that platform's licensed catalogue. It used to list library games with a future date, i.e. things the household already had.
- Browser emulator (EMU-AUDIO): the play assets' cache key is bumped to `play-clock-2` — it had sat at `leave-guard-1` through two refresh-clock fixes under `max-age=3600` with no validator, so a browser holding the old file kept it. The refresh sampler now waits for `visibilitychange` when the player boots in a hidden tab (`requestAnimationFrame` does not tick there) and logs that it is waiting instead of logging nothing. The device's audio rate is logged at boot (`Audio device: 48000Hz`) and both clocks are stamped on `<html>` as `data-od-refresh-hz` / `data-od-audio-hz`. `audio_latency` 96 → 128 for underrun headroom on a main-thread core. Ships with the image — no Reset Themes.
- **CI `pytest-core` runs the marker set, not a hand list.** `tests/ -m "not integration"` (3,792 tests, 11m24s on the runner) minus an explicit `--deselect` list of the 31 known failures that reproduce there. A new test file is gated by default; the deselect list is the exception list and only ever shrinks. The hand list of ~113 files had let 42 failing files ship unnoticed.
- `@oneirodex/api-client` exports every resource factory as a value (`createPlaytimeApi`, `createWishlistApi`, `createDiscoverApi`, `createGameApi`, `createUpdatesApi`, …). Until now only `createCollectionsApi` was, which is why collections was the only typed module any SPA had adopted. Member `api/playtime.ts`, `wishlist.ts`, `favorites.ts`, `discoverPins.ts`, `gameEditions.ts` and `updates.ts` now sit on the typed modules; page exports and error shapes are unchanged. Client gaps closed on the way: `listRequests({all})`, librarian `resolveRequest`, `listFavorites({name, itemKind})`, `updates.scan` / `storeSearch` / `addWanted`, and `AbortSignal` on `playtime.me` / `discover.setPins`.
- Deep discounts (`store_deals`) can actually fill: CheapShark now 400s a generic User-Agent, and their Savings sort treats `desc=1` as 0% off first. Fetches send `Oneirodex/1.0 (self-hosted library)` and `desc=0`. A boot poller warms the cache so Discover does not wait on outbound HTTPS; a failed pull keeps the last good snapshot. Init still seeds the shelf. Unraid image rebuild is still the live-tree ship — this environment cannot reach `192.168.50.116`.
- Browser emulator: a display-refresh sample that finished during boot is no longer dropped. `afterStart()` now calls `tryApplyConfig()`, and the first `retroarch.cfg` write waits briefly for `measureRefreshHz` so `video_refresh_rate` can land before `callMain`. Does not rewrite cores; `audio_max_timing_skew = "0.15"` stays the WASM pin. Human console check on a high-Hz panel still required (EMU-AUDIO).
- Discovery shelves admin delete uses the house confirm dialog instead of `window.confirm` (UID-060). Theme JS cannot import `frontend/shared`, so the dialog is copied in-file (named buttons, danger tone, Cancel focused). `GENERATOR_VERSION` **31** — Reset Themes required so the volume copy of `discovery_sections.js` / `admin_discovery_sections.css` picks it up.
- `@validate_batch_body` lands for partial-success JSON. `POST /api/games/batch/favorite` uses it: missing `favorite` / `uuids` is `422 unprocessable` with `detail` naming the field **and** `updated` / `skipped` / `errors` / `limit` so the member batch bar does not go blank. Over-limit is still 400. Success `ok` is still "did every item succeed".
- Member collections CRUD goes through `@oneirodex/api-client`'s `createCollectionsApi` on the existing browser requester. Page exports (`fetchCollections`, `createCollection`, …) and error shape are unchanged. `searchGames` still hits `/api/search`.
- Playtime start, wishlist create/resolve, API-token create, and related-media create adopt `@validate_body`. Missing required fields (`game_uuid`, `title`, `status`, `name`) are now `422 unprocessable` with `detail` naming the field, not the old `400 bad_request` sentence. Semantic refusals (unknown status / preset / media kind) are unchanged.
- Library-tools JSON routes with a real presence/type guard (`proposals/approve`, `proposals/scan_roots`, doctor dry-run / write / apply-renames, `check_freshness`) adopt `@validate_body`. Missing `library_uuid` / `roots` is now `422 unprocessable`. Dual-input propose/import and the all-optional Steam backfill stay unwrapped.
- Chat mute, space-member add, and quality-profile score adopt `@validate_body`. Missing `muted` / `user_id` / `title` are now `422 unprocessable`. Channel/space 404 still follows a well-formed body.
- PC-cheat create and companion lifecycle POST adopt `@validate_body`. Missing `label` / non-list `records` are now `422 unprocessable`. Unknown cheat method, RetroArch-surface refusal, and missing companion stay in the view.
- Wanted add/fulfill, hardlink preview/apply, game-server create, and admin malware-scan adopt `@validate_body`. Missing `game_uuid` / `source` / `dest` / `display_name` / `connect_string` / `path` are now `422 unprocessable`.
- Acquire download and announcement create adopt `@validate_body`. Missing `url`/`magnet` or `title`/`body` are now `422 unprocessable`. In-view librarian/admin checks still 403 after a well-formed body.
- Check-username and layout-preset create adopt `@validate_body`. Missing `username` or `name`/`layout` are now `422 unprocessable`. Unknown section ids and the 64-character preset name cap still 400 from the view.
- Patch-catalog attach and artwork apply adopt `@validate_body`. Missing `game_uuid`/`source_url` or `url` are now `422 unprocessable`. Unknown image kinds and non-http(s) URLs still 400.
- Stock-avatar pick and password change adopt `@validate_body`. Missing `id` or password fields are now `422 unprocessable`. Unknown avatar ids still 400; a wrong current password is still 401.
- AI apply-triage adopts `@validate_body`. Missing `game_uuid` or `title`/`name` are now `422 unprocessable`. Auto-apply still 403 after a well-formed body.
- Discovery shelf create/update adopt `@validate_body`. Missing or blank `name` is now `422 unprocessable`. The 50-character cap and shelf-config checks stay in the view (still 400).
- Full-game delete and image delete adopt `@validate_body`. Missing `game_uuid` / `image_id` is now `422 unprocessable`. Unknown ids still 404; a running scan still 403 for a well-formed body.
- Library crop-preview adopts `@validate_body`. Missing `image_data` is now `422 unprocessable`. Decode / PIL failures stay 500.
- Admin cover-apply and artwork-generate adopt `@validate_body`. Missing `game_uuid` / `url` is now `422 unprocessable`. A well-formed generate body is still 403 when generated artwork is off.
- Arr download and hardlink-preview adopt `@validate_body`. Missing `download_url` / `library_dest_dir` is now `422 unprocessable`. A well-formed preview body is still 403 when the hardlink pipeline is off.
- Art-studio preview/generate/apply adopt `@validate_body`. Missing `title` / `pack_id` is now `422 unprocessable`. Mode-dependent apply checks and disk errors stay in the view. The file's `request.get_json` count does not drop: `_json_body()` remains for stock generate, batch, and system-marks.
- Discovery order/visibility, cover search (`query` or `game_uuid`), and quality-profile set-active adopt `@validate_body`. Missing `sections` / `section_id` / `is_visible` / query-or-uuid / `id` aliases are now `422 unprocessable`. Negative display order still 400; unknown shelf/profile ids still 404.
- **Probe endpoints renamed — `/healthz` → `/pulse`, `/readyz` → `/awake`.** **Breaking.** The trailing `z` is a Kubernetes convention and Oneirodex ships on Docker/Unraid, so the paths now say what they do. Response bodies, status codes and the `probe` field are unchanged, so a healthcheck only needs its URL updated. Compose is updated; **an existing Unraid container template pointing at `/healthz` or `/readyz` must be repointed or its healthcheck will fail.** Captured samples renamed to `docs/media/screenshots/pulse.json` / `awake.json`.
- **Legacy `GameTheca` identifiers removed — clean break, no back-compat ([ADR 0003](docs/adr/0003-product-name-oneirodex.md) finished).** **Breaking.**
  - Env: `ONEIRODEX_*` is the only prefix. The `GT_*` fallback is deleted from `product_env.py`, so **an `.env` still using `GT_*` silently falls back to defaults** — update it before redeploying. `LEGACY_PREFIX` / `NEW_PREFIX` are gone; `product_env.PREFIX` replaces them.
  - localStorage: `gt.*` keys are now `od.*` (`gt.library.layout` → `od.library.layout`, and 8 more). **Saved layout, filter, rail and palette state resets once** — no migration shim by design.
  - Danger zone: `RESET GAMETHECA` is no longer accepted. The phrase is `RESET ONEIRODEX`.
  - Admin Ops dashboard widget ids follow the probe rename, so **a saved Ops layout resets once**.
  - `product.LEGACY_NAME` is deliberately kept: it is read (never written) to recognise stock themes authored by older versions, not branding.
  - Historical `CHANGELOG.md` entries and `docs/adr/**` keep the old string on purpose — do not rewrite them, and do not rewrite git history.
- Member SPA remaining `src/api/` wrappers sit on `createBrowserRequester` (same shape as admin `adminApi.ts`). FormData / fire-and-forget writes use `send` / `sendResult`. Chat / voice / space-rail / PC cheats / related media / loading-icon / library-scan toast poll use those verbs too. Preferences HTML and EventSource stay off this path.
- `POST /api/support/tickets` adopts `@validate_body(CreateSupportTicketBody)`. Missing title is 422 `unprocessable` instead of 400.
- **Copy pass (member + admin).** One voice rule: playful where nothing is wrong (empty states, first run), plain where something failed (errors, destructive confirms). Catalog empty/error strings rewritten in `i18n.js` **en and es together**; member-facing `api_error` detail rewritten; the scan-lock message is one sentence across **6** sites and no longer says “try again later” (retrying does nothing — waiting for the scan does); image-size refusal names the real **60 megapixel** bound; 11 destructive confirmations front-load the consequence. `Clear` → `Clear filters`; sort labels and `All …` options in sentence case; `Filesize` → `File size`.
- Catalog edge-column tiles keep covers/badges on hover enlarge (bleed ×1.5 for 1fr stretch + `overflow-clip-margin-inline`). `GENERATOR_VERSION` **28**.
- Catalog **Grid** is genre shelves at full tile size without clipping headings (no shell hover-pad pullback). **Rows** height follows the tile-size slider (56–144px). `GENERATOR_VERSION` **27**.
- Libraries panel: view tabs have no underlines; page sits left under the thin bar; column filters sit beside titles (themed typeahead, not white); “N libraries” + Games popover live on the page (not the top bar); Scan/Edit share colour and size; “0 selected” is hidden; optional Group column + action; game counts heat against the platform’s released set. `GENERATOR_VERSION` **26**.
- Admin Dashboard: Reset layout has no rest outline; Health strip grows with Degraded issues; drag/resize use real row pitch (`3.5rem` was parsed as 3.5px and vanished widgets). Layout storage **v4**. `GENERATOR_VERSION` **25**.
- Admins can **Reset Default Themes** from Preferences → Look & density (same `POST /admin/themes/reset` as Admin → Themes).
- Compose binds WebRetro cores from `WEBRETRO_CORES_HOST_PATH` (default `/mnt/cache/appdata/oneirodex/webretro-cores`) so fetched cores survive recreate.
- Catalog / News / Favorites layout control shows the **active view name** (Tile · Rows · Grid, or News Card · Grid · RSS) instead of a fixed “View” label; the unfurl menu keeps the View name for assistive tech.
- Thin member top bar stays solid on tile hover; enlarged Catalog / Discover tiles overlap it (`GENERATOR_VERSION` **24**). No more opacity in/out.
- Catalog / Discover tiles: no outline at rest; hovered enlarge uses a tight accent ring. Library edge tiles overlap left/right (centred scale). Play on a tile follows `--od-tile-*`. `GENERATOR_VERSION` **22**.
- Admin Settings hub is one sheet with On/Off pills beside each title (UID-033 — human QA still open).
- Libraries & scans stays clickable during a live scan: job progress patches in place, unmatched does not rebuild on other panes. `GENERATOR_VERSION` **21**.
- Discover shelves use a pixel hbar, matching News scrollbar spacing, overlay-open tiles, and a Ways to Play rail glyph (UID-020 — human QA still open).
- BBC Micro and Game & Watch are companion leaves (no WebRetro WASM). Their dump suffixes (`.ssd` `.mgw` …) seed AllowedFileType on boot. Authentik groups `oneirodex-admin` / `librarian` / `child` map like the `oneirodex-*` aliases.
- Compose passes remaining OIDC and product-flag env into the app container (no `env_file` dump). Unraid Authentik LAN HTTP: [oidc-authentik-unraid.md](docs/runbooks/oidc-authentik-unraid.md) Appendix A.
- GitHub default is **`chrisjrovira/oneirodex`** (the old `chrisjrovira/oneirodex` URL still redirects). `SUPPORT_GITHUB_REPO` and `GT_SOURCE_URL` / `ONEIRODEX_SOURCE_URL` follow. Origin URL is `https://github.com/chrisjrovira/oneirodex.git`.
- Identifier **phase 3a** (landed, then superseded by the clean break above): dual `ONEIRODEX_*` / `GT_*` and `--od-*` aliases. Package path `oneirodex/`.
- Identifier **phase 3b** (2026-08-31): Python package `oneirodex/`; CSS `.od-*` / `--od-*`; live Unraid `oneirodex-*` containers; Postgres database `oneirodex`. Confirm phrase `RESET ONEIRODEX`. `createGamethecaClient` alias and `RESET GAMETHECA` retired with the clean break.
- Icon packs: **library / discover / systems** ship distinct SVGs on Filled, Duotone, Pixel, Soft, and Mono. Outline stays the inline stroke set.
- **Theme packs are system visual languages (`GENERATOR_VERSION` 16).** Each preset now overrides radius, spacing, type and shadow — not just hue. **Reset Default Themes** after deploy.
- **Art Studio idle title size is 1.3×** (floor 0.85×). The slider always posts `title_scale`.
- **Brand glyph is a closed cabinet** (lintel + shelf), so it does not read as a controller.
- **CSP enforces by default.** `onclick=` is gone from Jinja; WebRetro is outside Flask CSP.
- **Library tools live on Libraries & scans.** `/scan_management?active_tab=tools`; `/admin/library_tools` redirects. Auto Scan and the library maker are one page.
- **`/admin/server_status_page` redirects to Ops.** Login and admin still required.
- **Statistics charts sit in a bounded grid** (W27-D3). Chart.js no longer grows a dual-axis scroll.
- **Unmatched dupe compare has Pop out** (W27-C4) on the live Jinja table.
- **Rail glyphs at rest use the theme accent** (W27-E4 code half). Per-theme drawings remain art.
- **Dead sidebar chrome is gone** from `gt_shell_rail.js` (submenu / filter-visibility leftovers).
- **Game details later sections sit beside the facts rail (UX-B4).** Versions, extras, screenshots and trailers used to start below the taller Details column, leaving a hole under a short summary. They now share the two-column grid so that body climbs the left while Details stays on the right. Narrow viewports still read summary → details → the rest.
- **Discover learns what you reach for, without anything leaving the box.** A taste profile is built
  from signals the install already keeps — what you favourited, played, finished, own and downloaded
  — weighted by how much intent each one carries and decayed so it follows you rather than
  fossilising. It drives a **Because You Played** row per title you have really put hours into
  (anchored on playtime, not recency: a row built on something you bounced off reads as a
  misunderstanding), and *Curated for you* now reads the profile instead of the genre-affinity draft
  it shipped with. No model file, no new dependency, no telemetry
- **Collaborative filtering is written, and stays off until it would mean something.** "People who
  played this also played that" needs a population; on a self-hosted box with a handful of members,
  two titles co-occurring once is indistinguishable from coincidence. It switches on at 25 members
  with real play history and is otherwise skipped, with the content-based engine carrying the feed —
  which is the one that actually works at this scale
- **The feed stops showing you the same tiles every morning.** Titles you are shown and never open
  are quietly scored down — to a floor, never suppressed — and opening one clears that immediately.
  The running order is seeded from you and the date, so it is stable all day and different tomorrow
  rather than reshuffling under your pointer between glances
- **Pin the Discover rows you actually use.** Each row header carries a **Pin** button; up to three
  rows stay at the top of your feed. Pins are stored as rows, not positions, so an admin reordering
  shelves does not move your pins off what you chose — and a row that later stops existing is dropped
  quietly rather than erroring, because a genre row going away is not a fault. The fourth pin is
  refused outright instead of silently discarded: a pin that vanished without a word would look like
  a bug
- **Admins can force a shelf to the top of everyone's feed** — `pin_rank` on a discovery section,
  cleared by setting it back to null. Capped at three shelves on purpose, so that a member's own
  three pins can never be pushed below the fold on their own home page. Forcing composes with
  scheduling: a forced shelf outside its event window is still hidden
- **Discover stops showing you the same game five times.** Rows are now assembled as a page rather
  than built one at a time: each row drops titles a row above it already showed and backfills from
  its own depth, and the feed holds at most twenty rows. *Continue Playing* is exempt on purpose —
  what you are playing belongs there regardless. A row thinned below the point where it is worth
  showing is dropped and its slot goes to a row that missed the cut; a row that was **always** that
  short is kept, because a curated three-game zone is not a starved row. Your shelf order is
  untouched: what this decides is which rows fit, never what sequence they run in
- **Deduped rows stay deduped when you scroll them.** The feed hands the browser a token naming what
  each row claimed, and paging a row passes it back. Without it the duplicates would return the
  moment anyone scrolled — the dedupe would have been decoration. An install with no cache still
  gets its feed; it just loses dedupe past the first window
- **Discover knows what you were doing.** Four rows join the feed ahead of the charts: **Continue
  Playing**, **Friends Are Playing**, **Recently Updated Files** (actual update files landing, as
  distinct from the metadata timestamp the *Last Updated* shelf reads), and **News** — announcements
  and live free-game offers in the same vertical rhythm as the game rows rather than exiled to their
  own tab. Every row now says *why* it is there under its title; an unexplained recommendation reads
  as an ad and a named one reads as a feature
- **You decide whether friends see what you are playing.** *Friends Are Playing* is gated on a new
  preference under Notifications → Preferences. On by default, because the common install is a
  household — but limited to accepted friends and never server-wide, and one switch turns it off. A
  pending friend request is not a friendship, and a member who has never touched their preferences
  counts as sharing: absence is not an opt-out, only an explicit "off" is
- **Discover rows go deep, and end in a way out.** Every shelf showed the same eight tiles with no
  way to see the rest of what it stood for. Shelves are now horizontal rows that fill themselves in
  as you scroll them — twelve tiles arrive with the page, the rest follow — up to forty. Forty is a
  ceiling rather than a quota: a shelf shows what it honestly has, and the **See all** tile appears
  only when there is genuinely more than the shelf will display. That tile lands on a real filtered
  Library view when the shelf can be said as a filter (a genre or platform zone), and on a page for
  that shelf alone otherwise
- **Every shelf is now a registered row rather than a branch in one long chain.** Nothing visible
  changes today; it is what lets a shelf be capped, reordered, pinned or deduped against its
  neighbours without each shelf's own code taking part. A row resolves through its section, so a
  hidden or out-of-schedule shelf stays unreachable by direct URL — the new row endpoint is not a way
  around the visibility toggle
- **Discover builds the whole page in one batch instead of one tile at a time.** Every card ran its
  own cover-image lookup, lazy-loaded three relationships, stat'd the game folder twice and re-asked
  whether a companion client was connected — the last of which is the same answer for every card on
  the page. Selection and hydration are now separate passes, so the cost tracks the number of shelves
  rather than the number of tiles: at 120 tiles the feed went from 426 queries to 15, and a title
  appearing on several shelves is fetched once. Nothing about the page changes except how fast it
  arrives. One payload correction rides along — Discover cards reported `updates_count: 0` for every
  game, so the preview popup claimed no updates on titles that had them; it now carries the real count
  the Library and Updates pages already showed
- **Ops console and dashboard tables now sort.** Five hand-rolled panel tables moved onto the shared
  `DataTable`, which gained a `toolbar={false}` mode — these panels hold three or four rows, and a
  filter box above them was the reason hand-rolling them looked reasonable. They already shared the
  styling, so they had the look of the other admin tables and none of the behaviour. Two stay
  hand-rolled on purpose: the key/value detail panels, and the Services checklist, whose row order is
  the order you read it in
- **Child access to the household voice lobby is now a household setting**, not a hardcoded stance
- Chrome buttons and primitive buttons now agree on focus: one ring, one offset, and a fallback so a
  theme missing the token loses the colour rather than the outline
- **Four more surfaces answer through the shared response envelope** — wishlist, support tickets,
  wanted list and the patch catalog, taking the ratchet baseline from **875 to 849**. The wire contract
  is unchanged (`api_ok` / `api_error` still mirror `error`, `message` and `success`, and every HTTP
  status is the same), but the messages stop being developer strings: "Forbidden" becomes "That request
  belongs to someone else", "Not found" becomes "Ticket not found". These are member-facing failures, so
  they are exactly the ones the SPA's shared error component has to render
- **Theme selection lives in Preferences only.** The admin Themes page carried its own swatch grid
  writing the same `current_user.preferences.theme` that Preferences writes, so two surfaces could
  disagree about what was selected with nothing to say which had won. Preferences is the keeper — it
  builds its list from `get_installed_themes()`, so it already covers uploaded packs as well as presets,
  and font, icon pack and tile size live there too. The Themes page keeps upload, reset and delete, and
  now links to Preferences rather than silently dropping the affordance
- **The News page leads with admin notes**, full width, and only when there are any. Headlines dropped
  their full-row span so News and Free sit side by side beneath the notes instead of Free sharing a row
  with an often-empty panel
- **Help quick-navigation is one segmented strip** on the shared `.od-seg` the context bar and admin tab
  strips already use, instead of a third set of individually bordered pills wrapping into ragged rows.
  Help sections became panels matching the admin guide they were meant to resemble
- **Licensed under AGPL-3.0**

### Fixed
- Admin segmented strips wrap instead of pushing the page sideways on a phone. A six-item strip on Admin → Integrations was 457px wide inside a 315px parent; `.od-seg` was `inline-flex` with no `flex-wrap`. Wide layouts are unchanged — at 1280px it is still a single row. `GENERATOR_VERSION` 39, so Reset Themes after deploying.
- Rail glyphs are one shared module instead of two hand-maintained copies that had already drifted: the member set carried a `ways-to-play` glyph the admin set never got. The stated reason for the duplication (staging `frontend/shared` broke the image build) has not been true since the Dockerfile started staging all of `frontend/`; both apps keep re-export shims at their old paths. `any` ratchet 1,277 → 1,276.
- Big Picture no longer offers a thin seat buttons it cannot complete. The Download link, the Install button, the `D` shortcut and the gamepad's west button all ran with no seat check, while `GameActionBar` has refused them since TC-3 shipped — so on a TV, with a gamepad, the failure arrived as far from the press as it possibly could. All four are guarded now, and the two on-screen buttons are absent rather than present-and-failing.
- Tile-size slider in the top bar persists again. It posts `tile_size` alone, and WTForms rejected every SelectField that was absent, so each save came back 400 (swallowed client-side) and the size reverted on reload. `/settings_panel` now treats a post without `_full_form` as a partial save and fills the stored values in underneath.
- Unmatched list carries the name-transform trail again. PR #112 made `transforms` opt-in for CPU reasons, but the only consumer — the "Name transform trail" expander on Admin → Unmatched — never opted in, so it rendered for nothing. The list is paginated now, so the trail is on by default; `include=none` skips it.
- Scan-job cron: the field is labelled **UTC** (it always was evaluated in UTC — `0 3 * * *` from America/Chicago was a 9–10pm local scan); day-of-month and day-of-week follow crontab and fire on *either* when both are set (`0 3 1 * 1` was firing ~once a year instead of ~5×/month); an impossible expression (Feb 30) is rejected instantly instead of after a ~1.15M-step search inside the form POST; an unknown schedule option is refused instead of silently armed as a one-shot.
- `pydantic-core==2.46.5` is pinned explicitly. The shared interpreter has twice been pulled to 2.49.0 by another package, after which `pydantic` refuses to import and every route test hangs; `pip install -r requirements.txt` now reasserts the version `pydantic==2.13.5` requires.
- Docker `frontend-build` stages `tsconfig.base.json` so SPA `tsc --noEmit` keeps jsx/lib/moduleResolution (Unraid `compose up --build` was failing after the TypeScript on-ramp).
- Unraid ship/rebuild scripts pipe `scripts/ops/unraid_reset_themes.py` (the old `scripts/_unraid_reset_themes.py` path is gone).
- Dependabot npm groups are minor/patch only — vite/vitest/typescript majors stay manual (closed the open major grouper PRs).
- **Error flashes no longer time out.** Converting flashes to toasts applied a 6s dismissal to every
  tone, and `base.html` serves login and registration — so "Invalid credentials" vanished before a
  slow reader saw it. Successes and notices still expire; errors wait to be dismissed
- **The chat shell no longer breaks on phones.** The `data-surface="chat"` rule was more specific than
  the ≤900px override *and* later in the file, so it applied a two-column area map against the mobile
  single-column template and squeezed the conversation into an implicit zero-width column. Now scoped
  per breakpoint
- **The Notifications inbox cannot disagree with its own count.** Inbox filtered one page of rows
  client-side, so a member with more read notifications than the page size saw "All caught up" beside a
  "1 unread" badge, with the notification unreachable. Inbox is a server query now
- **Two scan locations sharing a label both appear in Ops path health.** Rows were keyed by label alone,
  so `Archive=/mnt/a|Archive=/mnt/b` reported only the second — from the view whose whole job is to
  reveal a root that stopped being mounted
- **The scan-location picker no longer wipes a typed folder path.** Its initial sync cleared the path
  input, so a re-rendered form after a failed submit lost what the operator had entered. Switching root
  still clears it, because a relative path does not survive changing what it is relative to
- **Flashes on the member shell are toasts, not a bar across the top.** `base.html` has always loaded
  the script that re-homes them; the member SPA extends `base_empty.html`, which did not — so on the one
  page where it mattered most, a flash rendered above the SPA and pushed the whole grid down, then
  pulled it back up when dismissed. Refreshing images on one tile moved the entire library twice. The
  conversion now covers every flash on a shell page, not just the image-refresh one
- **Trailers play inside a set.** The player was a bare iframe on a flat panel — the least evocative
  presentation available on the one page that is purely about watching something. It now sits in an
  analog cabinet drawn entirely from theme tokens (no image), so it recolours with the chosen preset
  instead of pinning the page to one palette
- **Help reads as documentation.** Sections adopt the admin panel treatment, the topic strip moved into
  bar two under short labels — reaching a page's own navigation should not mean scrolling that page —
  and the duplicate "Report an issue" link is gone; the rail already lists Report
- **Ownership is one store at a time.** The page stacked a full connect/import panel for every store, so
  the owned-titles summary sat above three long forms nobody was using. Stores are views in bar two; the
  summary stays put and the chosen store's card opens beneath it
- **The chat pop-out is a chat client at any size.** It was a bare `<main>` filling the window: fine at
  420px, but maximised it was simply the normal page with no navigation. It now has its own titled bar
  and a capped column. `/chat` inside the shell also drops bar two, which had nothing to hold there
- **The Updates refresh control says what it refreshes.** It was the word "Refresh" in bar two, a long
  way from the list it acted on. Now a symbol on the freshness inbox's own rule, with a hover/focus
  tooltip carrying the explanation
- **News sections are bounded.** Free games and headlines each rendered their whole feed into the page,
  so News grew to whatever arrived that day. Each scrolls within itself on desktop
- **Per page reads as a value, not a label** — the select precedes its caption
- **Every rail icon was being cropped.** `RailIcon` spread a `base` that carries width and height but
  no `viewBox`, and without one an SVG maps user units 1:1 to pixels — so an 18px element showed the
  top-left 18x24 of a 24x24 drawing. Whatever sat right of x=18 was simply gone, which is why the rail
  read as a column of similar half-glyphs and why the collapsed rail looked like it was slicing them.
  The admin copy of the same module had kept its `viewBox`; the member copy had lost it. Both now use a
  1-unit padded box so an edge stroke is not halved either
- **Rail glyphs redrawn.** Three pairs were byte-identical — `chat`/`news` (both in the Social group),
  `friends`/`users`, `admin`/`settings` — so the rail genuinely repeated the same mark. Every glyph now
  has a distinct silhouette and one filled signature element, verified as 31 unique drawings
- **Rail brand, icons and labels now share one column.** The brand had its own inset and a 1.4rem mark
  against the rows' 1.15rem icons, so the mark, the wordmark and the nav labels sat on three different
  left edges in the first 3rem of the rail. All three now derive from `--od-rail-inset` and
  `--od-rail-icon-w`
- **A page's controls followed you to every other page.** The first `ContextBar` mounted after login
  never had its portal torn down, so Activity's "Everyone / Friends only" strip sat in the top bar's
  centre slot for the rest of the session — Library rendered it *above* its own view strip, which read
  as buttons that had been added everywhere. React only removes portal children if the unmount runs,
  and a lazy route that suspends and is discarded can skip it. Each `ContextBar` now appends a host
  element it owns and sweeps out any other instance's on arrival, so a missed cleanup self-corrects on
  the next navigation instead of persisting. Reproduced in a browser, then pinned with tests
- **A rebuild was invisible to every lazily-loaded route.** `member-app.js` is deliberately unhashed so
  Jinja can link it, and the `?v=` on that link made the *script tag* fetch fresh — but the lazy route
  chunks `import` the entry by its bare path with no query, and that URL was served
  `public, max-age=3600`. After a rebuild the browser kept running the previous build's shared code in
  every lazy route while the versioned script tag reported the new one (two fetches of `member-app.js`
  at two different sizes, visible in `performance`). Unhashed SPA entry bundles now revalidate like
  theme assets; `chunks/` keeps the long cache, because those names carry a content hash
- **Tiles stayed enlarged after a click.** `:focus-within` matches focus from any source, so clicking
  a tile left it scaled until something else took focus — "you have to click off the screen to make it
  go back down". Every tile-scale rule now keys off `:has(:focus-visible)`, which a mouse click does
  not match and a Tab does, so the keyboard affordance survives
- **The tile-size slider shoved the centred controls sideways.** It expands 0 → 5.5rem on hover inside
  a single flex row, so merely crossing it on the way somewhere else moved the view switcher out from
  under the pointer. The control reserves its expanded width up front. Its hover border is gone with
  it; keyboard focus keeps a ring on the range itself
- **Filters no longer drifts away from the hamburger.** The page name rendered between the rail toggle
  and the Filters slot, so Filters sat at a different x on every page. The two are one cluster now,
  and all bar buttons land on `--od-control-h` — an icon-only button was previously shorter and
  narrower than the labelled one beside it
- **Hover glow raised 25%** (53%/26px/4px → 66%/33px/5px). The ring came off in the previous pass,
  leaving the glow as the only hover marker, and it lost that argument against a bright cover
- **Preview popup buttons no longer sit on top of each other** — the store links row and the
  Open details row both had zero margin
- **Frame removed from the library pager** — a glass panel with a border around a select, a segmented
  control and a sentence, each of which already carries its own shape
- **A long wishlist title made a new row on every resubmit.** `POST /api/requests` looked for an
  existing pending row using the full title but stored `title[:255]`, so anything past the column width
  could never match itself and the duplicate guard silently did nothing. Truncation now happens once,
  before the lookup, so the query and the insert compare the same string
- **Reopening a wishlist request left it stamped as resolved.** `pending` is a valid target for
  `PATCH /api/requests/<id>`, but the handler set `resolved_at` and `resolved_by_user_id` for every
  status, so a reopened row read as pending *and* closed and anything counting by `resolved_at` counted
  it as done. Reopening now clears both stamps
- **Reset Default Themes still told operators to hard-refresh** — the one instruction the cache fix
  above made obsolete, on the very page that runs the reset, contradicting both the runbook and member
  Help. It now says to reload
- **The same wishlist refusal read two different ways.** A child account blocked from requesting games
  got the GT-B1 envelope from a game page and a hand-rolled `{ok: false, …}` with no `error_code` from
  Library multi-select, because `POST /api/games/batch/wishlist` was never migrated alongside
  `POST /api/requests`. Both `can_request_games` denials answer through `api_error` now
- **The patch catalog's disabled-module 403 skipped the envelope**, so one endpoint reported failure in
  two shapes depending on which guard tripped; the same 403 was also copy-pasted into both routes and
  had already drifted. It is one helper now, and `POST /api/patch-catalog/attach` returns its success
  through `api_ok` rather than passing a helper's hand-rolled `ok` straight to `jsonify`. Baseline
  **849 → 846**
- **The envelope ratchet was counting an optimistic number**, which matters more than any single route
  because every migration wave steers by it. It only inspected `jsonify({...})` **dict literals**, so an
  envelope assembled anywhere else was invisible — which is how `patch_catalog.py` was recorded as
  migrated (6 → 2) with its main success path still hand-rolling `ok`, and how `wishlist.py` left the
  baseline altogether with three such returns in it. It now also resolves `body = {…}` → `jsonify(body)`
  and `jsonify(helper())` for bare functions defined in the file or imported absolutely from inside
  `oneirodex/`. Attribute calls like `obj.to_dict()` are deliberately left alone: they cannot be tied to
  one definition, and their `status` is usually a real field rather than an envelope — a lint that cries
  wolf gets `--update`-ed away, which is the one outcome that breaks a ratchet. **The recorded count
  went 846 → 856, and the rise is the point**: those ten call sites were always there, and four of them
  sit in files that had looked clean. `--list` prints every site with the reason it counted
- **Four surfaces the blind spot had been hiding now answer through the envelope** — image delete and
  unmatched-folder toggle in `routes.py`, orphan version cleanup, and free-game claim assist — together
  with the sibling failure branches in the same handlers, so no handler answers in two shapes. Baseline
  **856 → 847**. Six of the ten stay recorded on purpose, because the legacy key there is *data, not an
  envelope*, and "migrating" them would corrupt a response: `preview_hardlink()` returns
  `ok: would_succeed`, so `api_ok` would overwrite a real "no, this would not work" with `True`;
  `ollama_status()` reports `error` as the reason Ollama is unreachable on an otherwise fine 200, and
  `api_ok` strips that key outright; `/healthz` returning `{status: 'ok'}` is the liveness contract three
  runbooks `curl -f` against. **The ratchet's job is to stop growth, not to dictate migration** — a
  tolerated entry is sometimes the permanent right answer
- **The SPA was showing members developer strings instead of the sentences the backend sends.** Every
  one of the 25 `api/` wrappers hand-rolled its own failure path, and they had drifted into two broken
  tiers. The worse one never read the body at all — `throw new Error(\`announcements ${status}\`)` — and
  since `PageStatus` renders an Error's message as the headline, a household member hitting a 403 was
  shown **"announcements 500"** rather than "Free games are switched off". The milder one read `error`
  but dropped `error_code` and `status`, which is exactly what the detail line renders. Both are
  invisible in review because each file reads fine alone; only the set is wrong. One
  `errorFromResponse()` now serves all of them, 28 call sites across 22 modules, and
  `envelopeContract.test.js` asserts the set rather than naming files — a new wrapper is free to appear,
  it just has to use the helper. Two failure paths are exempt with reasons: `/settings_panel` renders
  HTML, and `discover.js` guards a content-type after an *ok* response. The first version of the guard
  only looked for a `new Error()` directly after `if (!response.ok)`, which missed the same flattening
  one level down inside a helper — `tokens.js` had a tidy-looking `readError()` doing exactly it, and
  five more sat in `batchActions.js`. What identifies the bug is reaching for `data.error` to build an
  Error, wherever that happens, so that is what the guard matches now: **ten further sites across six
  modules**. Wrappers that need the parsed body on the success path use `errorFromBody()`, because a
  Response body can only be read once and calling the response-reading variant after that would quietly
  yield the developer string again
- **Six api wrappers could send an empty CSRF token, and the 403 said nothing about why.** Fifteen
  modules each carried their own token lookup, in **nine variants** that differed in exactly the place
  that matters — how many sources they try. Nine walked `meta → input → #csrf_token`, three stopped at
  the input, and two read only the meta tag, so on any page rendering the field rather than the meta tag
  those two sent `''` and the request failed with nothing to diagnose. One `csrf.js` now holds the
  **superset** chain, so consolidating widened every narrow copy and narrowed none, and six modules that
  had been bypassing `window.CSRFUtils` (its own fallbacks, plus a script-element source and a cache)
  now go through it like the rest. The contract test rejects a local redefinition or a hand-built
  `X-CSRFToken` header — it caught two stragglers on its first run
- **Collections answers entirely through the envelope** — the first whole file taken to zero rather than
  a route at a time, **26 → 0**, baseline **847 → 821**. Five of its handlers opened with the same six
  lines (look the collection up, 404 if absent, 403 if the caller may not edit it), so those became one
  `_editable_collection()` and the refusal wording can no longer drift between them. The messages stop
  being developer strings — "Not found" becomes "Collection not found", "Forbidden" becomes "That
  collection belongs to someone else" on a write and "That collection is private" on a read, which are
  different refusals and used to read identically. The two sentences `test_collections_api_wiring.py`
  greps for are kept verbatim
- **Storage, API tokens and attract mode answer through the envelope** — baseline **175 → 151**.
  Two more `str(e)` values stop reaching the browser — both were already being logged, so nothing is
  lost by not also shipping them. `storage.py` keeps one site, now annotated: `preview_hardlink()`
  returns `ok: would_succeed`, the answer to *"would this hardlink work"* rather than *"did the request
  work"*, and `api_ok` stamps `ok=True` — which would turn every "no" into a "yes"
- **HLTB, game mods, game servers and the SMTP test answer through the envelope** — baseline
  **209 → 175**. `hltb.py` no longer imports `jsonify` at all. One more raw `str(e)` — a database
  exception, which can carry connection and schema detail — stops reaching the browser on SMTP save.
  **The SMTP *connection test* deliberately keeps answering 200 with `success: false`**: the request
  itself succeeded and only the thing it tested failed, `admin_manage_smtp_settings.js` branches on
  `data.success`, and the test says so in a comment. The SMTP *settings* save keeps its `status` for
  the same script
- **IGDB, quality stats, reference sets and related media answer through the envelope** — 12 each → 0,
  baseline **257 → 209**. Two IGDB endpoints were **answering HTTP 200 with an error body**, so a
  client branching on status saw a missing parameter or an upstream failure as success. They answer
  400 and 502 now; the only consumer (`admin_game_identify.js`) never checked status, so nothing
  relied on the old codes — but two tests pinned them, and both are updated with the reason rather
  than silently relaxed
- **Libraries, ownership and social answer through the envelope** — 15 / 15 / 13 → 6 / 0 / 0,
  baseline **294 → 257**. The friend-request path needed care rather than conversion: it builds one
  anti-enumeration response and returns it from two places, so an unknown username is indistinguishable
  from a real one. `api_ok` already returns `(body, status)`, so the `, 200` at each return site had to
  go with it — and the lint's double-wrap guard would not have caught that form, because the value
  arrives through a variable rather than a literal call. `test_social_friends_enum.py` still passes.
  `library.py` keeps six on purpose, now annotated: three batch refusals carry the scan-queue
  `status: 'rejected'`, one `ok` is computed (`started > 0`, meaning "did any delete start"), and
  `admin_manage_libs.js` reads `data.status === 'success'` off another
- **AI assist, the user API and admin settings answer through the envelope** — 17 / 17 / 16 → 1 / 0 / 0,
  baseline **343 → 294**. `user.py`'s play-status responses keep their `status` key: there it is the
  game's own state (`beaten`, `unplayed`), not an envelope marker, and the same is true of AI config's
  `status: 'saved'`. `settings.py`'s `status: 'error'` **was** the marker and is gone — checked first
  that its only caller, the integrations template, reads `response.ok` and `data.message`, both of which
  `api_error` still provides. The one site left in `ai_assist.py` is annotated: `ollama_status()` reports
  `error` as *why* Ollama is unreachable on an otherwise fine 200, and `api_ok` pops `error`, so
  wrapping it would delete the field the endpoint exists to return
- **Acquire, companion client and emulator saves answer through the envelope** — **19 / 19 / 17 → 0**,
  baseline **398 → 343**. All three were single-shape files, so the conversion was mechanical; the two
  keys that needed a decision both stay as payload data — the acquire readiness `message`, and the
  delete-save `status: 'deleted'`, which is an outcome rather than an envelope marker
- **Three more surfaces answer through the envelope** — system settings **23 → 0**, cover art studio
  **21 → 0**, downloads **20 → 2**; baseline **460 → 398**. Downloads had the same three-guard opening
  (malformed uuid, missing game, no access) in three handlers, now one `_downloadable_game()`. Its two
  remaining sites are annotated: the download request's own `status` is data, and the missing-file
  refusal carries `code: 'path_missing'`, which `api/downloads.js` reads and which **`api_error` cannot
  carry — `code` is its own parameter for the error_code**. That is the second key, after `status`, the
  helper's signature blocks. Deleting a download request now answers with `error` as well as `message`,
  so the member finally sees "Download request not found" rather than a status code
- **The legacy `routes.py` answers through the envelope where it safely can** — **38 → 13**, baseline
  **485 → 460**. Four more handlers were passing `str(e)` to the browser; those log and answer with a
  sentence, including the three that stay on `jsonify`, because fixing a leak never required migrating
  the shape. The thirteen that remain are the `status` state machine `admin_manage_libs.js` drives —
  it branches on `'error'`, `'success'`, `'started'`, `'connected'`, `'completed'` and `'not_found'`,
  and four tests assert on it. There is also a structural reason they cannot move: **`api_error`'s own
  signature takes `status` as the HTTP code**, so it cannot carry a legacy `status` key at all.
  `api_ok` can, through its payload dict, which is why the success half of that family did migrate
- **The envelope lint also rejects a double-wrapped response.** `return api_ok({...}), 200` nests the
  `(body, status)` tuple the helper already built, and Flask rejects it — while compiling cleanly and
  carrying no legacy key, so neither the interpreter nor the call-site count notices. Caught twice
  while converting multi-line literals, where the closing `}), 200` survives the rewrite
- **Scan management answers through the envelope** — `scan.py` **43 → 7**, baseline **521 → 485**.
  Seven stay and are annotated where they sit: `status` there is the **scan-queue contract**, not the
  legacy marker — `scanQueuePolicy.js` documents it as `'queued' | 'started' | 'rejected'` and
  `admin_manage_scanjobs.js` branches on `status === 'rejected'`. The per-item `ok` inside each
  `results` list is untouched for the same reason: it answers "did this folder succeed", not "did the
  request succeed"
- **The envelope lint now rejects a response that is built and thrown away.** `api_ok`/`api_error`
  both build a response *and* return it, so a call in statement position means a handler computed a
  refusal and then honoured the request anyway. Not baselined — it is never legitimate. Found the hard
  way: a migration regex ate the `return` on eleven guards in one file, and exactly one of the eleven
  had a test covering that path, so the suite reported a single failure for eleven broken validators
- **Admin artwork answers through the envelope** — `routes_admin_ext/images.py` **37 → 0**, baseline
  **558 → 521**. Two handlers passed `str(e)` from a bare `except Exception` to the browser; those now
  log and answer with a sentence. The unwritable-`IMAGE_SAVE_PATH` refusals keep every field they
  carried — `image_save_path`, the zeroed counters, the `errors` list — because the Images page renders
  them to explain *why* nothing downloaded, and a refusal that drops them would just look broken
- **Library tools answer through the envelope** — `library_tools.py` **32 → 0**, baseline
  **590 → 558**. This was the `{'status': 'ok'}` family, the third of the five competing shapes and the
  one that needed checking rather than converting: `status` is a real field name as well as an envelope
  marker. Here all 27 were the marker (`'ok'` or `'error'` and nothing else), and the admin clients read
  `response.status` and `data.message || data.error` rather than the body's `status`, so dropping it is
  safe. `routes.py` keeps its own — the same key there carries genuine scan-job state (`starting`,
  `deleting_games`, `completed`), which is data
- **Admin discovery sections and zones answer through the envelope** — `routes_admin_ext/system.py`
  **40 → 0**, baseline **630 → 590**. Another single-family file: all 40 sites used `{success, error}`,
  which `api_error` still mirrors, so the admin SPA is unaffected. The seven `Internal server error`
  handlers were already doing the right thing — logging the exception and returning a generic sentence —
  so they only changed shape
- **Metadata providers answer through the envelope, and an upstream failure is now nameable** —
  `providers.py` **29 → 0**, baseline **659 → 630**. Five search endpoints refused a missing `q` in
  their own words and four spelled out the same "not configured" 503; both are one helper now, with
  `provider` still riding along as an envelope extra because the admin UI uses it to link to that
  integration's card. **`bad_gateway` (502) joins `ERROR_CODES`** — fifteen route sites across five
  files already returned a bare 502 with nothing to branch on, and "the provider answered badly" is a
  different operator action from "we broke" (`internal`) and from "the integration is switched off"
  (`unavailable`)
- **The admin user editor answers through the envelope** — `routes_admin_ext/users.py` **36 → 0**,
  baseline **695 → 659**. This file used the *other* legacy shape throughout — `{success, message}` at
  all 36 sites — which is exactly the case the envelope was designed to absorb without breaking
  anything: `api_error` still mirrors `message` and `success`, so the admin SPA reading them is
  unaffected. Six validator refusals in a row became one lazy `_first_refusal()` that takes callables
  rather than results, so `check_username_unique` still does not hit the database when the username was
  already rejected. The refusals inside conditional branches stay written out — one of those pairs mixes
  a 400 with a 403, and folding it into a single-code helper would have hidden that
- **Chat answers entirely through the envelope** — `chat.py` **38 → 0**, baseline **733 → 695**. Ten
  handlers answered a bare `'Not found'`, across four different causes; they are one
  `_refuse_not_found()` now, with the reason for the opacity stated once instead of being folklore —
  a 403 would confirm that a channel someone cannot see exists. Channel lookups collapse into
  `_visible_channel()` / `_active_channel()`. The `str(exc)` passthroughs are kept: unlike the raw
  system exceptions in `game.py`, the chat helpers raise `PermissionError`/`ValueError` carrying a
  sentence written for the member
- **A test could only pass once against the shared test database.**
  `test_chat_spaces_voice_acl.py` committed a game with a hardcoded unique `igdb_id`, and `conftest`'s
  `db_session` deliberately never rolls back — `drop_all` is commented out for speed, so rows survive
  the run. The first run left the row behind and every later run died on a `UniqueViolation` that looks
  nothing like its cause. Now derives the id the way `test_library_health_pulse` already did
- **Chat spaces answers entirely through the envelope** — `chat_spaces_api.py` **28 → 0**, baseline
  **761 → 733**, and `jsonify` is no longer imported there at all. Seven handlers opened with the same
  "space not found" 404, one of which also rejected an archived space; `_refuse_missing_space()` carries
  both so the two wordings cannot drift. The deliberate white lie stays: a child account asking for a
  voice channel that is not child-safe still gets "Voice channel not found" rather than a 403, because
  the refusal should not confirm the channel exists
- **The game API answers through the envelope** — `routes_apis/game.py` **41 → 6**, baseline
  **796 → 761**. Five handlers shared the "load the game, 404, check access, 403" opening and had
  already drifted — the details endpoint said "Access denied" where the other four said "Forbidden",
  for the identical check — so that is one `_refuse_inaccessible_game()` now. **Four handlers were
  handing raw exception text to the browser** (`str(e)` from a failed commit, a library move, an IGDB
  id lookup), which can carry filesystem paths; those go to the log and the browser gets a sentence.
  The six that stay are recorded on purpose and annotated in place: five batch endpoints answer
  `ok: len(errors) == 0`, which means *"did every item succeed"* rather than *"did the request
  succeed"* — the SPA reads `data.ok !== false` to flag a partial batch, so routing those through
  `api_ok` would stamp them `True` and hide the failures
- **Cheats answers entirely through the envelope** — `emulator_cheats.py` **25 → 0**, baseline
  **821 → 796**. Five handlers shared the same four-line "load the game, 404, check access, 403"
  opening, now one `_accessible_game()`. The `cheat_surface` key both refusals carry — the one the
  Cheats and PC-cheats panels mount on — rides through as an envelope extra, so the surface-mismatch
  responses keep telling the client which panel belongs there
- **Moving the tile-size slider and navigating away left two timers running.** Neither was ever
  cleared: the transition-suppression class lives on `<html>` rather than on anything React unmounts, so
  leaving the library mid-drag stripped the tile-size transition for the rest of the session, and the
  debounced preference save fired from an unmounted component. The class comes off on unmount and the
  owed save is **flushed rather than dropped**, so the drag that was just made still persists
- **The admin SPA had the same duplication, one layer thinner.** `adminApi.js` was already the shared
  fetch module, but `SupportInboxPage` kept its own `csrfToken()`, `AnnouncementsPage` kept a whole
  private `postJson` / `getJson` pair — missing the 401→`/login` redirect every other admin call has —
  and **eleven** sites built the `X-CSRFToken` header by hand, three of them inside `adminApi.js`
  itself. All of it now goes through `csrfHeaders()`. The four error paths in that module also threw a
  bare `Error(message)`, so a page could show the sentence but could not tell a 403 from a 500;
  `adminError()` keeps `status` and `error_code` on the Error. Unlike the member app, the narrow
  meta-tag-only token lookup was **not** an active bug here — `base_admin.html` always renders the meta
  tag — so widening it is consistency rather than a fix. `ops-glance` was already clean
- **The CSS token ratchet could not be run locally on Windows.** `cssTokenLint.test.js` died with
  `SyntaxError: Invalid or unexpected token` before collecting a single test, because `.gitattributes`
  said only `* text=auto` — so a Windows checkout got `scripts/css-token-lint.mjs` with CRLF, and Vite's
  transform rejects a CRLF `.mjs` (sibling `.js` files are fine; it is specific to the extension). CI
  checks out LF and never saw it, so the gate was working *there* while a local `npm test` was red for a
  reason unrelated to whatever you had changed — the surest way to teach people to ignore a failing
  suite. `*.mjs text eol=lf` pins it and the four `.mjs` files are re-materialised
- **The unmatched-folder AJAX path never rolled back its failed transaction** — `db.session.rollback()`
  sat after the `return`, so only the non-AJAX branch reached it — and it handed the raw SQLAlchemy
  error text to the browser. The rollback now runs before either branch returns, and the exception
  detail goes to the log while the browser gets a sentence
- **Success responses were missing the `error` and `error_code` keys the envelope promises.** `api_ok`
  stripped them and never put them back, so a client reading `data.error_code` got `undefined` on the
  way through and a real token on the way out. They are present and `null` on success now, which is what
  the contract said all along
- **A completed theme reset stayed invisible for up to an hour** — the reason a run of CSS fixes looked
  like they never landed. `asgi.py` served every static file with `public, max-age=3600` and **no
  validator** (no ETag, no `Last-Modified`), while Reset Themes rewrites
  `static/library/themes/<theme>/…` *in place* behind an identical URL. Nothing about the request
  changed, so the browser cache answered for the full hour and only a hard refresh appeared to fix it.
  Both halves are closed: `theme_asset` appends a version derived from the file's mtime and size so
  replaced bytes produce a new URL (memoised, since a page links a few dozen of these and the tree can
  sit on a network path — Reset Themes clears the memo, which is what makes a reset visible), and the
  static handler serves `/static/library/themes/` with `no-cache` so even an unversioned reference
  revalidates. Hashed SPA bundles, images and fonts are content-addressed and keep the hour
- **One scan announced itself several times.** New-game alerts coalesce into a five-second window, so
  any pause longer than that — a slow scrape, a large file, a rate-limited provider — flushed the digest
  mid-scan and announced a library that was still filling, producing a run of "N games added" alerts with
  different Ns. Scan completion was the signal that was missing: `flush_library_add_digest()` is now
  called when the job is marked Completed, cancelling the pending timer and emitting once with the
  finished count. Safe when nothing is pending, and wrapped so a notification failure can never fail a
  completed scan
- **Tile menus rendered underneath the tiles below them.** Virtual rows are absolutely positioned *and
  transformed*, and a transform creates a stacking context — which trapped `.game-card`'s `z-index: 20`
  inside its own row, so the next row painted over the open menu. That is why raising the card read as a
  correct fix and did nothing, and why it only ever happened in the library grid. The row is the level
  the menu lives at, so the row is what gets raised, scoped to `:has(overlay-open)` so rows never
  otherwise reorder
- **Dead space above and below library tiles, with pagination pushed far down.**
  `estimateGridRowHeight()` returned the bare cover height; the plain grid gets its row spacing from
  `gap` for free, but virtual rows are absolutely positioned, so that number *is* the spacing. Rows
  stacked flush and `getTotalSize()` ran short by one gap per row. The estimate now includes the gap and
  the row carries it as padding, so the measured height agrees
- **Top-right tile buttons were hard to see and ignored the theme** — flat `rgba(0,0,0,.7)` on a white
  hairline with a fixed white glyph, which vanished over light cover art. Repointed at `--od-surface` /
  `--od-border` / `--od-text`, and the menu offset now derives from the same stride as the button stack
  instead of a magic `82px`, so hiding or adding a control moves the menu with it
- **The scroll pair floated in a box instead of aligning to the rail.** `chrome/ScrollJump.css` had
  already been rewritten to sit in the rail footer, but a duplicate in `od-chrome.css` won on
  specificity and kept the old fixed-position bordered design. The duplicate is gone. The selection bar
  and filter panel also docked at a literal `3.25rem` — the comfortable-density top bar height — so they
  detached and floated over the tiles on compact; both read `--od-topbar-h` now
- **The Help quick-nav chips and section headers had no focus indicator**, clearing their outline and
  leaning on a treatment hover already produces, so a keyboard user could not tell focus from hover. Same
  visible ring as everywhere else now; the panel radius became a declared token rather than a raw `14px`
- **An empty News announcements panel held a column permanently.** `announcements` is an array, so
  `announcements &&` was true when empty and rendered a heading, a zero count and "No announcements yet."
  The empty state survives on the Admins tab, where the section *is* the page and silence would read as a
  failed load rather than an empty one
- **Emulated games ran far too fast with broken audio.** Nothing measured the display refresh rate:
  RetroArch defaults `video_refresh_rate` to 60 and `video_vsync` paces to rAF, so a 120/144/165Hz
  monitor ran the core **2–2.75× too fast**. `measureRefreshHz()` now samples 32 frames (median, with a
  hidden-tab guard) and writes the real rate. **Unverified on hardware — needs a >60Hz display**, since
  a 60Hz panel is exactly the case the old default already got right
- **Firmware you added did not appear.** `list_bios_files` was a flat `os.listdir` that skipped
  directories, so per-system sets (`bios/psx/`, `bios/saturn/`) left a populated volume reading as
  empty. Nested files are found, and *present but misplaced* is now reported distinctly from *absent* —
  libretro cores read the system root, so the two need different fixes
- **A duplicated settings row would have locked everyone out of login**
- **Firmware upload never sent a CSRF token**
- Oversized cover uploads crashed on Pillow 10+
- Upgrading from the legacy quality-profile format 404'd on first edit
- A completed setup recorded itself as parked on Features
- Collection detail rendered with no name under the new chrome
- The scan path used a single scraper source instead of finishing the cascade
- Tile hover was effectively invisible
- **Seven controls had no visible keyboard focus.** The show/hide password toggle removed its focus
  outline and put nothing back — on a field whose contents are hidden too — and five others (admin top
  bar links, theme links, scan filter chips, account nav, loading-motif specimens) shared one rule with
  `:hover`, so a focused control and a hovered one looked identical. Account nav was the worst: that
  same styling is its "current page" state, so focus and "you are already here" were the same picture
- **Disabled chrome buttons looked and behaved like live ones.** `.od-cbtn` had no disabled styling at
  all, so "Mark all read" with nothing unread, refresh while refreshing, and delete mid-delete were
  indistinguishable from working buttons — and still lit up on hover, so the one control that would not
  respond was the one inviting the click
- **Background workers shared the request's database session.** Six sites paired
  `@copy_current_request_context` with a raw `Thread`, which carries the request's session onto the new
  thread — including library deletion, which walks every game committing repeatedly. Replaced by
  `run_in_background()` ([oneirodex/utils/background.py](oneirodex/utils/background.py)), which runs the
  worker in its own `app_context` and so its own session, and logs failures against a named task instead
  of a bare traceback. None of these workers ever wanted a request context; the decorator was handing
  them one they did not use, and the shared session came along with it. Two sites also passed ORM objects
  or read attributes from the thread — those now snapshot ids and re-fetch. A leaked deletion worker was
  the cause of the flaky test suite, and it was masking a pagination bug that is now fixed too

### Removed
- **The classic `/admin/manage_users` editor**, at every layer — rail entry, page link, route resolver,
  Flask route, template, CSS and JS. The React roster at `/admin/users` is the only user editor; the
  invites page now points there. **A bookmark to the old path will 404.**
- **The admin theme picker and `POST /admin/themes/apply`** — grid, fetch and handler. Theme choice is
  Preferences' job; see *Changed*. The 16 tests that covered the route are rewritten as retirement
  guards rather than deleted, on the principle the files already had: "gone" is a contract worth
  asserting
- `templates/settings/settings_panel.html` — `/settings_panel` renders `modal_preferences.html`, so the
  file was rendered by nothing while holding a third copy of the theme picker, element ids and all
- The last SharewareZ-era leftover in code (`get_warez_folder_usage()`)

### Security
- **Child ACL on tokens, Acquire, and companion commands.** Session-cookie deny for `write:download` / `write:library` / `admin` now also applies to Bearer tokens, so an already-minted companion secret cannot be used by a child. Children cannot create those scopes (including the Desktop companion preset); Acquire search returns 403; `POST /api/client/commands` for download/install/update/uninstall/patch/mod-pack requires `write:download`. Thin-client tokens still work.
- **WebRetro front end is MIT.** Upstream LICENSE (Copyright (c) 2021 BinBashBanana) is in `static/vendor/webretro/LICENSE`; third-party notices no longer leave it unconfirmed. Libretro cores stay operator-provisioned.
- **DataTables and Cropper.js no longer load on every classic page.** Member `base.html` and the admin shell dropped them; Cropper is on admin library-create, DataTables on logs and download requests. jQuery stays for toast notify.
- **Provider cover fetch follows the same SSRF gate as `download_image`.** IGDB / SteamGridDB / GiantBomb / Meta Quest `fetch_image` went through raw `requests.get`. They now use `fetch_outbound_image` (`http_safe.safe_get` + `validate_user_outbound_http_url` on every redirect hop).
- **Outbound fetches pin the address that passed the SSRF check.** `http_safe.safe_request` connects to the resolved IP and puts the original hostname on `Host` / SNI, so a DNS rebind between check and connect cannot steer the socket onto loopback or link-local. Homelab `ALLOW_PRIVATE_LAN_URLS` still reaches RFC1918 connectors.
- **Classic pages no longer ship executable inline `<script>` or `onclick=`.** Jinja interpolations moved to JSON tags, `data-*`, or `<template>` islands; the JS lives under `static/js`. **CSP enforces by default** (`CSP_ENFORCE=true`). WebRetro WASM is a native `/static/*` document with baseline headers only, so Flask `script-src` is `'self'`. Set `CSP_ENFORCE=false` to report-only.
- **Newsletter no longer depends on Flask-Mail or the CKEditor CDN.** Send uses `smtp.send_email_quiet` like invites; the compose page is a textarea. CSP no longer allowlists `cdn.ckeditor.com`.
- **Edit Images no longer interpolates upload URLs into `innerHTML`.** Needs **Reset Default Themes** so the theme-volume copy of `game_edit_images.js` refreshes.

## [1.0.0-beta] — 2026-08-06

First beta of the 1.0 line. Everything previously tracked as *Unreleased* is
part of this release; the version was also unified — `VERSION`, `app_version`,
both SPA packages, the desktop client, the Compose image tag and the OpenAPI
contract had drifted across `0.1.0` and `0.2.0` and now all read `1.0.0-beta`.

> The desktop `tauri.conf.json` carries plain `1.0.0`: the Windows MSI installer
> requires a three-part numeric version and rejects a prerelease suffix.

### Breaking

- **`DATA_FOLDER_WAREZ` removed.** The deprecated alias, its `config.py` fallback, and a **live Compose volume fallback** are all gone; only `DATA_FOLDER_GAMES` is read. A deploy whose `.env` still sets only the old key will start with **nothing mounted at `/storage`** — rename the key before redeploying. Also dropped from `.env.example`, `.env.docker.example`, `.env.unraid.example`, and `install-linux.sh`.

### Security

- **Chat @mention fan-out leaked DM content to non-members.** The mention notifier matched *any* user whose name appeared in a message and skipped only those who were muted **members**, so a non-member matching the name was notified with the message body — including in DMs they had no access to. Membership is now required before a mention notification is sent.
- **LiveKit room authorization was name-shaped, not access-checked.** `user_may_join_room` only inspected the room-name string, so any authenticated user could mint a token for any room — including `household:party:<game-uuid>` rooms, whose UUIDs are visible in game-details URLs. Every room name now resolves to a real access check (`voice:<id>` → space membership · `household:party:<uuid>` → game access · `household:lobby` → non-child), and **anything unrecognised is denied** rather than allowed through.

### Added

- **Health probes** — unauthenticated `GET /healthz` (liveness) and `GET /readyz` (DB + startup init); Compose `healthcheck` uses `/readyz` instead of `/` — [docker-compose-deploy.md](docs/runbooks/docker-compose-deploy.md)
- **Ops services pulse** — Admin Ops summary includes LiveKit, malware/ClamAV, companion heartbeats, and scan/download queues — contract: [ops-summary.md](docs/admin/ops-summary.md)
- **Observability stub** — commented Compose `# profile: observability` + [observability-profile.md](docs/runbooks/observability-profile.md) (Prometheus not required)
- **CI test gate** — `.github/workflows/ci-tests.yml` (pytest core + member-app vitest)
- **Library grid virtualization** — `@tanstack/react-virtual` in member-app `GameGrid`
- **Command palette** — member SPA Ctrl/Cmd+K (`cmdk`) for nav + Preferences
- **Desktop secure token store** — Windows Credential Manager / OS keyring via Tauri (`keychain`); scrub plaintext token from `config.json`
- **External-facing scrub** — Class A docs/UI placeholders neutralized; GitHub PR/Issue templates (SCRUB-6); competitive catalog private vault
- **Icon packs** (Outline, Filled, Duotone, Pixel, Soft, Mono) — orthogonal to color themes; Preferences chips + `data-icon-pack` CSS; see [preferences-themes.md](docs/user/preferences-themes.md)
- Lite social (friends, Activity poll) + community chat URL; WebRetro save/cheat bridge; NZBGet in Acquire
- Security suite P0/P1 hardening + `tests/test_security_suite.py`
- **Wave 14–17 social:** presence, Activity SSE, profiles, notifications, DMs, household channels, @mentions, mute, reactions, search, threads, custom emoji (max 20), LiveKit voice lobby + spectator
- **Friends companion:** stay-open dock · `/social-companion` pop-out · Big Picture **Y** · desktop always-on-top friends window
- **Sec-B:** `ALLOW_PRIVATE_LAN_URLS`, `OIDC_LOCK_ROLES`, Bearer-only client lifecycle POST
- **Admin Users SPA** roster at `/admin/users` (classic editor `/admin/manage_users`); live Scans status polling; **Admin → Features** toggles (setup + ops)
- **Malware scan** (`ENABLE_MALWARE_SCAN`, ClamAV + heuristics) — default on when configured
- **Multi-region set completeness** chips via `set_completion_regions` on Systems
- ROM language / translation-patch hooks · free-games News shelf · WebRetro save polish
- Proxy login rate-limit runbook — `docs/runbooks/login-rate-limit-proxy.md`
- **Legal free sample ROMs** — `samples/free-roms/` + `scripts/fetch-free-roms.py` (NES/GB/GBA/Genesis/Atari 2600)
- **Docs media capture** — Playwright recipe `scripts/capture_docs_media.py` · screenshots + `docs/media/video/product-tour.webm` — [CAPTURE.md](docs/assets/readme/CAPTURE.md)
- **W23 — Spaces (servers with their own channels)** — `ChatSpace` / `ChatSpaceMember` / `ChatSpaceInvite`; `household` (everyone) vs `invite` (scoped, genuinely invisible to non-members) visibility; text **and** voice channels per space; invite codes with revoke; space rail UI — [social-and-voice.md](docs/user/social-and-voice.md#spaces-servers-with-their-own-channels)
- **W25 — Storefront Discover** — `curated_for_you` (unplayed titles in genres the member favourites, excluding what they already picked) and `upcoming` (release dates still ahead, reusing Calendar data — no new scraping) shelves; `hero` / `carousel` / `shelf` layouts; **shelves as scheduled events** via `starts_at` / `ends_at`; admin schedule API. Curation uses on-box signals only — no external recommender, nothing leaving the box. Empty shelves hide rather than pad — [discover-sections.md](docs/admin/discover-sections.md)
- **Related media on a game** — adaptations, tie-ins, novelisations, documentaries, soundtracks as a popup **before** screenshots and trailers. Context, not a tracker: no watched/progress/rating fields exist on the model, and download-shaped links are refused — [library-and-systems.md](docs/user/library-and-systems.md#related-media)
- **Theme fonts** — era-appropriate faces (8-bit · compact pixel · arcade · 32-bit/disc · CRT terminal) mapped per system by **era, not brand**; admin upload with extension allowlist, size cap, and magic-byte validation; operator drop-ins offered beside the built-ins. Manufacturer typefaces are **not** shipped, and the OFL font files are operator-supplied — `installed: false` is reported honestly so a picker can say so — [theme-fonts-and-images.md](docs/admin/theme-fonts-and-images.md)
- **Batch artwork upload** — drop a folder of prepared art; files match games by `<uuid>` or `<uuid>_<kind>`; per-file outcomes reported so one bad file cannot sink the batch
- **FEAT-D1 scan freshness** — check version / updates / DLC after a scan; **off by default** (`SCAN_CHECK_FRESHNESS`) because each check is outbound store traffic, capped by `SCAN_FRESHNESS_LIMIT` (50)
- **FEAT-D2 PC cheat notes** — notes, not a trainer: console command / config edit / save field / launch flag / note. Never writes a game binary, never injects into a process
- **FEAT-D3 generated cover art** — self-hosted A1111-compatible endpoint (AUTOMATIC1111 / SD.Next / Forge); **off by default**, nothing leaves your network; regenerating replaces only the previous *generated* image so hand-picked art is never clobbered; `comfyui` engine raises an honest "not implemented" rather than silently doing nothing
- **FEAT-D5 play rooms** — per-system rooms grouped by **setting** (CRT living room · arcade cabinet · handheld · disc era · desk) rather than by brand
- **FEAT-D6** — seamless free-game claim when a store is linked
- **Emulator BIOS manifest + runbook** — [emulator-bios.md](docs/runbooks/emulator-bios.md)
- 15 missing console platforms added to `LibraryPlatform` (now 72)
- **Sortable admin tables** (`DataTable`) — asc → desc → clear, numeric-aware, nulls last in both directions, never mutates the caller's array

### Changed

- **BE-DET-9 Fandom alias registry** — Soft alias · series · remaster · regional EN↔JP · soft-title adjacency expand search variants + proposal ranking · propose-first soft paths · hard auto-identify ≥**0.92** · **QA PASS 65/65** · fixture pack 50 soft · capability language only (no Class A lists in public docs) — [libraries-and-scans.md](docs/admin/libraries-and-scans.md)
- **BE-DET-8 Arcade / Neo Geo AES** — Set-folder peel (dump or MAME/FBNeo set basename) · propose-first on large ARCADE / compact set names · AES≠CD TGDB hard guard · threshold **0.92** · **QA PASS 141/141** (peel+Stage E) · be_det8 **14/14** — [libraries-and-scans.md](docs/admin/libraries-and-scans.md) · [libraries-and-scans.md](docs/admin/libraries-and-scans.md)
- **UID-004 Search name** — Admin Dupe glance + Unmatched operator label **Amend naming** → **Search name** (labels · tooltips · toasts); Kind Soft title/Utility intact — [libraries-and-scans.md](docs/admin/libraries-and-scans.md#unmatched-folders)
- **UID-016 Dupe side-by-side Compare** — Admin Dupe glance + Unmatched show This folder | Library game columns (path · size · date); soft-read UI + Backend null-safe `size_bytes`/mtime on list/`matched_game` (library from Game; folder size null until denorm) — [libraries-and-scans.md](docs/admin/libraries-and-scans.md#unmatched-folders)
- **Desktop distribution — unsigned only** — Windows code-signing certs will never be pursued; CI no longer has an optional `signtool` step — [desktop-code-signing.md](docs/runbooks/desktop-code-signing.md)
- Pin `requirements.txt` with `==` versions for reproducible 1.0 builds; Compose local image tag `oneirodex:0.2.0` (matches `app_version`)
- **OpenAPI / semver hygiene** — `docs/openapi/openapi.json` `info.version` **0.2.0** aligned with `app_version` / Compose image tag
- **Default `UVICORN_WORKERS=1`** in Docker (`startweb-docker.sh`, Compose, `.env*.example`); override to 2+ still allowed
- **Two-bar chrome (UIR).** One `AppBar` for identity and destinations, one `ContextBar` under it for what the current page can do. Page titles and ledes retire under `data-chrome="v2"` — a heading that says "Library" while you are looking at the library is the least useful pixel on the page — and header *actions* stay put until each page moves them in. Library, News, Notifications and Calendar have moved: their hand-rolled tab strips are now bar two's segmented control, and Calendar's two window selects are a badged popover. Admin's Jinja renders the same bars from the same stylesheet, pinned by `tests/test_chrome_parity.py`, because the two SPA builds cannot import from each other. Behind `ENABLE_NEW_CHROME` until every page has adopted it — [getting-started.md](docs/user/getting-started.md) (two-bar chrome)
- **Member SPA rebrand (wave 1):** browse routes (Discover, Library, Favorites, Downloads) serve a React Router shell from `frontend/member-app` (`member-app.js`), with Oneirodex top nav, design tokens, and Docker multi-stage build of `/static/dist/member-app/`
- Docs: progress, bug triage, preferences/themes, security, social-av plans; Discord/webhook promises excised; peer catalogs kept private
- Mobile density: FilterBar + PaginationBar + Chat touch targets ≤900px
- WebRetro cloud saves: export retries, `.mcr`/`.sav` pick, auto `_cmd_load_state` when available
- Tile size: continuous 0–100% slider (legacy S/M/L/XL mapped)

### Fixed

- **Steam metadata was never mapped onto games.** `storesearch` hardcoded `summary=None`, `appdetails` dropped genres / developer / publisher / release date, and Stage D called no enrichment at all — so a Steam-identified import arrived with empty checkboxes and no summary. Added a single mapper with fill-don't-clobber semantics plus a backfill endpoint for rows already imported.
- **The scan path still asked Steam and nothing else.** The multi-source cascade shipped wired into store/software identify and the repair endpoint, but the ordinary IGDB scan — how nearly every title arrives — kept calling the Steam-only enricher. Steam has no SNES ROM, so console libraries scanned in blank exactly as before. `enrich_game_all_sources` now runs the Steam pass only for PC-family platforms and continues through GOG/Epic/itch/Giant Bomb/MobyGames/RAWG/TheGamesDB while `summary`, `genres` or `developer` are still empty. The cascade gained a `skip` argument so Steam is not queried twice per title (also applied to the two older callers, which both hydrated by App ID and then re-searched Steam by name).
- **Emulated audio ran fast and glitchy.** `audio_max_timing_skew` was `0.15` — three times the usual `0.05` — with no `audio_sync`, so audio chased the browser's 60Hz vsync against NTSC's 60.098Hz and was repeatedly yanked back. Now `audio_sync` + `audio_rate_control` with a 0.005 delta and standard skew — [browser-play.md](docs/user/browser-play.md#audiovideo-tuning--wasm-limits-snes-and-friends)
- **`chat_spaces` migration omitted `created_at`** and so silently no-op'd its own Household adoption step (`updateschema.py` swallows per-statement errors)
- **BE-DET-10 image kinds:** 6 of the 8 kinds had no UI surface at all
- Tile control stack, badge corner clearance, overflow-*measured* "Show more" (was a 420-char guess against an 8-line CSS clamp), and page-size handling
- Cover title legibility (FEAT-D4): minimum title size floor raised from 14px, plus editable headline / subtitle and a clamped `title_scale`
- Setup wizard mid-flow redirect: step map includes Features (3) + IGDB (4); `/setup` no longer claims “already completed” while wizard is in progress
- `InitManager` back-compat alias for `InitializationManager` (setup seed helpers)
- Admin Features template extends `base_admin.html`; Integrations community chat POST route restored (`admin2.community_chat_settings`)
- Admin SPA `hasLegacyBody` detects `.od-admin-card` so Features Jinja is not pushed below an empty React hub
- `admin_required` role normalization; honest `/playromtest` messaging
- Docker Compose forces `DATABASE_URL` host `db` (stops Unraid `.env` `@localhost` loops)
- Entrypoint rewrites loopback DB URLs inside containers
- Local image tag `oneirodex:0.2.0` (matches `app_version`; no Docker Hub pull required for local compose)
- Env examples / NAS deploy docs clarified for Compose vs native installs

### Removed

- Discord webhook / bot integration (use Support inbox + in-app admin alerts)

### Emulation honesty

- **Browser vs companion** — in-browser Play only for systems with present WebRetro cores; heavy systems (GC/Wii/Dreamcast/3DS/PS2/Vita) are companion-preferred — no fake Play-in-browser CTA.
- **Deferred WASM** — PCE / Commodore / DOS browser unlock is discover-on-disk / operator-vendored, not a claim that every core ships in the image.
- **No scrape** — no romhacking.net (or similar) scrape; reference DATs are operator-uploaded; DRM storefronts stay ownership register-only.

### Still operator-owned

- Live Authentik smoke (operator secrets) — OIDC stays **opt-in** (`OIDC_ENABLED` off by default)
- Native Quest APK (PWA MVP ships in 0.1.0)
- Publish optional Hub image `chrisjrovira/oneirodex` when ready
- ClamAV daemon reachability for malware scan; LiveKit compose profile for voice; deferred WebRetro WASM (PCE/VICE/DOS)
- Optional Compose `observability` profile (Prometheus/Grafana) — stub only; see [observability-profile.md](docs/runbooks/observability-profile.md)

## [0.1.0] — 2026-07-24

First milestone release on the `feature/roadmap-q1-foundation` track (Oneirodex rebrand + gap close).

### Added

- Oneirodex package cutover (`oneirodex/`), Docker image `chrisjrovira/oneirodex`
- Optional *arr module (Prowlarr/Jackett + qBittorrent) and **arr→hardlink** pipeline (triple-gated)
- Release calendar, quality profiles, GiantBomb/PCGW providers
- Detail-page layout editor (order/visibility)
- Ollama AI assist + gated **auto-apply** rename (`ENABLE_AI_AUTO_APPLY`)
- Hardlink preview/apply helpers
- VR / Quest **PWA** browse at `/vr`
- OIDC / Authentik SSO (optional; local username/password always works)
- Desktop companion (Tauri) + signing runbook/CI hooks (later: unsigned-only product stance)
- Emulator save sync options, deeper en/es i18n, SVG playtime share cards
- Strategy docs, runbooks, OpenAPI artifact under `docs/`

### Changed

- Docker Compose now passes optional module flags (AI, VR, arr, OIDC, hardlinks)
- Setup and Integrations copy clarify that Authentik is optional for local installs

### Security / ops

- Hardlink and AI apply remain feature-flagged and path-sandboxed
- `SECRET_KEY` required; container refuses the placeholder

[Unreleased]: https://github.com/chrisjrovira/oneirodex/compare/v1.0.0-beta...HEAD
[1.0.0-beta]: https://github.com/chrisjrovira/oneirodex/releases/tag/v1.0.0-beta
[0.1.0]: https://github.com/chrisjrovira/oneirodex/releases/tag/v0.1.0

