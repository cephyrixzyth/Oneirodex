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

Kid mode uses the same browse controls; parental ACL already filters the list. Download may be unavailable for child accounts.

**Steam Deck / Steam Input:** If you launch the browser from Steam, Steam can remap controls. Oneirodex uses the browser Gamepad API — it does not ship a separate Steam Input profile yet.

**WebRetro / native emulators** use each core’s own binds — see [browser-play.md](browser-play.md).

## Headsets (not Quest-only)

`/vr` (when admin enables **VR browse**) is a **large-target library** for any headset-friendly seat:

| You have… | Do this |
|---|---|
| **PSVR2 / Index / Vive via SteamVR** (PC VR) | On the **same PC**, open Oneirodex in Chrome/Edge (desktop window or SteamVR overlay browser) → `/vr` or Library. Use **Big Picture** with a normal gamepad for couch control. Sense controllers are for SteamVR games, not for driving the website. DRM-free Install/Play needs the **full** companion — thin is browse/social only. |
| **Quest / standalone** (friend seat) | Headset browser → `https://<server>/vr` → optional Add to Home (PWA). Play heavy titles via **Moonlight** to the household PC, or ask someone on the companion PC. No local install pipeline on the headset. |
| **No headset** | Normal Library + Big Picture on TV. |

### PSVR2 on a PC, step by step (VR-PC-1)

A PSVR2 is a SteamVR headset once the PlayStation VR2 PC adapter and the *PlayStation VR2 App* from Steam are installed — nothing Oneirodex ships or configures. Then: 1) on the gaming PC, connect the headset and start SteamVR; 2) in a desktop browser on that same PC, open Oneirodex → Library (or `/vr` for the large-tap view) and use **Big Picture** with the controller; 3) pick a title whose row says **Plays in VR** and launch it with the desktop companion — SteamVR takes over; 4) for a **Plays flat** title, launch it flat and watch it on the SteamVR desktop, or stream it with Moonlight to another seat. A **VR via community profile** title tells you a profile exists and links to its page; installing an injector is your own decision on your own PC, and Oneirodex never does it for you.

Android APK is a spike only.

### How a title plays in VR (`vr_compat`)

Beside the **VR** badge, every card and details payload carries `vr_compat`: `native_vr` (the title ships VR — derived from its IGDB perspective unless a librarian set otherwise), `injector_profile` (a community injector profile exists for it — Oneirodex links to the profile page and **never ships, installs or points at a shim**), `flat` (plays flat; use Moonlight to the household PC from a headset seat), or unknown. Librarians set it from the details page (`PATCH /api/games/<uuid>/vr_compat`); Library filters accept `?vr_compat=`. **Ways to play → In a headset** shows the three rows; the `/vr` hub filters by them (*Native VR* / *Community profile*); the details page carries the line under the play row.

### The record behind the line (INSP-40, `vr_profiles`)

Since v11 H3a a title can carry one **headset record per kind** — `native` (ships a VR mode), `injector` (a community profile exists; the record holds the **profile page** URL), `flat` (no VR) — with the runtime side when known (`openxr` / `openvr`) and a note. `vr_compat` derives from these rows when a librarian did not set it directly (a shipped VR mode beats a community profile), and the `/vr` hub admits a title whose only evidence is such a row. On the details line the record adds the runtime and a **Community profile page** link; librarians get **Add / Edit headset record** under it. API: `GET /api/games/<uuid>/vr_profiles`, `PUT …/vr_profiles/<kind>` (librarian; `profile_url` must be an http(s) page — `file:` URLs and paths are refused), `DELETE …/vr_profiles/<kind>`. It is a record and a link, nothing more: Oneirodex never ships, installs or points at a shim. Alembic `a1b2c3d4e5f6` adds `game_vr_profiles`.
