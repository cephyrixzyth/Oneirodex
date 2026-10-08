# Themes & reset

> **Doc status:** Active

Themes live on the **library volume** (`/app/oneirodex/static/library/themes/...`), not only in the image. Source of truth for defaults: `oneirodex/setup/default_theme/`. Preset generation uses **`GENERATOR_VERSION` 41** in `oneirodex/utils/preset_themes.py` (41 = metadata-providers handler learns the hash-identify switch; 40 = six system-family presets; 39 = `.od-seg` wraps on narrow screens; 38 = per-console loading-motif colour; 37 = drawn room art per era; 36 = Library tools THN). **Reset Default Themes** after this bump — volume copies stay on the previous generator until you do.

## Uploading a theme

Theme ZIP uploads are limited to 25 MiB compressed, 100 MiB total expanded content, and 1,024 archive entries. Unsafe archive paths and special files are rejected before extraction. Each upload uses its own temporary directory; concurrent uploads cannot mix files. If two uploads use the same theme name, one is accepted and the other is refused without replacing the installed theme.

## Default look

- Accent **`#2fd67b`** (green glass Style B+C).
- Glass tokens: `--od-glass-bg`, `--od-glass-border`, `--od-glass-blur`.
- Admin → Themes uses the shared `od-adminpage` width and panel spacing (upload · reset · **installed themes as a list** · loading icons) — no separate “Back to Dashboard” stack; use the React top bar. Choosing a theme happens in Preferences, not here — see [Apply a theme](#apply-a-theme).
- Member SPA also needs built **`member-app.css`** in dist — theme reset does not replace a missing SPA bundle.

## Rooms have drawn art (generator 37)

Each era now ships an authored SVG scene — `art/era/<era>.svg` — that the room
paints behind the product: a window and shelves in the 80s den, posters and a
portable set in the 90s bedroom, an AV rack in the 2000s media centre, a cabinet
row in the arcade, a monitor and tower at the desk. The gradients stay as the
*light*; the art is the *furniture*.

The room keeps its own era palette; only one sentinel colour follows the theme
accent (the screen glow, a standby LED), recoloured per preset exactly like the
stock avatars. Art direction and the contract for adding or generating a
backdrop: [dev/theme-art-direction.md](../dev/theme-art-direction.md).

**This needs a Reset Default Themes** — the art lives on the volume beside the
CSS, and a preset generated before 37 has no `art/` folder at all (it falls back
to the old flat room rather than breaking).

## When to Reset Default Themes

After any deploy that changes tokens, admin CSS, or preset fingerprints:

1. Free Unraid host disk if ~99% full — [unraid-deploy.md § Deploy gates](../runbooks/unraid-deploy.md#deploy-gates-operator-checklist)
2. `docker compose build --no-cache && docker compose up -d` (image must rebuild **`frontend/member-app` dist**)
3. **Reset Default Themes** — Admin → Themes, or (admin) Preferences → Look & density
4. Reload normally; confirm accent green, admin pages styled, and View Source includes **`member-app.css` / `member-app.js`**

> **A reset is visible immediately as of 2026-08-16 — a hard refresh is no longer part of the
> procedure.** It used to be, and the reason was a caching bug rather than anything about themes:
> every static file was served `public, max-age=3600` with **no validator**, while Reset Themes
> rewrites `themes/<theme>/…` in place behind an identical URL. Nothing about the request changed, so
> the browser answered from cache for up to an hour and a completed reset looked like it had failed.
> `theme_asset` now versions each URL by the file's mtime and size, and `/static/library/themes/` is
> served `no-cache` so even an unversioned reference revalidates. **If you are following older notes
> that say "hard-refresh or it won't take", that step is obsolete** — if a reset still looks
> unapplied, the cause is now genuinely elsewhere (most often a missing SPA rebuild, below).

Or delete `themes/default` (and stale presets) under the library volume and restart so boot sync can reinstall.

**Post-deploy pair (always both):** Reset Themes (volume CSS/JS) **and** a rebuild that includes member-app dist (SPA bundle). Skipping either leaves a half-applied Unraid pull.

**Two different things after an Unraid `git pull` + rebuild:**

| Asset | Where it lives | How it updates |
|---|---|---|
| Admin / library color theme CSS (`gt-*` tokens, swatch grid) | `oneirodex/setup/default_theme/` → copied onto the **library volume** on boot | Needs **Reset Default Themes** (or delete `themes/default` + restart) — a plain rebuild alone does not overwrite already-installed volume copies |
| Scan management CSS/JS (`admin_manage_scanjobs.css` / `.js` + **W22-1** `admin_manage_libs.css` / `.js` — Libraries tab merge, multi-select sticky **Scan**/**Edit** → batch APIs, force-delete, unmatched Open path, table scale, **UID-005** per-entry top actions bar + Resolve equal-pill bar + sortable columns, **UID-016** Dupe glance + Unmatched side-by-side Compare (This folder \| Library game · path/size/date) + **2026-08-26 Pop out** dialog, **Library tools tab**, **Scan Filters** how-it-works / quick-add / `dir:` kind UI, Wave 17 **Search name**/batch/Dupe-of, **Wave 18** scan job elapsed/ETA/stalled + status/library/path filters, **W20-2** Name transform trail `<details>`, **Layout** chips / `od-toast-host`, **UI-W22-M7** Soft title / Utility kind labels on Unmatched / Dupe glance / mark-kind) | Same theme tree → **library volume** copies | Needs rebuild **and** **Reset Default Themes** (or hard-refresh alone is not enough if volume copies are stale) — without Reset, unmatched tab can look cramped / miss Open path chrome / miss Pop out / miss Library tools tab JS / miss top actions bar · Resolve pill bar · column sort / miss UID-016 side-by-side Compare / miss Scan Filters explain UI / miss Wave 18 timing+filter chrome / miss W20-2 transform trail expander / miss W22 Libraries tab + sticky Scan/Edit batch wire + force-delete / miss Soft title·Utility kind copy (still show “experience”/opaque labels) |
| Auth / account / identify / Edit Images aurora (`od-setup` · `od-account` · prefs modal · identify `od-adminpage` · **Wave 19** `game_edit_images` aurora + chip underline/scale · **2026-08-25** uploaded-image DOM builders, no `innerHTML` URL interpolation) | Theme tree CSS/templates/JS → **library volume** copies | Needs rebuild **and** **Reset Default Themes** after aurora / Edit Images deploy — without Reset, login/account/identify/Edit Images can still show pre-aurora chrome **and the XSS-safe image insert will not be live** |
| P1 densified-admin Jinja (`od-adminpage` logs/status/whitelist/library-create/SMTP/integrations/users/… · `admin-pages.css` `od-meter` · `admin-components.css` 1600px settings) | Theme tree CSS/templates → **library volume** copies | After P1 densify deploy: **Reset Default Themes** so `library/themes` picks up widened settings shells and aurora meters — otherwise operators still see the 1100px / hybrid glass chrome |
| Member SPA bundle (`member-app.css` / `.js` — FilterBar `od-btn*` · **UID-009** `ScrollJump` · locale dates, CSS toasts, Acquire indexer labels · **UID-001** BadgeStack / GameCard layout JS) | Built into the **image/dist**, not the theme volume | Needs image rebuild that includes a fresh `frontend/member-app` dist — **Reset Themes alone does not refresh SPA JS/CSS** |
| Admin SPA bundle (`admin-app.css` / `.js` — Settings hub grouped rows · On/Off pills · Server Settings nested-card flatten) | Built into the **image/dist**, not the theme volume | Needs image rebuild that includes a fresh `frontend/admin-app` dist — **Reset Themes alone does not restyle `/admin/settings`** |
| Member chrome theme mirror (**UID-009** `od-chrome.css` — ScrollJump glass top/bottom controls) | Theme tree CSS → **library volume** copies | Needs rebuild **and** **Reset Default Themes** after ScrollJump / chrome deploy — without Reset, jump controls can miss aurora glass tokens from stale volume CSS |
| Library tile badge chrome (**UID-001** — rounded-square `.od-badge` / stacks / platform chip / hamburger · favorite · status in `css/components.css` + Signals filter chips in `games/library_filters.css`) | Theme tree → **library volume** copies | Needs rebuild **and** **Reset Default Themes** — without Reset, tiles can keep old pill/circle badge chrome or empty reserved corner slots from stale volume CSS |
| Admin SPA SoT re-exports (`stageECandidates.js` / `unmatchedTriage.js` / `scanJobsDom.js` used by Dupe glance / unmatched triage / Libraries & scans poll) | Theme tree JS is SoT; `Dockerfile` `frontend-build` **COPY**s those files into `/build/oneirodex/...` before admin-app `npm run build` | Image rebuild picks up admin bundle + theme JS together — still **Reset Themes** for Jinja scanjobs volume copies of the same files |
| Browser Play room skins (`play-skins.css` / `play-skins.js` / `webretro.html`, atmosphere stack · bezel mat · aspect-lock vars) | `oneirodex/static/vendor/webretro/` — served **directly from the image**, not copied to the library volume | Picks up on a normal `docker compose build --no-cache && docker compose up -d` — **no** Reset Default Themes needed, but the browser tab needs a hard-refresh (Ctrl+F5) to drop cached CSS/JS |
| Modal stacking helper (`js/od_modal_stack.js`) + `modal-components.css` | Copied onto the **library volume** with the theme tree | Needs rebuild **and** Reset Default Themes (or rely on **inline** stacking CSS in `base_admin.html` / Libraries / Integrations, which works after rebuild alone) |
| Local vendor CDN scrub (`static/vendor/bootstrap/5.3.2/` + jquery/datatables/notify/cropper/sortable/chart under `/static/vendor/...`) on `base_admin` · member `base.html` · `base_empty.html` (login extends `base`) | Served from the **image/static**, not the theme volume | Picks up on rebuild/restart — **no** Reset Themes for vendor libs; still Reset Themes for theme-volume CSS/JS (e.g. `admin_manage_libs.js` typed-confirm delete modal) |
| Account / prefs chrome (`od-account.css` · prefs modal · `modal-components`) | Theme tree → **library volume** | After Wave 2c densify: if account/prefs chrome still looks pre-sectioned or modal stacking lags, run **Reset Default Themes** (volume copies stale) — same gate as aurora scrub row above |
| Wave 2d presets + loading motifs (`GENERATOR_VERSION` **10** at the time · paired `default_icon_pack` · `od-loading-motifs.css` / `od_loading_motifs.js`) | Theme tree tokens/CSS/JS → **library volume** | After Wave 2d ship: rebuild **and** **Reset Default Themes** — without Reset, presets stay accent-only (v9) and Auto Scan misses motif CSS |
| Geometry packs (`GENERATOR_VERSION` **16** — UID-006 radius / space / type / shadow per preset) | Theme tree tokens → **library volume** | After 2026-08-26: rebuild **and** **Reset Default Themes** — without Reset, presets keep v10 geometry (hue + pairing only) |
| Decade rooms (`GENERATOR_VERSION` **17** — `od-era.css`, six era presets, colour cabinets sit in a play-room, themed placeholder covers). Atmosphere is `z-index: -1`; rail/topbar stack at 2, main at 1 (flattened `#admin-app-root` cannot). | Theme tree CSS/JS/tokens → **library volume** | After 2026-08-26: rebuild **and** **Reset Default Themes** — without Reset, member/admin chrome stays a flat colour slab and the Preferences picker is still the tiny swatch grid. After 2026-08-28: restart so `od-era.css` stacking copies; Reset if a preset still hides admin chrome |
| Libraries & scans hang + flatten (`GENERATOR_VERSION` **18** — `admin_manage_scanjobs.js` / `.css`: skip overlapping/hidden-tab polls; drop nested glass on jobs/unmatched; unwrap Libraries `.card`) | Theme tree CSS/JS → **library volume** | After 2026-08-30: rebuild **and** **Reset Default Themes** — without Reset, Scan management still polls drain-on-every-tick from stale JS and still shows cards-in-cards. Admin SPA poll coalesce ships in the image, not the theme volume. |
| Discover top-bar fade (`GENERATOR_VERSION` **19** — `od-shell.css` / `od-era.css`: bar opacity transition on tile hover instead of a z-index pop) | Theme tree CSS → **library volume** | After 2026-08-30 Discover pickup: rebuild **and** **Reset Default Themes**. Member shelf JS/CSS still needs a **member-app dist** rebuild — Reset Themes does not refresh that. |
| Libraries & scans in-place poll (`GENERATOR_VERSION` **21** — `admin_manage_scanjobs.js` + `scanJobsDom.js`: patch job progress instead of wiping the table; unmatched rebuild only on that pane. `od-shell.css`: account dropdown panel is a vertical menu on admin too) | Theme tree JS/CSS → **library volume** | After 2026-08-31 hang + account-menu pickup: rebuild **and** **Reset Default Themes**. Admin SPA `AdminTopNav.css` also needs the **admin-app** image rebuild. |
| Catalog / Discover tile hover (`GENERATOR_VERSION` **22** — `components.css` + `od-shell.css`: outline only while enlarged, tight to the cover; library L/R overlap via clip-margin, not inward origin) | Theme tree CSS → **library volume** | After 2026-08-31 tile-outline pickup: rebuild **and** **Reset Default Themes**. Member SPA `GameGrid.css` / `glass.css` / `NewsCard.css` still need a **member-app dist** rebuild. |
| Libraries & scans page-shell flatten + Libraries DataTable (`GENERATOR_VERSION` **23** — shell/tab-content flatten; admin SPA Libraries panel + Libraries/Scan unfurls) | Theme tree CSS/JS/templates → **library volume**; admin-app dist in **image** | After 2026-08-31: rebuild **and** **Reset Default Themes**. |
| Member selection top bar (`od-shell.css` — keep bar visible while `.is-selecting`; larger hover clip-margin; tighter top-bar start padding) | Theme tree CSS → **library volume**; selection bar logic in **member-app** dist | After 2026-08-31 pickup: rebuild **and** **Reset Default Themes**. |
| Thin top-bar no fade (`GENERATOR_VERSION` **24** — `od-shell.css` / `od-era.css`: bar stays opaque; hover lifts the scroll pane so tiles overlap it) | Theme tree CSS → **library volume** | Rebuild **and** **Reset Default Themes**. |
| Admin trail Reset layout (`GENERATOR_VERSION` **25** — `od-appbar.css`: no rest border on `.od-topbar__trail > .od-cbtn-group > .od-cbtn`) | Theme tree CSS → **library volume**; Dashboard drag/resize pitch is **admin-app** dist | Rebuild **and** **Reset Default Themes**. |
| Token pass on classic CSS (`od-tokens.css` family marks, scan jobs / game details / base / account / setup, plus earlier form-components / sidebar / table-components) | Theme tree CSS → **library volume** | After UID-017: **Reset Default Themes** so volume copies pick up `var(--od-radius-*)` / `var(--od-font-*)` / `--od-family-*`. Member SPA pages ship in **`member-app` dist** — rebuild the image; Reset Themes does not refresh those |

| Libraries & scans LHN/THN (`GENERATOR_VERSION` **32** — `od-shell.css` hub sub active matches member; Scan THN Auto\|Manual only; no Libraries sibling strip) | Theme tree CSS/templates → **library volume**; admin-app dist in **image** | After 2026-09-12 chrome pickup: rebuild **and** **Reset Default Themes**. |
| Auto Scan refresh control (`GENERATOR_VERSION` **33** — icon + `od-tip` in Auto Scan header; drops the “Refresh all libraries” banner row) | Theme tree CSS/templates → **library volume** | After 2026-09-12: rebuild **and** **Reset Default Themes**. |
| Library tools THN (`GENERATOR_VERSION` **34** — tool views in contextbar; Add many folds scan+import; no page title / pane outline) | Theme tree CSS/templates → **library volume** | After 2026-09-12: rebuild **and** **Reset Default Themes**. |
| Drawn room art per era (`GENERATOR_VERSION` **37** — `art/era/<era>.svg` painted by `.od-era-scene`; one sentinel colour follows the accent) | Theme tree CSS/art → **library volume** | Rebuild **and** Reset Default Themes. |
| Per-console loading-motif colour (`GENERATOR_VERSION` **38** — `.od-loading-motif` reads `--od-platform-accent`, falls back to the theme accent) | Theme tree CSS → **library volume** | Rebuild **and** Reset Default Themes. |
| Segmented strips wrap (`GENERATOR_VERSION` **39** — `.od-seg` gets `flex-wrap`; a six-item strip no longer pushes Admin → Integrations sideways on a phone) | Theme tree CSS → **library volume** | Rebuild **and** Reset Default Themes. |
| Hash-identify switch (`GENERATOR_VERSION` **41** — `admin_metadata_providers.js` on the volume reads a fourth checkbox, `mp_hash_identify`) | Theme tree JS → **library volume** | Rebuild **and** Reset Default Themes — without Reset the Integrations form shows the checkbox but the old handler never saves it. |
| System-family presets (`GENERATOR_VERSION` **40** — six `group: 'console'` packs in `preset_themes_catalog.py`, their picker swatches in `form-components.css`; the fifteen existing presets are byte-identical) | Preset folders + theme tree CSS → **library volume** | Rebuild **and** Reset Default Themes — without Reset the six new folders do not exist on the volume and the picker offers themes that 404. |

If a fresh Unraid pull looks half-applied (new play-skins room art shows but admin still looks old, or vice versa), check which of the two you skipped.

## Apply a theme

**Preferences is the only theme picker.** Everyone — admins included — chooses a theme in
**Preferences**, which sets colour theme, icon pack, font and tile size together. The picker
is grouped **Decade rooms** / **Colour cabinets** / **Installed** with a miniature of the
era room on each card, so fifteen-plus presets stay scannable.

> **Changed 2026-08-16.** The Admin → Themes page used to carry its own swatch grid writing the same
> `current_user.preferences.theme` that Preferences writes, so the two surfaces could disagree about
> what was selected with nothing to say which had won. The grid, its fetch and **`POST /admin/themes/apply`**
> are retired at every layer; a script or bookmark calling that endpoint will 404. Preferences builds
> its list from `get_installed_themes()`, so it already covers uploaded packs as well as presets.

Admin → Themes keeps the operator-only actions: **upload**, **Reset Default Themes**, **delete**, and
the Loading-icons controls below. It links to Preferences for the actual choice. Admins can also run
**Reset Default Themes** from Preferences → Look & density (same `POST /admin/themes/reset`).

Icon-pack fallback is unchanged: when a theme is selected and no pack is named, the theme's
`theme.json` `default_icon_pack` applies when present; otherwise the existing preference pack stands
(new rows still default to `outline`).

Never edit `oneirodex/static/library/themes/` in git — it is runtime output. Change `oneirodex/setup/default_theme/` and bump generator version when output format changes.

## Icon packs (separate from color themes)

Icon / image packs live under `static/library/icon-themes/{id}/` and are installed from `oneirodex/setup/icon_themes/` on boot. They restyle `.od-icon` via `html[data-icon-pack]` and work with **any** color theme.

- **Reset Default Themes does not wipe icon packs.**
- Members pick a pack in Preferences → Icon pack (same modal as color swatches).
- Details: [preferences-themes.md](../user/preferences-themes.md)

## Loading icons (admin)

Household spinner mode is **DB settings**, not theme volume files — Reset Themes does not change it. Motif CSS/JS **do** live on the theme volume (`od-loading-motifs.css` / `od_loading_motifs.js`) — Reset after Wave 2d so Auto Scan picks them up.

- Admin UI: **Admin → Themes → Loading icons** (rotate catalogue vs lock to one).
- Admin API: `PUT /api/admin/loading-icon/config` (`loading_icon_mode` = `rotate` \| `lock`, optional `loading_icon_id`).
- Public bootstrap: `GET /api/loading-icon`.
- Details: [settings-modules.md](settings-modules.md#loading-icons-admin-lock--rotate).

Related: [preferences-themes.md](../user/preferences-themes.md) · [ui-wave0-tokens.md](../dev/ui-wave0-tokens.md) · [unraid-deploy.md](../runbooks/unraid-deploy.md#deploy-gates-operator-checklist)
