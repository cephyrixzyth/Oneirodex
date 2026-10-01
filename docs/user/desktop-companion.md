# Desktop companion

Optional **Tauri** client under `clients/desktop/` for Install / Update / Uninstall / Play on your PC. The web UI still downloads archives to the browser; the companion extracts and launches locally.

## Connect

1. Open **Account → API tokens** (`/tokens`) — or create via `POST /api/tokens` if you prefer the API.
2. Create a token with the **Desktop companion** preset (`read:library` + `write:download`), or **Thin client** for connect-only seats.
3. Copy the one-time secret (`gt_<hexprefix>_<urlsafe-secret>`) — it is shown only once. The secret uses URL-safe base64 (`A–Z`, `a–z`, `0–9`, `_`, `-`), so **hyphens and underscores in the secret are normal**. Paste the **entire** `gt_…` string into Connect. Truncating at a `-` (or any earlier character) always fails auth. On plain HTTP LAN, browser clipboard may be limited — use **Copy secret** (copies the raw token only) or select the one-time secret field and Ctrl+C / ⌘C.
4. Open the companion, enter your Oneirodex **base URL** (**`https://`** — plain `http://` is accepted only for `localhost`/loopback, private LAN addresses such as `192.168.x.x`, `10.x.x.x` and `172.16–31.x.x`, link-local `169.254.x.x`, the shared range `100.64.0.0/10` that Tailscale uses, IPv6 `::1` / `fc00::/7` (which covers Tailscale's `fd7a:115c:a1e0::/48`) / `fe80::/10`, `*.local`, `*.lan`, `*.home.arpa`, `*.internal` and `*.localdomain` names (the same list the server uses for its own household-host check) and bare single-word host names like `nas`; any other `http://` server is refused before the token is sent, with a message telling you to use `https://`) and token, Connect. Paste is normalized (whitespace/newlines, BOM/zero-width, wrapping quotes, first `gt_…` match from labeled/HTML junk) — hyphens inside the secret are kept. Status distinguishes invalid shape, 401 (wrong/truncated secret), network/TLS/CORS, and OS credential-store failures. Companion console logs `[Oneirodex:connect]` / `[Oneirodex:keyring]` (prefix only, never the secret) when the server log is empty.
5. Library preview loads via search; local lifecycle syncs with the server when available.
6. Status shows **Online** / **Offline (server unreachable)** / **Not connected**. After two failed heartbeats, Download and Update are disabled; Play, Install, and Uninstall still run locally. Web-queued Install/Update commands stay pending until heartbeat recovers (nack → retry).

**Thin client:** For connect-only seats (no Download/Install/Play), build `npm run tauri:build:thin` — user guide [thin-client.md](thin-client.md) · [desktop-code-signing.md](../runbooks/desktop-code-signing.md). Use the **Thin client** token preset (`read:social` / presence; no `write:download`). Optional thin API token uses the **same** normalize / shape / validate helpers as the full companion (**Validate token**); stored in the same OS credential store (not `config.json`).

**Security note:** The API token is stored in the OS credential store (Windows Credential Manager on Windows; Keychain / Secret Service elsewhere), not in plaintext `config.json`. Older installs that still have a token in JSON are migrated into the secure store on next Connect/load and scrubbed from the file. Caveat: anyone with your Windows user session can still read Credential Manager entries for this app.

## Friends window

**Open friends window** opens (or focuses) a compact always-on-top Tauri popup (~360×560) anchored to the **bottom-right** of the work area (Windows taskbar-aware via `screen.avail*`), pointed at `/social-companion`. It is a Steam/Discord-friends-style overlay — not a fullscreen takeover of the companion. A second click focuses the existing window (keeps wherever you dragged it). Browser fallback uses the same size/`left`/`top` features when not running under Tauri.

### Auth: Friends vs main companion

| Window | How you authenticate |
|---|---|
| **Main companion** | Oneirodex **API token** stored in the **OS keyring** (Credential Manager / Keychain) after Connect — used for library, download, and lifecycle APIs |
| **Friends window** | Ordinary **site session cookies** in that webview — sign in with your household **site account** (same as the browser). The companion API token is **not** injected into Friends |

Signing in on Friends does not replace Connect on the main window, and Connect does not log you into Friends.

| Situation | What you see |
|---|---|
| **No Server URL** | Status error — set Server URL first (no silent no-op) |
| **Server URL only (not Connect)** | Window opens from the **current Server URL field** (not a stale Connect auth base); sign in with your **site account** in that webview (companion API token not required) |
| **Companion Offline** | Window still opens/focuses; status warns the page may not load until the server is reachable again. Heartbeat Offline does **not** disable Open friends |
| **Already open** | Existing always-on-top popup is shown and focused (position preserved) |
| **Server URL changed while open** | Previous Friends webview is closed and recreated at the new `/social-companion` origin |

The Friends webview is least-privilege (browse only); install/launch ACLs stay on the main window.

## Lifecycle

Linux dependency note: the locked Tauri/GTK3 tree includes `glib 0.18.5`, affected
by [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html).
The advisory concerns string-variant iteration and is patched in glib 0.20+;
upgrading glib alone does not replace Tauri's GTK3 dependency chain. The current
Windows target does not include glib. Linux/Steam Deck release acceptance must
retain this upstream dependency risk; Windows tests do not resolve it.

| Action | Local effect |
|---|---|
| Download | Streams archive into the companion downloads folder (chunked append). When a title has more than one version, an in-window picker (arrow keys / Enter, Escape to cancel) chooses base vs. update/extra; a single version downloads straight away. |
| Install | Extracts zip into installs folder |
| Update | Prepares a separate generation, carries forward missing base/save files, then atomically selects the new install. The generation it replaced is kept until the next update, then removed |
| Uninstall | Removes the install folder, then the archive, then forgets the game (a failed removal can simply be retried). No snapshot is copied unless an archive-retaining uninstall is requested |
| Play | Launches detected / stored exe |
| Cheat staging | Before RetroArch companion launch, downloads library `.cht` into `app_data/cheats/{gameUuid}/` **only when** launch/payload `cheat_surface=retroarch` (Wave 19 GM lock). Never stages for PCWIN/PCDOS/MAC/OTHER (`pc_wand` / soft-hide). Tauri ACL allows `downloads` + `cheats`. |
| Translation patch apply | When `ENABLE_ROM_PATCH_APPLY=true` and `FLIPS_PATH` is set, stages `.ips`/`.bps` under `app_data/patches/` and runs Flips CLI — [translation-patches.md](translation-patches.md) |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. **Arcade cabinets (INSP-43):** when a game carries a control family (`spinner` / `lightgun` / `trackball`), the companion appends the matching RetroArch input remap on launch, so a spinner game is not bound like a stick game; `joystick` and unknown families use RetroArch's own defaults. Oneirodex never ships a ROM, a MAME set or a remap for a family it was not told about. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. When a **profile** is active on the pack (INSP-37) the result names it — the companion stages exactly the profile's enabled set, in load order — a row's `requires` always land before it. **Apply refuses** a set whose loaders disagree with the pack default (*Loader mismatch — …*), and refuses an empty or short download before writing it; the next apply re-stages from the source URL. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. **Open save folder** (INSP-1) receives a templated path from the details page, expands `<home>` / `<winDocuments>` / `<winAppData>` / `<winLocalAppData>` / `<xdgConfig>` / `<xdgData>` for this PC through the OS path API, and reveals the folder; a placeholder this PC cannot fill is reported, never guessed. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. When a **profile** is active on the pack (INSP-37) the result names it — the companion stages exactly the profile's enabled set, in load order. |
| Show in Explorer / open path | Companion opens an absolute path in the OS file manager (Windows Explorer first; Finder / `xdg-open` elsewhere). Local installs: **Show in Explorer** on installed titles (path must sit under the companion installs root). Library / unmatched: web queues `open_path` via `POST /api/client/commands`; companion reveals when Online and the path exists on **this** PC. |

When search marks `has_updates` (or `lifecycle_state=update_available`) and the title is locally **installed**, Connect flips it to **Update available**.

Updates prepare a new generation beside the working install. A failed download,
extraction, copy or registry replacement leaves that working install selected. After
restart, the registry selects either the old or fully prepared new generation. Save
files absent from the update are carried forward; files replaced by the archive remain
recoverable in the generation the update replaced. That one superseded generation is
kept until the next update (or until the game is uninstalled) and then removed, so at
most one extra copy of the game is on disk. No game-specific save-conflict merge is
attempted.

Uninstall removes the install folder, then the archive, and only then forgets the game.
Nothing is copied first, so it needs no spare disk space and cannot fail for lack of it.
If a file is locked (a running game, an antivirus scan) the uninstall stops with an error,
the game still shows as installed, and running **Uninstall** again resumes where it
stopped. A superseded update generation, and any snapshot left by an earlier
archive-retaining uninstall, are removed with it.

An archive-retaining uninstall (the `removeArchive: false` option; the companion's
**Uninstall** button does not use it) first copies the complete install (including local
saves) to a sibling `.uninstalled-…` snapshot and records it before removing active
files. Retaining the archive also retains that snapshot's record, so Install restores the
complete game and patch packs without downloading again. A failed restore can be retried
into a new directory. A snapshot uses disk space until the game is uninstalled for good;
review and back up saves before manually removing any obsolete copy.

Symbolic links and Windows junctions inside an install folder (a Wine prefix's
`dosdevices`, a save-folder junction) are never followed. Snapshots and update
generations skip them, and the data they point at stays exactly where it is — it is not
copied, moved or deleted. The game or Wine recreates its own links; re-make any you added
yourself.

Browser WebRetro still applies cheats via the in-page Emscripten FS bridge when `cheat_surface=retroarch`; use the companion path for heavy/native RetroArch systems when the browser FS cannot write. Author or upload `.cht` files on game details → **Cheats** (same library the play bar lists). PC / native (`PCWIN`/`PCDOS`/`MAC`/`OTHER`): notes or BYO trainer only — companion never stages `.cht`.

## Open path (Explorer / Finder)

The browser cannot open Unraid/host paths. When the companion is Online:

1. **Local install** — use **Show in Explorer** in the companion (no server command).
2. **Member library / admin unmatched** — queue `action: "open_path"` with an absolute `path` the companion machine can see (a mapped drive letter, a local mount, or a UNC `\\host\share` path whose share is listed under **Trusted network shares** — see below). Heartbeat delivers it; companion validates (absolute, not a device path, a UNC path only for a trusted share, no `..`, no control chars, path exists) then opens Explorer / Finder.

### How UI should invoke

| Caller | Call | Notes |
|---|---|---|
| Member SPA (game folder) | **OpenPathModal** → `POST /api/client/commands` `{ action: "open_path", path, game_uuid?, select? }` | Prefer admin `full_disk_path` / `server_path` or game disk path the household PC can resolve; clipboard fallback only — **no** Auto Scan jump |
| Admin unmatched / Dupe glance | Same queue with unmatched `folder_path` (`game_uuid` may be `""`) | OpenPathModal + clipboard when companion offline — **no** Auto Scan redirect |
| Companion itself | Tauri `reveal_path_in_os` via **Show in Explorer** (also heartbeat `open_path`) | Installs root allowlisted |

**Server allowlist:** enqueue rejects paths outside configured library roots (`DATA_FOLDER_GAMES` / `BASE_FOLDER_*`) and library `last_scan_folder` values — clear `400` with the validation message. `open_path` is allowlisted in `client_commands`. `GET /api/path/open` remains path-info only (admin).

**Safe path checks (companion):** absolute only · reject device paths (`\\?\…`, `\\.\…`, `\??\…`) always, and reject UNC paths (`\\host\share`, `//host/share`) unless they sit at or below a trusted share (below) — decided on the text of the path, before any file-system lookup: on Windows even checking whether such a path exists makes Windows authenticate to that host and leak the user's NTLM hash, and a queued `open_path` is chosen by the server · reject `..` segments · reject null/CR/LF · max 4096 chars · must exist on the companion host · local-install reveal also under `app_data/installs`. The companion does not know the server's library roots (the server never tells it, and the same folder has a different path on each PC), so queued `open_path` commands are not restricted to a root list on this side; the server allowlist above plus the checks in this paragraph are the guards.

**Mount caveat:** Docker/Unraid paths like `/mnt/user/games/…` will fail unless that exact path exists on the companion PC. Send the Windows/macOS-visible path (e.g. `Z:\games\…` for a mapped network drive, or the UNC path of a share you have trusted below).

### Trusted network shares (UNC library roots)

A Windows-hosted server is told to use UNC library roots (`ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=\\nas\roms`, see [remote-scan-locations.md](../runbooks/remote-scan-locations.md)), so a queued **Open folder** can name `\\nas\roms\Some Game`. Opening a network path makes Windows sign in to that computer, so the companion refuses it unless you have said you trust that share:

1. In the companion, open **Trusted network shares**.
2. Enter one share per line, as `\\server\share` (or deeper, `\\server\share\sub`). Server names are matched exactly (letters are not case-sensitive); `\\nas.local\roms` and `\\nas\roms` are different entries. Device paths, `..`, and a server with no share are rejected, and one bad line rejects the whole save with a message naming it.
3. **Save shares.** The list is kept on this PC (`trusted_shares.json` in the companion's app-data folder) and read fresh on every open; nothing the server sends can add to it.

A path is allowed when it is at or below a listed share, compared segment by segment — `\\nas\roms\Game` is under `\\nas\roms`, `\\nas\romsx`, `\\nas.evil.example\roms` and anything containing `..` are not. A refused path never reaches the file system, so with an empty list no network path is ever looked up.

On a domain PC where Windows Folder Redirection puts Documents, AppData or the profile on a file server, that server is already trusted by Windows. The companion treats the folders Windows itself reports for you (home, Documents, AppData, local data, config) as trusted when they are network paths, so **Open save folder** and **Show in Explorer** work without an entry.

## Limits (this polish pass)

- **Unsigned only (product stance).** CI ships unsigned installers for Windows (`.exe`), macOS (`.dmg`, universal) and Linux (`.deb` / `.AppImage`); code-signing certs will never be pursued, so expect a SmartScreen or Gatekeeper warning on first run ([desktop-code-signing.md](../runbooks/desktop-code-signing.md)).
- **Installing games works best on the platform the game was built for.** The companion restores archived permission bits when it extracts, so a native macOS/Linux build launches; a Windows-authored archive carries no executable bit and holds `.exe` files, which are not launchable on macOS or Linux regardless.
- Emulator systems that are companion-only still need the mapped core / external app — see [browser-play.md](browser-play.md).

## Troubleshooting

| Symptom | Likely cause | What to try |
|---|---|---|
| Connect 401 / 403 | Bad token, missing scopes, or truncated paste | Recreate token; need `read:library` (+ `write:download`). Paste the **full** `gt_<prefix>_<secret>` — hyphens/`_` inside the secret are normal; truncating after `-` always fails. Server logs `api_token_auth_failed reason=… prefix=…` (never the secret) when Bearer verify fails |
| Connect “invalid token” / bad shape | Extra chars copied with the secret, or cut at `-` | Use **Copy secret** on Account → API tokens (raw string only), or select the one-time secret field. Do not copy the name/prefix label line |
| Connect network / “failed to load” | Wrong URL, TLS/CORS, or server down | Check base URL (origin only); open companion DevTools for `[Oneirodex:connect]` — server may log nothing |
| Connect “Bad data” / credential store | OS keyring persist failed after validate | Check Windows Credential Manager; retry Connect; see `[Oneirodex:keyring]` in console |
| Connect 404 | Wrong base URL | Use origin only (no `/api` suffix) |
| Download / update fails with permission | Missing Tauri ACL for append/rename | Rebuild companion from this repo |
| Download / Update buttons disabled | Companion Offline banner | Re-Connect or wait for heartbeat; Play/Install/Uninstall still work |
| Friends window permission errors on install | Social webview has no FS ACL (by design) | Use lifecycle actions in the **main** companion window |
| Update button missing | Server didn’t flag updates | Refresh Connect; check freshness inbox on web |
| Extra update / uninstall directories | The one previous update generation (removed at the next update or uninstall), an archive-retaining snapshot, or a leftover from an update that failed part way | Keep the selected install and save backups; retry the operation. A failed update's own files (`…-update-<id>` folders and zips) are not removed automatically — review before manual cleanup |
| Cheat not applied in native RetroArch | Missing `cheat_surface=retroarch`, PC platform, or core needs Quick Menu load | Confirm browse/launch payload has `cheat_surface=retroarch` (not PCWIN/PCDOS/MAC/OTHER). Then Quick Menu → Cheats → Load Cheat File from companion `cheats/{uuid}/` |
| Apply patch fails / button missing | Flag off or Flips missing | Set `ENABLE_ROM_PATCH_APPLY` + `FLIPS_PATH`, or apply manually with Flips |
| Apply mods disabled / fails | Companion offline, no install, or empty mod list | Re-Connect (Online); install locally first; librarian must add enabled mods with BYO URLs. WebRetro cannot load PC mods. |
| Open path / Show in Explorer fails | Path missing on this PC, relative path, or companion offline for queued open | Use a mapped-drive or local path the companion can see; if the server uses a UNC `\\host\share` path, list that share under **Trusted network shares** (an untrusted UNC path is refused before it is looked up, and device paths are always refused); for local installs use **Show in Explorer**; keep clipboard / Auto Scan fallback on admin unmatched when companion is offline |
| Connect / thin client says *Refusing http://… your API token would be sent unencrypted* | Server URL is plain `http://` to a host outside your local network | Use the server's `https://` URL; for a home server use its LAN address, its Tailscale `100.x.y.z` address, a `.local` / `.lan` / `.home.arpa` / `.internal` / `.localdomain` name or a bare host name, which are all allowed over `http://`. A URL saved by an earlier build that is refused now is shown in the status line when the companion or thin client starts, so it is not silently ignored |
| *Invalid game id from server* | The server sent a game id that is not letters / digits / `_` / `-` (1–64 chars) | Nothing was written. Report it to the server admin — such an id cannot be used as a folder name |
| *Refusing http:// mod source …* | A mod `source_url` is plain `http://` to a host outside your local network (or redirects to one) | The librarian should change the mod's source URL to `https://` |
| *Refusing http:// download redirect …* | The server answered a game download with a redirect to plain `http://` on a host outside your local network | Fix the server or its reverse proxy so the download is served from, or redirects to, an `https://` URL. Nothing was written to disk |

Related: [downloads.md](downloads.md) · [browser-play.md](browser-play.md) · [translation-patches.md](translation-patches.md) · [social-and-voice.md](social-and-voice.md) — Friends window section mirrors web dock / pop-out / Big Picture **Y**
