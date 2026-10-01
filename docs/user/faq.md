# FAQ (members)

## Navigation

**How do I jump around quickly?**  
**Ctrl+K** (⌘K on Mac) or the top-nav **Search** hint opens the command palette — pages, Preferences, Help, Admin. Type two letters to search **library titles** from any page. An empty box shows titles you recently played or opened, plus household favourites (on this server, not store trends). Navigate / More / Account stay listed.

**How do I jump to the top or bottom of a long page?**  
When the member page is scrollable, aurora glass **Jump to top** / **Jump to bottom** controls appear (bottom-left, clear of the Friends/Chat dock). They hide on short pages that don’t scroll.


## Sign-in & accounts

**I can’t log in.**  
Ask an admin to check your invite/whitelist and that the server is up (`/pulse` liveness · `/awake` ready). SSO only works if Admin → Integrations has OIDC enabled *and* `OIDC_ENABLED=true`. After several failed passwords you may see “Too many login attempts” — wait a few minutes.

**I can’t pair the desktop companion.**  
Account menu → **API tokens** (`/tokens`). Create with the **Desktop companion** preset, then **Copy secret** (raw `gt_…` only) into Connect. Format is `gt_<prefix>_<secret>` — the secret segment may include `-` / `_`; paste the **full** string (do not stop at the last `-`). Thin seats use the **Thin client** preset (no download). Browser **Copy** writes only the `gt_…` secret; on plain HTTP LAN (common on Unraid), use the Copy fallback or select the secret field and Ctrl+C / ⌘C. See [desktop-companion.md](desktop-companion.md) · [thin-client.md](thin-client.md).

**Why can’t I Install / Play in the thin client?**  
By design — thin is connect-only (browse / social / Big Picture). Use the **full** companion on the install PC. Build: `npm run tauri:build:thin` — [thin-client.md](thin-client.md).

**Child account can’t see some games.**  
Parental ACL / library allowlists filter the library. That’s intentional. Child accounts also cannot search Acquire or use companion download/install commands.

**Where is account data stored?**  
On the machine that runs Oneirodex (self-hosted). Operators: [privacy-data-handling.md](../admin/privacy-data-handling.md).

## Game Catalog & downloads

**Game Catalog looks unstyled.**  
Missing `member-app.css` — admin must rebuild the Docker image / frontend dist.

**Download stuck or empty zip.**  
Confirm the game path exists on the games mount and you’re not a child blocked from that library. See [troubleshooting.md](troubleshooting.md).

**Why is Download hidden / “Missing on disk” on a version?**  
Game details lists installs with honest presence: a version marked **Missing on disk** (`path_missing`) is not downloadable — Download is hidden for that row. The **Default** chip marks the base install. Measured **size** shows when known. Librarians/admins can **Remove missing versions** (orphan cleanup) when stale version rows linger after files moved. See [library-and-systems.md](library-and-systems.md) · [downloads.md](downloads.md).

**How many games per Game Catalog page?**  
Preferences → items per page: **20 / 50 / 100 / 200 / 250 / 300 / 400 / 500 / 1000**.

**Can I switch Game Catalog off the cover grid?**  
**Tile / Rows / Grid** in the top bar. Tile is the cover grid, Rows is a title list that scales with the slider, Grid is Steam-like genre shelves (same row chrome as Discover) — one shelf per genre in your library, each fetching its own covers and saying how many titles that genre holds, with **See all** handing the genre to Tile view. Grid has no pager: it used to shelve whichever 50 games the pager had reached, so a genre shelf changed contents every time you turned the page. The choice is remembered in this browser. Favorites uses the same switcher. The tile-size slider applies at full size to Tile, Rows, Grid, and Discover. The title strip under each cover is now a preference — **Preferences → Look & density → Show titles under tiles** — not a checkbox on the bar.

**What are Signals chips?**  
Inside Library Filters: UPDATE · MISSING · NEW · LANG — same browse params as the badges; they persist with other filters. VR is a tile badge / More → VR, not a Signals chip. MISSING means files were removed from disk. Tile badges sit in four corners only (occupied corners; rounded-square chrome). No OUT / ~ / RELEASE on tiles or Signals chips (UPDATE alone covers freshness-behind).

**When do “N games added” toasts show?**  
When a library scan **finishes** (or is cancelled after titles landed), not while it is still running. Watch/import still group into a short digest. More than five toasts at once collapse to **N notifications** (inbox still has every row). Toasts are dismissible (×) on member and admin, including classic admin pages.

**I marked a game "Won’t play" and Discover keeps suggesting it.**  
Fixed. The status was recorded but nothing read it, so the recommendations never took the hint. A title you mark **Won’t play** is now left out of the personal rows on Discover — yours only, so it does not change what anyone else in the household sees. Clearing a status is not the same as saying no: *no opinion* leaves the title in the running. You can also set it on several titles at once now from the multi-select bar, which previously offered four of the five statuses and quietly refused this one.

_One "won’t play" only removes that title — it is not read as a verdict on its whole genre, so saying no to one platformer will not empty the shelf of platformers._

**What does Surprise me on Discover pick from?**  
The top of your own taste ranking — the dozen or so titles Discover would most stand behind for you — minus anything you have already favourited, played or said no to. It is deliberately not the whole library, which would mostly land on things nobody in the house wanted. The genre chips beside it are your strongest genres; tap one to draw only from that genre. Pressing the button does not change what Discover thinks you like.

**What is a smart collection?**  
A saved filter that also shows up as a shelf on **Collections**. A normal shelf holds the games you put in it; a smart one holds whatever currently matches its filter, so it stays current on its own as titles come and go. Tick **Show on Collections** when you save a filter. It is yours — it does not appear for anyone else in the household.

**Can I filter for "this or that"?**  
Yes — the Signals chips are always *and*, but **Filters → Build a filter** gives you groups that read All of / Any of / None of, nested if you need them. Name it and it comes back as a button. A saved filter is yours alone; it does not change what anyone else in the household sees. It can only use the same signals the chips offer, so it never reaches anything the catalog does not already know.

**Where did the Game Catalog Filters column go?**  
Two-bar chrome opens Filters from a **Filters** button on the catalog bar (popover with Apply · Clear · Done). There is no sticky left-hand Filters column to collapse.

**What are Kind views?**
On the Game Catalog bar: All · Games · Soft titles · Emulators · Utilities — one view at a time. All omits `item_kind`. Persist with other library filters. Tile badges stay short (**EXP** / **TOOL**) with tooltips **Soft title** / **Utility**.

**Can I favorite, set play status, wishlist, or re-check freshness on many Game Catalog titles at once?**  
Yes via Game Catalog multi-select (checkbox / long-press / Shift+click · **Select page** for visible tiles): sticky Favorite / Unfavorite / **Add to wishlist** / **Play status** / Refresh freshness / **Refresh covers** (More; librarian+ · max 20) / Clear. Batch APIs: favorite set/clear (`POST /api/games/batch/favorite`, ≤100) · play status (`POST /api/games/batch/status`, ≤100; empty status clears) · wishlist queue (`POST /api/games/batch/wishlist`, ≤50; accounts that can request) · freshness re-probe (`POST /api/games/batch/freshness/check`, ≤50) · cover refresh (`POST /api/games/batch/refresh_images`, ≤20; 202 queued). Sticky **Refresh freshness** always re-probes the selection. Only titles you can see; partial-success toasts report updated/queued/skipped/failed. Admins still use library-wide `POST /api/admin/freshness/refresh`. No DRM download queues.

**A folder didn’t show up after a scan?**  
Librarians triage it under Admin → Scan management → Unmatched Folders (and Dupe glance). Each Unmatched row shows a **Why unmatched?** line (and a **Name transform trail** expander when Backend sends peel steps) so they can Identify as game or Mark as Soft title / Emulator / Utility. Bare folders named **UPDATE** / **Updates** stay Unmatched with an update-package why note — they are **not** auto-marked Soft title.

**Where are ES-DE / Pegasus export packs?**  
On **Systems**, in the **Export packs** note beside the page intro at the top — optional downloads of ES-DE `gamelist.xml` and Pegasus metadata for other frontends. (It used to close the page below the platform grid, which meant scrolling the whole console list to reach two links.) Admins also find them under Integrations → Export packs. Paths stay portable (no NAS mount leaks). See [library-and-systems.md](library-and-systems.md).

**What is Licensed catalog on a Systems tile?**  
It opens `/systems/catalog` for that console or computer. Counts come from an IGDB `release_dates` cache (main games only), not Wikipedia. An empty table means an admin has not refreshed that platform yet. Windows/Steam libraries are not in the report. Set completeness (DAT missing list) is a separate **Missing** link after a DAT upload.

**Trailers page is empty.**  
That’s OK (HTTP 200 + CTA) when no trailer metadata is available yet — open a title that has video, or ask an admin to enrich metadata. On **game details**, a trailer or first screenshot leads the fold when media exists — that stage is the only gallery, so there is no second screenshots or trailers section below it. Trailers play from `trailers[].embed_url` (or a YouTube demo link when there is no embed) and use the player's own fullscreen; clicking a screenshot opens it in the lightbox. Embeds do not autoplay if you asked the OS for reduced motion.

**Why doesn’t every title show system requirements or store languages?**  
Those blocks are fill-only from Steam `appdetails` when a title was identified that way. ROM-only copies keep filename language chips and do not invent a PC spec sheet.

**Where are Extras / DLC on a game?**  
Game details → **Extras & DLC**. Rows show honest **on-server** when the vault has the folder; PC libraries pick up common `DLC`/`extras` sidecars on scan — console DLC ingest is deferred. Discover may show **Extras not on the vault** for titles you already play or favourite when a catalogued extra is missing on disk. That row is an acquire hint, not a sale.

**What is a genre hub?**  
A Discover **See all** on a genre zone opens `/discover/hub/genre/…` — unplayed, newly added, and loved-here shelves for that genre. **Browse the catalog** is the full filtered list. It is not a store genre storefront. The genre chips and breadcrumb on a game's details page go straight to the filtered catalog rather than the hub, so clicking a genre there gives you every title in it. The **News** shelf’s See all opens the News page (`/news`).

**What is on a game details page besides Play and Download?**  
A breadcrumb (Catalog or Systems › genre › title), a media stage when a trailer or screenshot exists, capability chips that filter the catalog, **About** when a storyline was stored, and — only if Steam filled them — system requirements and a store-language matrix. ROM region chips stay filename truth. **More from** this developer or publisher lists other vault titles you can already see (hidden when there are fewer than two). No cart, price, or Deck Verified.

**What is Ways to Play?**  
**More → Ways to Play** (`/ways-to-play`) links Game Catalog filters for **Browser**, **Companion**, and **Catalog**, plus Systems and VR when enabled. Same honesty as the Systems badges — not Deck Verified or sale chrome. Filters also have a **Play path** select.

**What is the Mods panel, and what does Browse catalogue do?**
When mod tracking is on, a game's details page lists the mods a librarian tracks for it — name, version, the loader it needs (BepInEx, SMAPI, Fabric…), and where it came from. Librarians can add rows by hand or **Browse catalogue**: Thunderstore (BepInEx / MelonLoader games), Modrinth (Minecraft), GameBanana (Source, fighting and rhythm games, skins) and — when the admin has placed a personal key — Nexus Mods (trending and latest) are searched read-only and *Add to list* records the registry page. Nothing on the page downloads or installs a mod or a loader; the desktop companion can later stage the URLs you chose into a local install. When a registry has no entry for the game the drawer says so instead of showing an empty list. **Profiles** sit under the list: a librarian saves the currently enabled mods as a named set (*Vanilla+*, *Everything*), and **Activate** switches the whole list to that set in one click — the desktop companion's next *Apply mods* then stages exactly those. **Copy code** gives an `od-mod:…` text you can paste to another household; importing it there picks up the mods that game already tracks and names the ones it does not, so nothing gets installed behind anyone's back. If a mod's loader disagrees with the game's default loader the panel says **Loader mismatch** and the companion will not apply that set until you fix the row or the default. The catalogue drawer marks mods you already track and shows **update: vX** when the registry has a newer version — *Mark updated* records that you moved to it; a Thunderstore mod that needs other packages is added **with** them.
When mod tracking is on, a game's details page lists the mods a librarian tracks for it — name, version, the loader it needs (BepInEx, SMAPI, Fabric…), and where it came from. Librarians can add rows by hand or **Browse catalogue**: Thunderstore (BepInEx / MelonLoader games), Modrinth (Minecraft), GameBanana (Source, fighting and rhythm games, skins) and — when the admin has placed a personal key — Nexus Mods (trending and latest) are searched read-only and *Add to list* records the registry page. Nothing on the page downloads or installs a mod or a loader; the desktop companion can later stage the URLs you chose into a local install. When a registry has no entry for the game the drawer says so instead of showing an empty list. **Profiles** sit under the list: a librarian saves the currently enabled mods as a named set (*Vanilla+*, *Everything*), and **Activate** switches the whole list to that set in one click — the desktop companion's next *Apply mods* then stages exactly those. **Copy code** gives an `od-mod:…` text you can paste to another household; importing it there picks up the mods that game already tracks and names the ones it does not, so nothing gets installed behind anyone's back.
When mod tracking is on, a game's details page lists the mods a librarian tracks for it — name, version, the loader it needs (BepInEx, SMAPI, Fabric…), and where it came from. Librarians can add rows by hand or **Browse catalogue**: Thunderstore (BepInEx / MelonLoader games), Modrinth (Minecraft), GameBanana (Source, fighting and rhythm games, skins) and — when the admin has placed a personal key — Nexus Mods (trending and latest) are searched read-only and *Add to list* records the registry page. Nothing on the page downloads or installs a mod or a loader; the desktop companion can later stage the URLs you chose into a local install. When a registry has no entry for the game the drawer says so instead of showing an empty list.
When mod tracking is on, a game's details page lists the mods a librarian tracks for it — name, version, the loader it needs (BepInEx, SMAPI, Fabric…), and where it came from. Librarians can add rows by hand or **Browse catalogue**: Thunderstore (BepInEx / MelonLoader games) and Modrinth (Minecraft) are searched read-only and *Add to list* records the registry page. Nothing on the page downloads or installs a mod or a loader; the desktop companion can later stage the URLs you chose into a local install. When a registry has no entry for the game the drawer says so instead of showing an empty list.
**What does the Anti-cheat line on a details page mean?**  
A PC title the community anti-cheat list knows shows **Anti-cheat: Supported / Running / Planned / Broken / Denied**, the anti-cheat's name, and a link to the report page. It is community reports, not a guarantee — *Denied* means the publisher has said no to Linux / Proton seats, and that a kernel anti-cheat title is one where mods, cheats or an injector risk a ban. Nothing on the page changes what Play or Download do. Titles the list does not know show no line; an admin can turn the whole row off with `ENABLE_ANTICHEAT_COMPAT=false`.

**What are the Assists links in the Friends window?**
When the desktop companion launches a game and you open **Friends**, the window lists that game's assists: an interactive map, a guide, clips, and the PCGamingWiki page (PC titles get the wiki link even when nobody wrote a pack). They are **links**, opened in your browser — Oneirodex never reads the running game, never injects anything, and never changes a save or a file. A librarian curates the list per game; the policy stays single-player, offline-only.
**Where are my saves for this PC game?**
A PC title the community save-location manifest knows shows a **Save location** row on its details page — one templated path per OS (`<winAppData>/Studio/Game/Saves`), the same for every household PC. When the desktop companion is online, **Open save folder** asks it to expand the placeholders for *its* machine and reveal the folder; if a placeholder cannot be filled there (a store user id, an install that is not on that PC) it says so instead of guessing. It is the folder, not a backup: nothing is synced or copied.

**Open path does nothing / doesn’t open Auto Scan.**  
Open path uses **OpenPathModal** → companion `open_path` (or clipboard fallback). It never jumps to Auto Scan. Pair the desktop companion Online and send a path your PC can see — [desktop-companion.md](desktop-companion.md).

## Browser play

**Where are pause, reset, mute, save, and rewind in the browser player?**  
On the play bar above the screen: Pause, Reset, Mute, volume, Save, Load, Rewind, FF, Picture, and Power. Power leaves the game, same as **← Game Catalog**. **?** opens the shortcut list (F2/F3 save/load, hold Right Shift to rewind, F5 fast-forward). An overlay repeats the in-game controls on touch, or when you move the pointer over the play stage. See [browser-play.md](browser-play.md).

**Which systems play in the browser?**  
NES, SNES, N64, Game Boy family, DS, Virtual Boy, PS1, the Genesis family including SG-1000, Saturn, the Atari line, Lynx, Jaguar, WonderSwan, Neo Geo Pocket / Color, Coleco, Vectrex, 3DO, Neo Geo CD, Intellivision, Channel F, and Odyssey 2. Switch, Wii, GameCube, Xbox, and arcade boards stay companion or catalog. Cartridge NES / SNES / N64 / Genesis do **not** wait on optional add-on firmware (FDS `disksys`, DSP chips, 64DD IPL, Sega CD BIOS). Play greys only when that system cannot boot without a file — PS1, Sega CD, Saturn, and the other hard rows in Admin → Emulators. Oneirodex never fetches BIOS. Full matrix: [browser-play.md](browser-play.md). An optional NES Nostalgist host (admin flag, off by default) does not have the play bar yet.

## Themes & icons

**Theme vs icon pack?**  
- Color theme = **decade room or colour cabinet** (wallpaper, window, posters, floor — same setting language as browser play — plus palette/chrome). Icon pack = glyph style (outline, filled, …) — still overridable. Independent after save — [preferences-themes.md](preferences-themes.md). Preferences is sectioned (Library · Look & density · Game language) and uses a **grouped room-card picker** (Decade rooms · Colour cabinets · Installed uploads), not a tiny swatch grid. **Preferences is the only place a theme is chosen** — admins included; the separate admin picker was retired in favour of one surface that cannot disagree with itself.

**Loading spinners look wrong / stuck on ring?**  
Household mode is Admin → Themes → **Loading icons** (rotate catalogue or lock one). Motif CSS needs **Reset Default Themes** after Wave 2d deploy — [themes-reset.md](../admin/themes-reset.md).

**Why do some games show a Oneirodex placeholder cover?**  
Titles without downloaded artwork get a branded placeholder painted in your **active decade room** (wood planks, posters, carpet, marquee, phosphor — cached per theme). The generic `default_cover.jpg` is only the last fallback if rendering fails. Admins can generate decade-room / platform / stock packs in **Admin → Settings → Art studio** and attach them to games or set a site-wide fallback pack.

**Do I need an admin to install fonts?**  
No. Every face the Font picker lists ships with Oneirodex and is copied into place on each server start — no download, no admin step, works air-gapped. "Not installed" now means a real filesystem problem on the server, not the normal state. What is *not* bundled is console manufacturers' own typefaces; those are trademarked, so the bundled faces evoke each era instead — [preferences-themes.md](preferences-themes.md).

**I picked a theme and nothing changed after reload.**  
Fixed. On a build from before that fix, the whole install served whichever theme was current when its templates were first rendered, so only a server restart ever applied a change — re-picking and hard refreshing did nothing because neither was the problem. See [troubleshooting](troubleshooting.md#a-new-theme-doesnt-appear-after-reload).

**Preferences will not open / the page errors.**  
Fixed. The grouped room-card picker crashed while rendering because Jinja treated each group's `items` as `dict.items`. See [troubleshooting](troubleshooting.md#preferences-will-not-open).

**Theme/prefs look wrong after deploy?**  
Ask an admin for **Reset Default Themes** if `od-account.css` / `modal-components` lag on the library volume — [themes-reset.md](../admin/themes-reset.md).

## Social & voice

**Where are friends?**  
Use the **Friends** pill (bottom-right), **More → Friends**, or Big Picture **Y**. Pop out / desktop “Open friends window” parks `/social-companion` on another monitor — [social-and-voice.md](social-and-voice.md).

**Where is chat?**  
**Chat** pill (bottom-left), **More → Chat**, or Ctrl/Cmd+K → Chat opens a **left slide-out** (rooms · messages · composer) — TopNav stays. `/chat` deep-links open the same panel then return you to Library. Dismiss with × / scrim / Esc; reopen anytime. Use **Add** to create a room (child accounts cannot). Thread header **Archive** (household rooms, creator/librarian+) and **Leave** (DM drop / household mute — room list shows a **muted** badge after leave). Optional BYO Stoat/Matrix if the admin set Community chat.

**What are Spaces?**  
The rail beside chat. **Household** is everyone on the box; **invite-only** spaces stay invisible until you redeem a code. Each space has its own text and voice channels. See [social-and-voice.md](social-and-voice.md).

**Voice doesn’t appear.**  
LiveKit is optional. If off, Activity shows “LiveKit is off.” Admins enable `ENABLE_LIVEKIT` + compose profile — [social-and-voice.md](social-and-voice.md).

**Play via Moonlight on game details?**  
Optional. When the admin enables remote play and registers a BYO Sunshine or Wolf host, game details show **Play via Moonlight** — it copies the host and app/PIN hints for your Moonlight client. Oneirodex does not stream in the browser.

**Can I use Discord webhooks?**  
No. Oneirodex does not integrate Discord (bots or webhooks). Use in-app notifications, chat, optional email for mentions/DMs, or optional LiveKit / BYO community link.

**Does Oneirodex ship peer “we’re not Product X” catalogs?**  
No — public docs use Oneirodex capability language only. Competitive intel stays in the private vault (`docs/_private/`, gitignored).

## Updates & calendar

**Where are library updates?**  
**More → Updates** — freshness inbox (auto-refresh while the tab is visible), store search / apply packs, plus a short **Upcoming releases** teaser that links to the calendar. The refresh control and the "Updated HH:MM" timestamp sit together on the **Library freshness inbox** heading row, time first.

**The Updates inbox is empty — how do I make it check my library?**  
Press **Check library for updates** beside Refresh. The two do different things:

- **Refresh** re-reads what the *last* probe found. If nothing has ever been probed, refreshing forever will keep showing nothing.
- **Check library for updates** makes a new probe happen — `POST /api/updates/scan`, oldest-checked titles first, skipping anything probed in the last 24 hours.

Each press does one bounded batch (25 titles, 50 max) because every title is a live request to Steam / GOG — an unbounded sweep would hang for minutes and get you rate-limited. The line under the heading reports what it found and **how many titles are still to check**, so pressing again picks up where it left off. Librarians and admins still have the library-wide `POST /api/admin/freshness/refresh`.

**Where is the release calendar?**  
**More → Calendar** — IGDB releases (metadata only) with Ahead/Behind window controls and a **List / Month** view switcher (choice remembered in the browser). Month shows each day's **cover art**; when more than one title lands on a day the tile cycles through them every ten seconds and a `+N` badge says how many more there are. Click a day for the full list beneath the grid. Oneirodex does not download those titles.

> The old **Agenda** view is gone. It was the List view with week headings between the rows — the same titles in the same order — so it was a third tab that never showed anything List did not. A browser still holding `agenda` as its remembered choice falls back to List.

## News & notifications

**Where is News?**  
**More → News** — tabbed feed (All · Admins · Free now · Headlines) that fills the pane. **Card / Grid / RSS** in the top bar changes how Free now and Headlines look: Card and Grid overlay source and date on the artwork with the title under the image; RSS is magazine rows. Empty tabs return an honest empty state (HTTP 200), not an error.

**Where do free Steam/Epic/GOG offers show up?**  
**News → Free now.** Claim opens the store page (or launcher if that account is linked under Ownership). Details: [free-games.md](free-games.md).

**Will Oneirodex add the game to my DRM library automatically?**  
No — claim on the store, then sync Ownership for badges. Steam / GOG / Epic / Amazon live-sync the register when a token is saved; they still never download the game. Local DRM-free library folders are separate.

**How do I keep GOG, Epic, or Amazon ownership current?**  
**More → Ownership.** Save a GOG refresh token, Epic device-auth JSON (Heroic / Legendary), or Amazon Nile/Heroic token JSON, then **Sync**. Same idea as Steam Web API. Tokens stay on your server; they are not shown again after save. CSV import still works if you do not want live sync.

**Can I see what I own on Xbox or PlayStation?**
Yes, as a register only. **More → Ownership** has Xbox and PlayStation Network cards: import a CSV of title ids (or id,name) any time. Live sync from the accounts themselves uses *unofficial* community clients and is **off unless your server operator opts in** (`ENABLE_UNOFFICIAL_STORE_SYNC`) and installs the optional package — the Sync button tells you which part is missing. When it runs it records ids and names, nothing else: Oneirodex never downloads a console title, and a rejected token just asks for a fresh one. Nintendo remains CSV-only.

**Where are Notifications?**  
**More → Notifications** — dense unread inbox; alert prefs live under **Alert preferences**. Empty inbox is honest (HTTP 200). **Mark all read** sits on the **INBOX** heading row, aligned with the label and directly above the list it clears — not in the top bar, which holds page-level controls.

## Reporting bugs

**How do I report an issue?**  
**More → Report issue**. Title required; symptom and logs optional. Start with title, area, and severity. **Context** (deploy / client / URL) and **Logs** stay collapsed until you expand them. Tickets go to admins and sync to GitHub Issues when configured — confirmation shows a ticket id (and GitHub link if synced).

**Where is Help?**  
**More → Help** — a grid of topic cards with one reading pane underneath. The page opens on **Getting started**; picking any card swaps the pane. Deep links like `/help#translations` still land on that topic.

Each card carries a colour and a glyph drawn from the theme's own semantic set (accent · info · success · warning · danger), so a topic can be found at a glance instead of by re-reading thirteen identical headings — and a theme or icon pack restyles them along with the rest of the product.

The bar carries **one** control: **Expand all** puts every topic in the pane in order, to read straight through, and the same button then reads **Collapse all** to go back to one at a time. The five group chips and the "N of 13 open" read-out are gone — the card grid is the index now, and with one pane open the count was always 1.

> Before this the page was thirteen full-width accordions: every topic cost a screen of scroll whether or not you wanted it, and opening one pushed the rest below the fold.

## Big Picture

Gamepad-friendly browse at **More → Big Picture**. Esc exits; Attract opens trailers. Full button map (Xbox + DualSense): [controllers-and-vr.md](controllers-and-vr.md).

## VR / headsets

`/vr` is headset-friendly browse (admin flag), **not Quest-only** — PSVR2/SteamVR use a desktop browser on the PC; Quest friends use the headset browser/PWA. Thin / headset seats have **no** install pipeline. See [controllers-and-vr.md](controllers-and-vr.md).

**Which VR runtime, adapter or streamer do I need — and does Oneirodex install any of it?**
None of it: Oneirodex records how a title plays and links to where the community keeps its profile; the runtime (SteamVR, Monado / WiVRn, a vendor link app), the OpenVR adapter (OpenComposite) and the streamer (Virtual Desktop, Steam Link, ALVR, WiVRn) are yours to install from their own projects. [runbooks/vr-byo-runtime.md](../runbooks/vr-byo-runtime.md) is the matrix: pick the runtime by OS and headset, add an adapter only when a title needs it, a streamer only for a standalone headset — and, for a Quest-class headset, the **wired USB network link** that measured 0.7 ms / ~756 Mbps against any Wi-Fi in the house.

**Where do I see which devices are connected?**  
Admin → Ops → **Companions** shows the count by kind and, under it, the device list: every companion, thin seat or browser shell that has sent a heartbeat, with its owner, version and last-seen time. *Online* means a heartbeat in the last 3 minutes.

## Licence

**What licence is Oneirodex?**  
GNU AGPL v3. Help → About has the licence link. If you run a *modified* copy as a network service, AGPL §13 means you owe your users that modified source — admins set `ONEIRODEX_SOURCE_URL` to their fork so the Help/About source link is honest.

## Installing

**Can I install Oneirodex as an app?**  
Yes, on anything with a modern browser: **Preferences → Install this library**. It opens in its own window with its own icon and starts on your shelf. On iPad and iPhone use Share → **Add to Home Screen**; in a headset browser use its *Add to Home screen*. A thin seat that wants to appear in the operator's device list as a thin client uses the shell instead — [thin-client.md](thin-client.md).

**Why is there no Install row?**  
It needs **HTTPS**. Browsers only allow the install path on a secure origin, so a plain-HTTP LAN address will not offer it. The row is also hidden once the app is installed, or if you pressed *Not now*.

**Does an installed copy work offline?**  
No, and it does not pretend to. It keeps the app's own code and theme files on the device — never games, cover art or anything from the API, because an installed app outlives a sign-out on a shared machine. With no network it shows a "no route to your library" page rather than a stale shelf, and reconnects on its own.
