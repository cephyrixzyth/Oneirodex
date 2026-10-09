# Theme art direction

> **Doc status:** Active

> Human, 2026-08-31: *"themes are horrible; need full design with AI artwork, not
> CSS-only."* This is the answer to the second half of that sentence — what a
> theme **is**, so that art (drawn now, generated later) has somewhere to land.

## What a theme is

A theme is not a hue. It is six things that have to agree:

| Layer | Owned by | Where it lives |
|---|---|---|
| **Palette** — accent, surface, text, border | the preset | `css/od-tokens.css`, generated per preset |
| **Geometry** — radius, spacing, type scale, shadow, motion | the preset | `_system_geometry()` in `preset_themes_geometry.py` (catalogue in `preset_themes_catalog.py`, generator in `preset_themes.py`) |
| **Room** — the space the product sits in | the **era**, not the preset | `css/od-era.css` variables + `art/era/<era>.svg` |
| **Marks** — cover placeholder, avatars | the preset | `avatars/*.svg`, recoloured per preset; `.od-cover-fallback` is CSS + live text |
| **Motifs** — loading animations | shared, tinted | `css/od-loading-motifs.css`, `currentColor` throughout |
| **Glyphs** — rail and chrome icons | the icon pack the preset names | `icon_pack` on the preset |

The shipped catalogue now has six redesigned presets: Mosslight, Afterglow
Arcade, Graphite Studio, Signal Room, Tape Deck, and Deep Space Media. Each has
its own palette, geometry, type, glyph treatment, room, avatar treatment, and
platform-mark art direction. The former built-in presets are retired; uploaded
themes remain untouched. Existing preferences are mapped to the closest new
preset until the member picks another one.

The retired presets are removed only when their folder still carries the
Oneirodex generator marker. A custom upload with the same folder name is kept.

## The rule that keeps rooms from becoming nine copies of one room

**The room keeps its own palette. Only the light the product makes is themed.**

A wood den is brown because dens were brown. Tinting the whole scene to the
preset accent is exactly what made the pre-37 gradient rooms read as one room
nine times. So each `art/era/*.svg` is authored in its era's palette, with a
single sentinel colour — `#2fd67b` — used *only* where the theme should show
through: the screen glow, a standby LED, a boombox bar. `_write_preset_era_art()`
substitutes that one value with the preset's `--od-accent`, exactly as
`_write_preset_avatars()` does for the three avatar colours.

Anyone authoring or generating room art works inside that contract:

- era palette for the world, `#2fd67b` for anything that should follow the theme;
- `viewBox="0 0 1600 900"`, `preserveAspectRatio="xMidYMid slice"`, composed so
  the **bottom centre** survives cropping (the layer is `background-position:
  center bottom` under a UI that occupies the middle of the screen);
- no photographs, no manufacturer marks, no licensed art — original geometry
  that *reads* as a console, a cabinet, a CRT, without being anyone's product;
- quiet. This is backdrop. Anything with hard contrast in the centre fights the
  catalogue grid that sits on top of it.

## Avatars and platform marks

The seven stock avatar SVGs are newly drawn in one matching emblem style. They
use only the accent, panel, and muted source colours so the preset generator can
recolour the complete set without changing member-uploaded portraits. Platform
marks use a theme-specific illustration direction in addition to the platform
hardware silhouette and theme palette. Recreate generated marks from Art Studio
after changing a preset's art direction; generated image files are runtime
library assets and are not overwritten automatically.

## How a room is drawn

`#od-era-atmosphere` (see `templates/partials/era_atmosphere.html`) stacks, back
to front: `wall` → **`scene`** → `window` → `posters` → `furnish` → `stand` →
`floor` → `lamp` → `vignette` → `grain`. The gradient layers are the *light*;
`scene` is the *furniture*. Both stay: the gradients respond to tokens and
animate cheaply, the scene gives the room objects to be a room with.

`--od-era-scene` points at `../art/era/<era>.svg` — relative to the stylesheet,
so it resolves inside **the preset's own folder** and each preset paints its own
recoloured copy with no generator work per URL. `--od-era-scene-opacity` is
per-era, because a bright arcade and a dim den do not need the same weight.

## Replacing drawn art with generated art

The generated-art half of THEME-AI (SD.Next sidecar, `docker-compose.artwork-local.yml`,
the RTX 2080 box — **do not batch FLUX there, 8 GB**) drops a rendered backdrop
at the same path with the same name. Nothing else changes: no CSS, no generator,
no template. Requirements for a generated backdrop are the contract above, plus:

- deliver a raster at 1600×900 or larger, or an SVG that traces it;
- keep the accent-bearing element (screen, LED) as a separate pass in `#2fd67b`
  so the substitution still works, **or** accept that the room will not follow
  the theme accent;
- bump `GENERATOR_VERSION` so every preset rebuilds and operators Reset Themes.

## Deploy trap

Theme CSS, JS and art are served from the **library volume**, not the image.
A change here is invisible until the container is rebuilt **and** an admin runs
**Reset Themes** (Preferences → Look & density, admin only). `GENERATOR_VERSION`
is what makes that reset actually regenerate rather than keep the stale copy.

## Still open

- ~~**E1** console-named theme packs (a pack per system family, not per decade).~~ **Done (v11 H-T, generator 40):** six `group: 'console'` presets — Cartridge red, Disc-tray blue, Signal green, Deep blue 16-bit, Woodgrain amber, Terminal teal — each the shell language of one family in the era room it lived in; names and copy describe the look, never a maker (Class A lock). Data only: `preset_themes_catalog.py` + `preset_themes_geometry.py`.
- ~~**E2** loading motifs in full colour per console~~ — **done.** They are
  still `currentColor`, which was the right mechanism all along; what was
  missing is that `.od-loading-motif` read `--od-accent` instead of
  `--od-platform-accent`, so a Mega Drive cabinet span in the theme accent like
  everything else. `platformSkins` already sets that variable on `<html>` per
  system family, and the fallback keeps every non-system page unchanged.
- ~~**E4** per-theme rail glyph drawings~~ — **done (v11 H-T).** First half: one shared `railIcons.tsx` restyled by the icon-pack tokens. Second half: `frontend/shared/src/railIconsEra.tsx` redraws the eight most-visible destinations (discover · library · systems · downloads · favorites · collections · playtime · chat) in three hands — *pixel* (wood den 80s, arcade cabinet), *rounded* (teen bedroom 90s, carpet den late 90s), *angular* (media centre 00s, desk). `RailIcon` prefers the era drawing when the theme is a decade room or system-family pack (`data-theme` `era-*` / `console-*`); colour cabinets and the default keep the shared set.
- `platformSkins` is still duplicated member↔admin; `railIcons` no longer is.
- Generated (AI) backdrops for the six rooms, per the section above.
