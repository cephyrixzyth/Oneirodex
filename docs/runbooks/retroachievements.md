# RetroAchievements (R1/R2)

> **Doc status:** Active

Matches cartridge ROMs to community achievement sets by hash, so game details can
say a set exists and a member can see their own progress. **Read-only**: nothing
played in the browser unlocks anything — there is no rcheevos runtime in the WASM
shell — and the member copy says so.

## Turn it on

1. Sign in at retroachievements.org and open **Settings → Keys** for the *web API
   key* (not the Connect key).
2. In Oneirodex, open **Admin → Integrations → Metadata & art → Artwork &
   secondary → RetroAchievements connection** and save the account username and
   web API key. The key is stored in the Oneirodex database
   and is never shown after saving. This works for Docker and Unraid installs
   without editing container environment variables. Environment values, when
   present, take precedence over the saved admin settings.

   Alternatively, configure both values in the server environment and restart:

   ```
   RETROACHIEVEMENTS_USERNAME=the-account-that-owns-the-key
   RETROACHIEVEMENTS_API_KEY=...
   ```

   Both are required. With one missing, the Admin → Integrations panel shows what
   is missing, the plugin reports `available`, and no title claims a set.
3. Open **Admin → Emulators → Achievements** and use **Match** per system. Each run refreshes
   that console's hash index (cached 24h) and hashes every game on the platform that
   has a disk path, storing the match on the game.

Re-run Match after a scan adds titles. Hashes are cached per game, so a second run
only hashes what is new.

## What gets matched

| | |
|---|---|
| Systems | NES · SNES · N64 · GB/GBC/GBA · Mega Drive · Master System · Game Gear · 32X · SG-1000 · PC Engine · Lynx · NGP/NGPC · WonderSwan · Virtual Boy · ColecoVision · Intellivision · Vectrex · Odyssey² · Channel F · Jaguar · Atari 2600/5200/7800 |
| Not matched | Every disc system (PS1, Saturn, Sega CD, 3DO, Neo Geo CD, NDS…). RetroAchievements hashes those from track data in ways this build does not reproduce, and a wrong match is worse than none. |
| Archives | A `.zip` / `.7z` / `.rar` holding one ROM dump is hashed through to the dump. |

The hash is **not** `file_md5`. RetroAchievements strips an iNES/FDS header and sizes
the body from it, strips a 512-byte SNES copier header, strips Lynx/PCE/7800 headers,
and normalises N64 images to big-endian z64 order before hashing. That is why this
does not ride on the DAT matcher's `md5` column.

## Honesty rules

- `supports_achievements` is true only for a matched set that **carries** achievements.
  A matched set with zero is stored (`ra_game_id`) but promises nothing: no badge, no
  section, no CTA.
- Unconfigured is *no data*, never a silent empty list: the panel says exactly which
  credential is missing, and the plugin registry reports `available`.
- The member's RetroAchievements username is a public handle stored on
  `user_preferences.ra_username`. Oneirodex never asks for their RA password or key.

## API

| Route | Who | What |
|---|---|---|
| `GET`/`PUT /api/admin/integrations/retroachievements` | admin | Read credential state and save username/API key; never returns the key. |
| `GET /api/retroachievements/status` | admin | Configured? Per-console index size/age and matched counts. |
| `POST /api/retroachievements/match` | admin | `{platform, rehash?}` — refresh index if stale, hash and match. |
| `GET /api/games/<uuid>/achievements` | member | The matched set + this member's progress (cached 10 min) + `unlocks_here: false`. |
| `GET`/`PUT /api/me/retroachievements` | member | Their RA username. |

Provider endpoints used: `API_GetGameList.php` (`h=1&f=1`) and
`API_GetGameInfoAndUserProgress.php`. Both are GETs; nothing is ever written to
RetroAchievements.
