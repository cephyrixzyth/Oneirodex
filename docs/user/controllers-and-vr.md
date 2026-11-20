# Controllers & VR / headset browse

> **Doc status:** Active

## Controllers (Big Picture)

Open **More → Big Picture** for a gamepad-first library rail.

| Action | Xbox-style | DualSense / PlayStation-style | Keyboard |
|---|---|---|---|
| Move | D-pad / left stick | D-pad / left stick | Arrow keys |
| Open game | **A** | **×** | Enter |
| Download | **X** | **□** | `D` |
| Attract / trailers | **B** | **○** | `B` |
| Friends companion | **Y** | **△** | (Friends button / `Y` on pad) |
| Exit / blur | — | — | `Esc` |
| First / last | — | — | `Home` / `End` |

Kid mode uses the same browse and open controls; parental ACL filters the list. Download and install controls remain visible but disabled for child accounts.

**Steam Deck / Steam Input:** If you launch the browser from Steam, Steam can remap controls. Oneirodex uses the browser Gamepad API — it does not ship a separate Steam Input profile yet.

**WebRetro / native emulators** use each core’s own binds — see [browser-play.md](browser-play.md).

## Library room and headsets

Open **Game Catalog → Library room → Explore in 3D** to enter the room with your full collection. **Play → VR → Open room** opens the same space with the VR catalog selected. The server’s VR browse setting controls both entrances.

| Activity | Controls |
|---|---|
| Browse | Select a cover on the library wall. Previous and Next turn the shelf. Select Full library or VR titles to change the collection. |
| Read | Selecting a cover moves you to the reading desk. Longer summaries have page controls. Add favorite and Remove favorite update your own library. |
| Spend time in the room | Select Lounge for the current theme’s interior. Select Library wall to return. |
| Desktop | Drag horizontally or focus the scene and use Left/Right to look. WASD moves, Home returns to the current station. The catalog below the scene also supports keyboard browsing. |
| Headset | Open the room on HTTPS (or localhost on the browser’s own machine). Choose **Enter headset** when the browser reports a compatible WebXR immersive session. Point a controller at a panel and select. Use the wall’s Exit XR panel or the headset’s system menu to leave. |

A standalone headset can enter through its browser. A PC headset needs a browser and active runtime exposing immersive WebXR. The ordinary catalog and desktop preview are available when headset support is absent. To run a game, follow its own browser, companion or streaming requirements.

### PSVR2 on a PC, step by step (VR-PC-1)

A PSVR2 is a SteamVR headset once the PlayStation VR2 PC adapter and the *PlayStation VR2 App* from Steam are installed — nothing Oneirodex ships or configures. Then: 1) on the gaming PC, connect the headset and start SteamVR; 2) in a desktop browser on that same PC, open Oneirodex → Library (or `/vr` for the large-tap view) and use **Big Picture** with the controller; 3) pick a title whose row says **Plays in VR** and launch it with the desktop companion — SteamVR takes over; 4) for a **Plays flat** title, launch it flat and watch it on the SteamVR desktop, or stream it with Moonlight to another seat. A **VR via community profile** title tells you a profile exists and links to its page; installing an injector is your own decision on your own PC, and Oneirodex never does it for you.

Android APK is a spike only.

The VR PWA does not keep signed-in pages or catalogue responses for offline use. Reopen `/vr` online after an update so the shared installer can retire the older private-data worker. Catalogue and details requests wait for that privacy update. If it cannot finish, reconnect and reload before browsing. A failed optional app installation does not prevent browsing once browser control is safe. Already-offline clients cannot receive the update until they reconnect.

### How a title plays in VR (`vr_compat`)

Beside the **VR** badge, every card and details payload carries `vr_compat`: `native_vr` (the title ships VR — derived from its IGDB perspective unless a librarian set otherwise), `injector_profile` (a community injector profile exists for it — Oneirodex links to the profile page and **never ships, installs or points at a shim**), `flat` (plays flat; use Moonlight to the household PC from a headset seat), or unknown. Librarians set it from the details page (`PATCH /api/games/<uuid>/vr_compat`); Library filters accept `?vr_compat=`. **Ways to play → In a headset** shows the three rows; the `/vr` hub filters by them (*Native VR* / *Community profile*); the details page carries the line under the play row.

### The record behind the line (INSP-40, `vr_profiles`)

Since v11 H3a a title can carry one **headset record per kind** — `native` (ships a VR mode), `injector` (a community profile exists; the record holds the **profile page** URL), `flat` (no VR) — with the runtime side when known (`openxr` / `openvr`) and a note. `vr_compat` derives from these rows when a librarian did not set it directly (a shipped VR mode beats a community profile), and the `/vr` hub admits a title whose only evidence is such a row. On the details line the record adds the runtime and a **Community profile page** link; librarians get **Add / Edit headset record** under it. API: `GET /api/games/<uuid>/vr_profiles`, `PUT …/vr_profiles/<kind>` (librarian; `profile_url` must be an http(s) page — `file:` URLs and paths are refused), `DELETE …/vr_profiles/<kind>`. It is a record and a link, nothing more: Oneirodex never ships, installs or points at a shim. Alembic `a1b2c3d4e5f6` adds `game_vr_profiles`.

The lounge has a Favorite shelf. Point at it to display the signed-in member’s favorites on the library wall. In the desktop preview, drag horizontally or vertically to look around. The arrow keys also turn and tilt the view, and Home recenters at the current station.
