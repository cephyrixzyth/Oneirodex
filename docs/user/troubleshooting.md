# Troubleshooting (members)

> **Doc status:** Active

Quick checks before pinging an admin.

## Blank / broken UI

| Symptom | Likely cause | What to try |
|---|---|---|
| Unstyled Discover/Library | Missing frontend build | Admin rebuilds image / `member-app` dist |
| Spin forever / Discover stuck on Loading while nav works | Old image without ASGI SSE fix, or companion SSE holding the only worker | Ask admin to rebuild from current tree (not restart alone) — [admin troubleshooting](../admin/troubleshooting.md#spa-navigates-but-pagesadmin-hang-discover-stuck-on-loading). Clear site data if Friends dock was stuck open. |
| Spin forever (API 401/500) | Auth / server error | Hard refresh; re-login; admin check `/awake` + logs |
| Chat, Release calendar (or another page reached from the rail) shows only the room scenery — no rail, no content | Server predates the module-identity fix: the shell linked the bundle with a `?v=` token while route chunks import it bare, so the page ran two copies of the app's context and unmounted itself | Fixed in the current tree — ask the admin to rebuild. Until then Game Catalog, Discover and Systems still work; Chat opens from any of them via the rail. |
| Theme didn’t apply | Server predates the constant-folding fix | Fixed — see [below](#a-new-theme-doesnt-appear-after-reload). On an older build only a server restart applied a theme change. |
| Font pref changed nothing | Server predates the `fonts.css` fix | Fixed — see [below](#the-font-preference-had-no-effect). On an older build no font choice, including the default, ever reached the page. |
| Preferences panel is blank / errors | Server predates the room-card picker Jinja fix | Fixed — see [below](#preferences-will-not-open). On an older build the theme picker crashed while rendering. |
| Can’t find a page | Nav clutter | **Ctrl+K** / ⌘K command palette — [faq.md](faq.md) |
| Help / Trailers missing after a refresh on Systems, Chat, or Collections | Older build hid those More items on `member_bp` pages | Update the server. They follow Admin → Server Settings (`showHelpButton` / `showTrailers`) on every member page. In-app clicks from Discover could still show them while a hard refresh hid them. |
| Chat cramped on phone | Old frontend build | Admin rebuild `member-app` (Chat slide-out stacks ≤900px) |
| Huge tiles on phone | Pref L/XL before density polish | Rebuild; tiles clamp automatically under 900px |
| Some store links on details look like plain text | Logo assets not shipped yet for that store | Expected for itch · Humble · EA · Ubisoft · Xbox · PSN · Amazon · wikia/fandom · unknown — link still works; Steam/GOG/Epic/IGDB/YouTube/Wikipedia/official have marks |

### A new theme doesn't appear after reload

**Fixed.** Picking a theme saved the preference and changed nothing you could
see: the page came back with the previous theme's colours, and only a server
restart ever applied one. Re-picking, hard refreshing and clearing the cache all
made no difference, because none of them were the problem.

Every template asks for its stylesheets with a *literal* path, and Jinja
evaluates a filter applied to a literal once, at template-compile time, then
caches the compiled template for the life of the server process. The first
page rendered after a restart therefore baked its theme's URLs into every later
render. The `<html data-theme>` attribute is a variable, never folded, which is
why the page correctly *announced* the new theme while wearing the old one.

If you are on a build from before this fix, a server restart is the workaround.

### The font preference had no effect

**Fixed.** Preferences → **Font** saved your choice and the picker listed every
face, but nothing on any page ever changed — including back to the default.

The stylesheet that declares the font families, `/api/theme/fonts.css`, failed
on every request with a server error. So the `@font-face` rules were never
delivered and `--od-font-family` was never set: the browser fell through to its
own defaults no matter what was chosen. It affected everyone equally, signed in
or out, which is why it did not look preference-shaped.

There is no workaround on a build from before this fix — the fix is a server
update.

### Preferences will not open

**Fixed.** Opening Preferences threw a server error instead of showing the
room-card picker, so the panel never rendered. Jinja treated each group's
`items` list as the built-in `dict.items` method, which is not a list of
themes. The picker now walks `group['items']`.

There is no workaround on a build from before this fix — the fix is a server
update.

## The catalog is empty

The empty catalog now tells you *why* it is empty, and the three messages mean
different things:

| What it says | What it means | What to do |
|---|---|---|
| "No libraries yet" | Nothing has been added to scan | Admin → Libraries → add one |
| "Shelves are up but empty. Nothing's turned up in a scan yet." | A library exists, but no scan has finished | Run a scan (Admin → Libraries → Scan) |
| "A scan finished and matched nothing." | A scan **ran** and placed nothing — usually the scan path points above or below the game folders | Check the library's scan path; admins also get a count of folders waiting in **Unmatched** |

The third one used to read like the second, so a wrong scan path looked the
same as not having scanned yet. If you see it, the scan is working and the
paths are the thing to look at.

## Downloads

| Symptom | Likely cause | What to try |
|---|---|---|
| Download 404 | Path missing on games volume | Admin verify library path / scan |
| Empty or tiny zip | Folder empty / wrong root | Admin Library Doctor / re-scan |
| Forbidden | ACL / child role | Ask admin for library access |

## Play in browser (WebRetro)

| Symptom | Likely cause | What to try |
|---|---|---|
| Core won’t start | Unsupported system / missing BIOS | See admin emulator profiles; some systems are companion-only. Confirm required BIOS names under Admin → emulator BIOS — [browser-play.md](browser-play.md#bios--firmware-filenames-only) |
| Save missing | Cloud save flag / encrypt | Re-try; admin check emulator saves settings |
| Play fails / blank after Start (zip/7z/rar/gz) | Archive has no playable ROM, wrong member, or missing unrar/py7zr | Prefer one ROM per archive; use `.zip` with a known ROM ext; single-file `game.nes.gz` is OK — not `.tar.gz`. Check `/api/downloadrom/<uuid>` JSON (`error`, `code`, optional `hint`) |
| PS1 (or other `.cue`-based disc) never starts / stuck loading ROM | Large cue+bin download still in flight, or BIOS missing | Disc sets download as a bundled `play.zip` (cue + bin/img together) and can take a while on slower storage/network — let it finish. Confirm SCPH/region BIOS via Admin upload **or** household private BIOS mount — [browser-play.md](browser-play.md#bios--firmware-filenames-only) · [PS1 zip note](browser-play.md#ps1-and-other-disccue-downloads-are-bundled-as-a-zip) |
| No browser Play button on a scanned `.gz` | Non-ROM gzip (e.g. `.tar.gz`) | Repack as `.zip` / raw ROM; Play is suppressed for unsupported archives |
| No sound on Start | Browser autoplay policy suspends audio until a page gesture | Click once into the play screen, then press Start |
| Pause / Reset / Mute / Save do nothing | Core still booting, or a cached player shell | Wait until the game is running; hard-refresh (Ctrl+F5). Controls are on the **play bar** — the overlay cannot see hover over the iframe canvas |
| ← Game Catalog / Power does nothing | Leave-site dialog from the emulator iframe, or a cached play shell | Confirm Leave if the browser asks, then hard-refresh (Ctrl+F5). Current shells clear that guard and always go to `/library` — [browser-play.md](browser-play.md) |
| Cannot reach Start under the bottom controls | Old overlay captured the whole gradient | Hard-refresh. Only the overlay buttons take clicks; the rest of the stage stays click-through |
| Rewind button is disabled | Heavy core (N64, PS1, Saturn, Dreamcast, PSP) | Expected — a rewind buffer stutters those cores in the browser. Use save states, or the desktop companion |
| Picture looks too sharp / too CRT | Picture mode | Cycle **Picture** on the play bar: CRT · Sharp · Soft. Soft turns on RetroArch smoothing. Hard-refresh if the bar is missing the control |
| SNES game crackles / audio pitch shifts on busy scenes | WASM CPU pressure causing emulation slowdown | Pre-start gear → **Reduce Slowdown (Overclock)**; still choppy → use desktop companion for that title — [browser-play.md](browser-play.md#audiovideo-tuning--wasm-limits-snes-and-friends) |
| NES opened a chromeless Nostalgist page (no Save/Load bar) | Admin enabled `nostalgist_nes_pilot` | Expected for the NES pilot. Turn the flag off via `PUT /api/browser-player-settings` to use the WebRetro room — [browser-play.md](browser-play.md) |

## Social / voice

| Symptom | Likely cause | What to try |
|---|---|---|
| Friends pill missing | Old frontend build | Admin rebuild `member-app`; use **More → Friends** |
| Chat empty | No channels yet | Admin/librarian may need to create `#general` |
| Voice token fails | LiveKit off / misconfigured | Admin: `ENABLE_LIVEKIT` + [livekit-unraid.md](../runbooks/livekit-unraid.md) |
| Screenshare denied | Child account | Expected — camera/screenshare blocked for children |
| Looking for Discord webhooks | Not supported | Use chat / notifications / Report issue — [faq.md](faq.md) |

## Desktop companion

| Symptom | Likely cause | What to try |
|---|---|---|
| Connect fails 401/403 | Bad token / scopes / truncated paste | Account → API tokens: recreate with Desktop companion preset; paste full `gt_<prefix>_<secret>` (hyphens/`_` in the secret are normal — do not truncate after `-`). **Copy secret** copies the raw token only. On HTTP LAN, select the secret field + Ctrl+C if Copy fails. Server WARNING: `api_token_auth_failed reason=… prefix=…` |
| Download / Update greyed in companion | Offline heartbeat | Re-Connect; Play/Install/Uninstall still work — [desktop-companion.md](desktop-companion.md) |
| Friends window can’t install games | By design (least-privilege) | Use the main companion window |
| Update never appears | Local registry not merged | Re-Connect companion; see [desktop-companion.md](desktop-companion.md) |
| Leftover `.staging` folder | Interrupted update | Uninstall title in companion, or delete the staging folder |
| My headset / thin client / companion is not in the operator's device list | It has not sent a heartbeat yet, or sent one without a `device_kind` | A seat appears in **Admin → Ops → Companions → Devices** after its first heartbeat: the companion once it is connected with a token; the thin shell (`device_kind=thin`) once a token is saved; a plain browser tab never registers — it is not a device. Offline means no heartbeat in the last 3 minutes, not a broken seat. |

## Report still needed?

Use **More → Report issue** with deploy (Unraid/Compose), URL, and trimmed logs — [faq.md](faq.md).
