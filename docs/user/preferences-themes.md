# Preferences & themes

> **Doc status:** Active

> 🎬 Watch (narrated): [themes, rooms, icons & fonts](../media/video/howto/howto-preferences.mp4) — [all how-to videos, with transcripts](../media/video/howto/README.md)

## Open preferences

From the member SPA **Account** drawer (under TopNav) → **Preferences**, or Ctrl/Cmd+K → Preferences. The modal uses sectioned aurora chrome (`od-prefs-modal`: Library · Look & density · Game language) — dense sections, **no heavy cards**. Changes save to your user profile and usually reload the page.

Preferences is three folding sections — **Library**, **Look & density** and **Game
language**. Fold the ones you are not using and it stays folded next time; the panel
opens fully expanded until you change that.

## Color theme presets

- Pick a preset from the **room-card picker** in Preferences — the six current designs are Mosslight, Afterglow Arcade, Graphite Studio, Signal Room, Tape Deck, and Deep Space Media. Uploaded packs appear under **Installed**. The underlying `<select>` is visually hidden. Preferences is the only theme picker. Admins also get **Reset Default Themes** under Look & density (same action as Admin → Themes) after a deploy that changes theme CSS.
- A theme is a **room**, not a solid colour. Member and admin chrome share atmosphere with browser-play rooms (`html[data-era]`), while each design has its own palette, geometry, icon pack, and material feel.
- **Default (system)** is the built-in theme id `default` (saved explicitly — not `None`). It keeps the green accent and wood-den scenery.
- The six new designs vary accent, surfaces, glass/CRT, typography, spacing, geometry and icon style. Ask an admin to **Reset Default Themes** after a deploy so the library volume receives the current designs. Old shipped presets are retired; uploaded themes are kept and old saved selections map to a replacement.
- Picking a room card also selects that preset’s paired icon pack (still changeable before Save). The live preview repaints the accent **and** switches the room scenery before you save.
- The chosen theme applies on the **next page load** — every stylesheet, the brand mark, the tile chrome, the **stock avatars**, and **backup/placeholder covers** follow it. Untitled games get a Pillow placeholder painted in the active decade room (cached per theme). The seven avatars Oneirodex ships are recoloured into each preset's palette. An avatar you uploaded yourself is your picture and is never recoloured.
- If cards do nothing, accents look wrong, rooms stay flat, or presets still look accent-only, the library volume may have stale theme files — ask an admin to **Reset Default Themes** after a rebuild.

> **Fixed:** themes used to appear not to save at all — the page came back with
> the previous theme's colours however many times you picked a new one. The
> preference was saving correctly; the stylesheet links were being cached per
> server process, so a restart was the only thing that ever changed them. See
> [troubleshooting](troubleshooting.md#a-new-theme-doesnt-appear-after-reload).

## Icon packs (independent of color)

- Preferences → **Icon pack**: Outline, Filled, Duotone, Pixel, Soft, Mono block.
- Outline is the default stroke set. The other five packs draw their own SVGs for every CORE glyph (primary rail, settings, More-menu set, plus user / menu / more / play). Preferences chips still preview the five primary-rail glyphs.
- Packs use `currentColor`, so they work with **any** color theme (e.g. Aurora + Pixel).
- A preset can also set the icon *silhouette* — stroke weight, corner style, and whether glyphs are outlined or solid. A glyph drawn as a solid shape (the Favorites heart, the play triangle) stays visible under the outline presets rather than being erased by them.

## Fonts

- Preferences → **Font** picks the typeface used across the UI, independently of
  your color theme and icon pack.
- Faces are chosen to evoke an era rather than imitate a brand: an 8-bit pixel
  face, a compact handheld face, an arcade face, a 32-bit/disc face, and a CRT
  terminal face — plus **System UI**, the default, which uses your own device's
  fonts.
- Emulator and library surfaces can pick an era-appropriate face per system
  automatically (a Game Boy title gets the compact pixel face, a PS1 title the
  disc-era one).

- **Every listed face ships with Oneirodex.** The open-licence (OFL 1.1) faces
  are bundled in the release and copied into place on every server start — no
  download, no admin step, and nothing to do on an air-gapped install. If the
  picker ever shows *not installed*, that is a genuine file problem on the
  server, not the normal state.

> **What is *not* bundled:** console manufacturers' own typefaces. Those are
> trademarked and not licensed for redistribution. The bundled faces evoke each
> era rather than imitating a brand. An admin can still drop a licensed font in
> and have it offered alongside — [theme-fonts-and-images.md](../admin/theme-fonts-and-images.md).

## Tile size

- Preference: continuous **0–100% slider** (TopNav) — legacy S/M/L/XL values still load and map onto the scale.
- Affects Library / Favorites / Discover shelves; denser gaps on smaller sizes; grid re-measures with a short debounce so dragging feels smooth instead of snapping between sizes. Range is about **120–400px** (0–100%). **Grid** and **Rows** use that size too — Grid is genre shelves, Rows is a scaling title list, not a denser wrap.
- **Everything on a tile scales with it** — the corner controls (menu, favourite, play status), the badges, the platform chip and the Preview pill all derive their size from the tile, so a 120% tile and a 30% tile read the same way rather than one being all chrome.
- Hovering a tile grows it **25%** equally around its resting box (a transform, so the grid does not reflow), from the tile's own centre — including the first and last tile in a Discover row, which used to grow sideways out of the row edge. There is no accent glow on the enlarge.
- **Show titles under tiles** sits directly under the slider here (it was a checkbox on the top bar). Off gives you the covers alone and a shorter tile; the Discover shelves and the catalog grid both re-derive their height from it.

## Items per page

- Preference: **items per page** for Library / similar browse grids.
- Allowed values: **20 / 50 / 100 / 200 / 250 / 300 / 400 / 500 / 1000** (API allowlist; other values are rejected).

## Preferred game language

- Preference: **Preferred game language** (BCP-47, default `en-US`).
- Separate from UI locale (`en` / `es`). Used for ROM language chips and translation-patch prompts on game details.
- Details: [translation-patches.md](translation-patches.md).

## Tips

- A theme or icon-pack change takes effect on a normal reload. Hard-refreshing used to be necessary and no longer is — if it makes a difference for you, that is worth reporting rather than repeating.
- Admin theme install is separate from your personal preset — see [themes-reset.md](../admin/themes-reset.md).
- If account/prefs chrome looks stale after deploy (`od-account.css` / `modal-components` on the library volume), ask an admin for **Reset Default Themes**.
- Icon packs install on app boot; they are not wiped by Reset Default Themes.
- **Loading icons (admin):** household spinner mode — rotate catalogue or lock to one id (Admin → Themes → Loading icons). Members/SPA read `GET /api/loading-icon`. Motifs appear on Auto Scan browse + `PageStatus` loads. Admin: [themes-reset.md](../admin/themes-reset.md#loading-icons-admin).
- Social / voice / Report issue: [social-and-voice.md](social-and-voice.md) · [faq.md](faq.md).
