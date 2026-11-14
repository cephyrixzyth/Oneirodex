# Desktop companion

> **Doc status:** Active

Optional **Tauri** client under `clients/desktop/` for Install / Update / Uninstall / Play on your PC. The web UI still downloads archives to the browser; the companion extracts and launches locally.

## Connect

1. Open **Account → API tokens** (`/tokens`) — or create via `POST /api/tokens` if you prefer the API.
2. Create a token with the **Desktop companion** preset (`read:library` + `write:download` + `write:presence`), or **Thin client** for connect-only seats. A token needs `write:download` or `write:library` to acknowledge or release queued commands; read-only tokens can inspect permitted data but cannot change queue state. Bearer clients calling `POST /api/check_username` also need `read:social`.
3. Copy the one-time secret (`gt_<hexprefix>_<urlsafe-secret>`) — it is shown only once. The secret uses URL-safe base64 (`A–Z`, `a–z`, `0–9`, `_`, `-`), so **hyphens and underscores in the secret are normal**. Paste the **entire** `gt_…` string into Connect. Truncating at a `-` (or any earlier character) always fails auth. On plain HTTP LAN, browser clipboard may be limited — use **Copy secret** (copies the raw token only) or select the one-time secret field and Ctrl+C / ⌘C.
4. Open the companion, enter your Oneirodex **base URL** (`https://` is recommended. Plain `http://` is accepted only for `localhost`/loopback, private LAN addresses such as `192.168.x.x`, `10.x.x.x` and `172.16–31.x.x`, link-local `169.254.x.x`, the shared range `100.64.0.0/10` that Tailscale uses, IPv6 `::1` / `fc00::/7` / `fe80::/10`, and the supported local suffixes `*.local`, `*.lan`, `*.home.arpa`, `*.internal` and `*.localdomain`. Bare names such as `nas` are refused because resolver search domains can send them to another host; use an HTTPS name or the server's private LAN IP. The companion refuses other HTTP URLs before sending the token.) and token, then choose **Connect**. Paste is normalized (whitespace/newlines, BOM/zero-width, wrapping quotes, first `gt_…` match from labeled/HTML junk) — hyphens inside the secret are kept. Status distinguishes invalid shape, 401 (wrong/truncated secret), network/TLS/CORS, and OS credential-store failures. Companion console logs `[Oneirodex:connect]` / `[Oneirodex:keyring]` (prefix only, never the secret) when the server log is empty.
5. Library preview loads via search. Choose **Open full library** to open the server's `/library` catalog for titles outside the companion's 12-title preview; the page may ask you to sign in with your site account.
6. Status shows **Online** / **Offline (server unreachable)** / **Not connected**. The offline Installed shelf includes only previously verified titles that still have local install records and launchable states. Play and Reveal use local files; Download, Update, mods, and patches need the server. The shelf keeps a server/account/device binding and a one-way credential fingerprint, not the API token. It explains that server access can change while disconnected and local file access follows OS permissions. Web-queued commands remain pending until heartbeat recovers.

Existing tokens keep their original scopes. If an older companion token lacks `write:presence`, its heartbeat returns 403. Create a replacement with the Desktop companion preset, reconnect with its one-time secret, then revoke the old token. The additional scope permits device heartbeat; it does not grant library edits or social access.

**Thin client:** For connect-only seats (no Download/Install/Play), build `npm run tauri:build:thin` — user guide [thin-client.md](thin-client.md) · [desktop-code-signing.md](../runbooks/desktop-code-signing.md). Use the **Thin client** token preset (`read:social` / presence; no `write:download`). Optional thin API token uses the **same** normalize / shape / validate helpers as the full companion (**Validate token**); stored in the same OS credential store (not `config.json`).

**Security note:** The API token is stored in the OS credential store (Windows Credential Manager on Windows; Keychain / Secret Service elsewhere), not in plaintext `config.json`. Older installs that still have a token in JSON are migrated into the secure store on next Connect/load and scrubbed from the file. The server checks token scopes against the account's current role when delivering companion commands, so changing an account to `child` stops lifecycle command delivery even for an older token. Authenticated API calls reject redirects so they stay on the configured server; archive downloads use a separate destination check before their contents are read or written. Caveat: anyone with your Windows user session can still read Credential Manager entries for this app.

Game archive installs are limited to 250,000 entries and 200 GiB expanded by default. Before extraction, the companion checks the destination volume has space for the declared expanded data plus a 1 GiB reserve; extraction still enforces the expanded limit while streaming and preserves the prior install on failure. Operators can raise the entry limit with `ONEIRODEX_DESKTOP_MAX_GAME_ARCHIVE_ENTRIES`, raise the expanded limit with `ONEIRODEX_DESKTOP_MAX_GAME_ARCHIVE_EXPANDED_BYTES`, and adjust the reserve with `ONEIRODEX_DESKTOP_GAME_ARCHIVE_RESERVE_BYTES` in the desktop process environment. Missing, invalid, or zero entry/expanded limits fall back to the defaults. Free space remains the final bound.

During ZIP extraction, the game card reports progress. **Cancel install** stops the staged extraction and removes its temporary files; the existing install stays in place, and an interrupted first install remains available to install again.

Each game install is serialized while it is staged and promoted. If the companion stops during promotion, the next install attempt reconciles the matching temporary files: it restores the previous install or finishes a fully staged install, then cleans the abandoned generation. If recovery metadata is invalid or conflicting, the attempt stops and preserves the files for review.

## Friends window

**Open friends window** opens (or focuses) a compact always-on-top Tauri popup (~360×560) anchored to the **bottom-right** of the work area (Windows taskbar-aware via `screen.avail*`), pointed at `/social-companion`. It is a Steam/Discord-friends-style overlay — not a fullscreen takeover of the companion. A second click focuses the existing window (keeps wherever you dragged it). Browser fallback uses the same size/`left`/`top` features when not running under Tauri.

**Open full library** opens or focuses a separate least-privilege site window at `/library`, or opens it in a browser outside Tauri. It uses the Server URL currently in the form and may ask you to sign in with your site account. The companion API token is not included in the URL or passed to this webview.

### Auth: Friends vs main companion

| Window | How you authenticate |
|---|---|
| **Main companion** | Oneirodex **API token** stored in the **OS keyring** (Credential Manager / Keychain) after Connect — used for library, download, and lifecycle APIs |
| **Friends window** | Ordinary **site session cookies** in that webview — sign in with your household **site account** (same as the browser). The companion API token is **not** injected into Friends |

Signing in on Friends does not replace Connect on the main window, and Connect does not log you into Friends.

### Local account and server access

The Installed shelf uses titles previously verified for the same server, account, device and credential. A reachable server rejecting the token is shown as **Server access denied**. Local **Play** and **Show in Explorer** remain available for matching installed titles; downloads, updates, mods and patches require current server access. A refused API redirect or unexpected server response has its own error and does not imply an outage or prove token revocation.

On recovery, the companion refreshes account identity and the permitted library preview before enabling server actions. It also checks launchable local install IDs outside that preview through the game-details API, with at most four reads in flight. The Installed shelf caches those permitted installed titles independently of the twelve-title preview; **Open full library** remains the path to the wider catalog. Denied or missing titles are omitted from a successful refresh. A changed account identity clears the old catalog and requires Connect again.

The cache supports up to 5,000 installed titles. An over-capacity inventory or failed verification is reported explicitly and preserves the previous cache; it is not reported as a complete refresh. Newly completed local installs refresh their shelf metadata too. If that refresh fails, the local install remains successful and the companion reports that offline metadata is stale. Games and saves are not deleted by these metadata checks.

To switch accounts, enter the server and token and select **Connect**. The old catalog is hidden during validation. Only a successful verified connection replaces the saved profile; a failed attempt does not save the new credentials. Finish or cancel active local operations before switching or forgetting the account.

**Forget account and cached titles** clears the visible profile, saved server URL, OS credential entry and local title cache. It stops presence and playtime tracking, with a best-effort final session report. It preserves installed files, saves, local install records and running games. Partial storage or credential-store failures are reported so you can retry. Other Library/Friends windows keep their separate site sign-ins; the server token remains valid until you revoke it. Anyone with access to local game files through the OS may still use them.

| Situation | What you see |
|---|---|
| **No Server URL** | Status error — set Server URL first (no silent no-op) |
| **Server URL only (not Connect)** | Window opens from the **current Server URL field** (not a stale Connect auth base); sign in with your **site account** in that webview (companion API token not required) |
| **Companion Offline** | Window still opens/focuses; status warns the page may not load until the server is reachable again. Heartbeat Offline does **not** disable Open friends |
| **Already open** | Existing always-on-top popup is shown and focused (position preserved) |
| **Server URL changed while open** | Previous Friends webview is closed and recreated at the new `/social-companion` origin |

The Friends webview is least-privilege (browse only); install/launch ACLs stay on the main window.

## Lifecycle

The review source improves macOS executable discovery for extracted application bundles. When the search reaches an `.app`, it reads the declared main executable instead of searching its helpers. Missing, invalid, oversized or excessively complex bundle metadata is not guessed around. Native Mac and real packaged-game qualification are still pending for this discovery change.

Cancel, Escape or clicking outside the version picker stops the download without
changing the game's local state. Choosing the base version explicitly still
downloads it.

An installed game can launch while the server is unavailable. Play from a cached shelf does not request server playtime until the account verifies online. A reporting or registry-write failure leaves a successful local launch intact and shows tracking as unavailable. Recovery does not backfill the disconnected gap; the previous interval retains the server's existing limit of 120 seconds after its last heartbeat.

On Windows and Linux, a separate launch supervisor follows the executable and its verified child processes. Closing the companion leaves games running. A numeric process ID alone cannot attach another game; if the supervisor loses verified state, playtime reporting stops. A handoff through an already running external launcher may fall outside the verified family. The review source adds a macOS supervisor using a private per-launch GUI job and a boot-bound kernel family identity. Native Rust/helper checks pass on the hosted Mac runner; older Mac builds still follow only the directly launched executable. Real packaged launch/discovery and restart/account journeys remain separate checks.

On Windows and Linux, reopening and successfully reconnecting can resume a still-running verified launch from the same server, account, device and credential. Recovery starts a fresh reporting interval. It does not attach a process by name or number, and a changed credential or unverifiable record is not resumed. Multiple instances of one game share a reporter until all verified instances exit; another companion owning that reporter is disclosed. Forget clears recovery bindings and reporting while leaving games running.

If verification or a heartbeat fails, the status shows that reporting is unavailable; local Play and Reveal remain usable. Native helper checks pass on hosted Windows, Linux and Mac runners; the earlier mounted-UI checks remain separate. Actual packaged restart/account journeys, older/Intel Mac runtime and external launcher handoffs still require qualification. The review source wires Mac recovery to the same account checks, with current-boot family verification. Native Rust checks pass, while packaged Mac restart/account journeys still require qualification; this is not a claim that an existing Mac installer gained recovery.

Linux dependency note: the locked Tauri/GTK3 tree includes `glib 0.18.5`, affected
by [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html).
The advisory concerns string-variant iteration and is patched in glib 0.20+;
upgrading glib alone does not replace Tauri's GTK3 dependency chain. The current
Windows target does not include glib. Linux/Steam Deck release acceptance must
retain this upstream dependency risk; Windows tests do not resolve it.

| Action | Local effect |
|---|---|
| Download | Streams archive into the companion downloads folder (chunked append). When a title has more than one version, an in-window picker (arrow keys / Enter, Escape to cancel) chooses base vs. update/extra; a single version downloads straight away. |
| Install | Extracts ZIP into a staged installs generation and promotes it after success. Progress appears on the game card; **Cancel install** discards the stage and preserves any previous generation. |
| Update | Prepares a separate generation, carries forward missing base/save files, then atomically selects the new install. The generation it replaced is kept until the next update, then removed |
| Uninstall | Removes the install folder, then the archive, then forgets the game (a failed removal can simply be retried). No snapshot is copied unless an archive-retaining uninstall is requested |
| Play | Launches detected / stored exe |
| Cheat staging | Before RetroArch companion launch, downloads library `.cht` into `app_data/cheats/{gameUuid}/` **only when** launch/payload `cheat_surface=retroarch` (Wave 19 GM lock). Never stages for PCWIN/PCDOS/MAC/OTHER (`pc_wand` / soft-hide). Tauri ACL allows `downloads` + `cheats`. |
| Translation patch apply | When `ENABLE_ROM_PATCH_APPLY=true` and `FLIPS_PATH` is set, stages `.ips`/`.bps` under `app_data/patches/` and runs Flips CLI — [translation-patches.md](translation-patches.md) |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. **Arcade cabinets (INSP-43):** when a game carries a control family (`spinner` / `lightgun` / `trackball`), the companion appends the matching RetroArch input remap on launch, so a spinner game is not bound like a stick game; `joystick` and unknown families use RetroArch's own defaults. Oneirodex never ships a ROM, a MAME set or a remap for a family it was not told about. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. When a **profile** is active on the pack (INSP-37) the result names it — the companion stages exactly the profile's enabled set, in load order — a row's `requires` always land before it. **Apply refuses** a set whose loaders disagree with the pack default (*Loader mismatch — …*), and refuses an empty or short download before writing it; the next apply re-stages from the source URL. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. **Open save folder** (INSP-1) receives a templated path from the details page, expands `<home>` / `<winDocuments>` / `<winAppData>` / `<winLocalAppData>` / `<xdgConfig>` / `<xdgData>` for this PC through the OS path API, and reveals the folder; a placeholder this PC cannot fill is reported, never guessed. |
| Mod pack apply (MOD-3) | When `ENABLE_MOD_TRACKING=true` and the companion is **Online**, **Apply mods** fetches enabled mod metadata, downloads BYO `source_url` files into `app_data/mods/{gameUuid}/`, and applies them path-safely into the local install folder. **Offline:** button disabled — reconnect to fetch metadata and URLs. **WebRetro cannot apply PC mods** — companion-only. Queued web command: `apply_mod_pack` via heartbeat. When the pack names a **loader** (`loader` on a row, or the pack's `default_loader`), the apply result adds *Needs BepInEx installed — not managed here* — the companion copies mod files and never installs a loader. When a **profile** is active on the pack (INSP-37) the result names it — the companion stages exactly the profile's enabled set, in load order. |
| Show in Explorer / open path | Companion opens an absolute path in the OS file manager (Windows Explorer first; Finder / `xdg-open` elsewhere; on macOS the item is selected in its parent folder in Finder, and an app or other package is only ever revealed, never launched). Local installs: **Show in Explorer** on installed titles (path must sit under the companion installs root). Library / unmatched: web queues `open_path` via `POST /api/client/commands`; companion reveals when Online and the path exists on **this** PC. |

Game archive downloads are limited to 100 GiB. Install rejects archives with more than 250,000 ZIP entries or 200 GiB of declared or streamed expanded data by default. Operators can raise the entry and expanded-byte limits through the desktop process environment described above. Declared ZIP limits are checked before replacing an existing install, and actual expansion is bounded while writing. The browser fallback, which buffers archives in memory, is capped at 1 GiB.

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

**Safe path checks (companion):** absolute only · reject device paths (`\\?\…`, `\\.\…`, `\??\…`) always, and reject UNC paths (`\\host\share`, `//host/share`) unless they sit at or below a trusted share (below) — decided on the text of the path, before any file-system lookup: on Windows even checking whether such a path exists makes Windows authenticate to that host and leak the user's NTLM hash, and a queued `open_path` is chosen by the server · reject `..` segments · reject null/CR/LF · max 4096 chars · must exist on the companion host · local-install reveal also under `app_data/installs` · on macOS a folder is opened in Finder only when its name has no extension (any dot counts, so `Doom 3 v1.2` is revealed in its parent rather than opened); one named like a package (`Something.app`, `.bundle`, `.prefPane`, `.xcodeproj`, …), or a link that leads to one, is revealed in its parent folder instead, because `open` would launch it, and a queued `open_path` with `select: false` must never start a program. The companion does not know the server's library roots (the server never tells it, and the same folder has a different path on each PC), so queued `open_path` commands are not restricted to a root list on this side; the server allowlist above plus the checks in this paragraph are the guards.

The companion's own file operations (extracting an install, deleting, writing downloads and mods, launching a game, the update and uninstall snapshots) screen every path the same way before they look it up: a UNC or device path, or one that is not absolute, is refused with no file-system lookup at all. The one network path they accept is below the companion's own app-data folder, which sits on a file server when Windows redirects your profile (see Folder Redirection below).

Staged mod ZIP entries are also resolved beneath the canonical game install folder during extraction. An entry that would write through an existing symlink outside that folder is rejected. A mod pack is limited to 1 GiB of downloads, 4 GiB of expanded files, and 50,000 archive entries; the companion checks the full pack before applying files. ZIP archives and direct mod files are supported. 7z archives are rejected with a format message rather than copied into the game folder as if they had been applied.

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
| Download / Update buttons unavailable | Offline, access-denied or connection-error state | Reconnect with valid access; matching cached installs retain local Play and Show in Explorer. Recovery refreshes identity and permitted titles first |
| Friends window permission errors on install | Social webview has no FS ACL (by design) | Use lifecycle actions in the **main** companion window |
| Update button missing | Server didn’t flag updates | Refresh Connect; check freshness inbox on web |
| Extra update / uninstall directories | The one previous update generation (removed at the next update or uninstall), an archive-retaining snapshot, or a leftover from an update that failed part way | Keep the selected install and save backups; retry the operation. A failed update's own files (`…-update-<id>` folders and zips) are not removed automatically — review before manual cleanup |
| Cheat not applied in native RetroArch | Missing `cheat_surface=retroarch`, PC platform, or core needs Quick Menu load | Confirm browse/launch payload has `cheat_surface=retroarch` (not PCWIN/PCDOS/MAC/OTHER). Then Quick Menu → Cheats → Load Cheat File from companion `cheats/{uuid}/` |
| Apply patch fails / button missing | Flag off or Flips missing | Set `ENABLE_ROM_PATCH_APPLY` + `FLIPS_PATH`, or apply manually with Flips |
| Apply mods disabled / fails | Companion offline, no install, or empty mod list | Re-Connect (Online); install locally first; librarian must add enabled mods with BYO URLs. WebRetro cannot load PC mods. |
| Open path / Show in Explorer fails | Path missing on this PC, relative path, or companion offline for queued open | Use a mapped-drive or local path the companion can see; if the server uses a UNC `\\host\share` path, list that share under **Trusted network shares** (an untrusted UNC path is refused before it is looked up, and device paths are always refused); for local installs use **Show in Explorer**; keep clipboard / Auto Scan fallback on admin unmatched when companion is offline |
| Connect / thin client says *Refusing http://… your API token would be sent unencrypted* | Server URL is plain `http://` to a host outside the allowed local forms, including a bare name that may be expanded through resolver search domains | Use the server's `https://` URL; for a home server use its LAN IP, loopback, Tailscale `100.x.y.z` address, or a supported local suffix (`.local`, `.lan`, `.home.arpa`, `.internal`, `.localdomain`). Bare names such as `nas` require HTTPS. A URL saved by an earlier build that is refused now is shown in the status line when the companion or thin client starts, so it is not silently ignored |
| *Invalid game id from server* | The server sent a game id that is not letters / digits / `_` / `-` (1–64 chars) | Nothing was written. Report it to the server admin — such an id cannot be used as a folder name |
| *Refusing http:// mod source …* | A mod `source_url` is plain `http://` to a host outside your local network | The librarian should change the mod's source URL to `https://` |
| Mod download fails on redirect | A BYO mod source redirected; redirects are refused because the companion cannot safely validate every hop before staging files in the game install | Use a direct source URL without redirects |
| Game download fails with a redirect error | The configured server redirected an authenticated archive request | Serve the archive from the configured server URL without redirects. Redirects are rejected before archive bytes are read or written |

Related: [downloads.md](downloads.md) · [browser-play.md](browser-play.md) · [translation-patches.md](translation-patches.md) · [social-and-voice.md](social-and-voice.md) — Friends window section mirrors web dock / pop-out / Big Picture **Y**
