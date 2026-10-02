# UI Wave 0 — design tokens (Oneirodex)

> **Doc status:** Reference

These CSS variables are the shared foundation for web + future desktop client.
Tracked source: `oneirodex/setup/default_theme/css/od-tokens.css` (presets regenerated at **`GENERATOR_VERSION` 10**).

Import after theme base.css or use as a reference when migrating React islands / admin SPA.

```css
:root {
  --od-bg: #0b0d10;
  --od-surface: #141820;
  --od-surface-2: #1c2230;
  --od-text: #f2f4f8;
  --od-text-muted: #c4ccd8;
  --od-accent: #2fd67b;
  --od-accent-contrast: #0b0d10;
  --od-success: #4ade80;
  --od-danger: #ff6b6b;
  --od-warning: #ffc94a;
  --od-info: #5ac8fa;
  --od-family-nintendo: #e60012;
  --od-family-sony: #0070d1;
  --od-family-xbox: #2fd67b;
  --od-family-sega: #1a66ff;
  --od-family-atari: #f5a623;
  /* Brand marks for external store / social / catalog links (ExternalStoreLinks).
     Not themed — each is the brand's own colour. Full set in od-tokens.css:
     --od-brand-steam / -gog / -epic / -playstation / -xbox / -amazon / -humble /
     -itch / -ea / -ubisoft / -fandom / -igdb / -youtube / -wikipedia / -official /
     -facebook / -x / -twitch / -instagram / -reddit / -android / -apple / -unknown */
  --od-brand-steam: #66c0f4;
  --od-brand-playstation: #0070d1;
  --od-brand-xbox: #107c10;
  /* Play-status indicator colours (GameCard status dot + dropdown). Semantic. */
  --od-status-unplayed: #808080;
  --od-status-unfinished: #4A90E2;
  --od-status-beaten: #50C878;
  --od-status-completed: #FFD700;
  --od-status-wont-play: #DC3545;
  --od-status-none: #808080;
  --od-border: rgba(255, 255, 255, 0.12);
  --od-focus-ring: color-mix(in srgb, var(--od-accent) 70%, white);
  --od-tile-min: 180px;
  --od-tile-gap: 10px;
  --od-crt-opacity: 0.03;
  /* Style B glass launcher chrome */
  --od-glass-bg: rgba(20, 24, 32, 0.72);
  --od-glass-border: rgba(255, 255, 255, 0.14);
  --od-glass-blur: 12px;
  --od-platform-accent: var(--od-accent);
  --od-platform-motion: none;
  --font-ui: "Segoe UI", "Helvetica Neue", sans-serif;
  --font-display: "Arial Black", "Segoe UI", sans-serif;
}
```

Member SPA also ships `frontend/member-app` chrome (`glass.css`, TopNav). Built **`member-app.css`** must be linked in the SPA shell.

## css-token-lint ratchet

`scripts/css-token-lint.mjs` enforces "*defining* a token may use a literal; *using* a value must go through one" across `.css`, JSX `style={{}}` blocks, **and** — since wave B1.5 — hex literals on colour-ish keys (`color` / `background` / `backgroundColor` / `borderColor` / `fill` / `stroke`) in `.js` / `.jsx` object and array literals. That last rule (`no-raw-js-color`) closed the blind spot where a brand/status table carried raw hex on a plain object property and then handed it to the DOM as a CSS custom property, so the style-block scan skipped it. Repoint such constants to `var(--od-brand-*)` / `var(--od-status-*)`. Baseline `scripts/css-token-lint.baseline.json` stays `{}`.

## Command palette (planned)

- Shortcut: Ctrl/Cmd+K
- Sources: games search (`/api/search`), admin jumps
- Ship as React island under `frontend/command-palette/` in Wave 0.1

## Checklist

- [x] Document tokens (default accent `#2fd67b` + glass)
- [ ] Shared package `frontend/design-system`
- [ ] Command palette island
- [x] Wire tokens into theme pipeline / member SPA
- [ ] Wire into React admin SPA (`frontend/admin-app`) — partial: consumes the tokens
  and shares `DataTable` / `PageStatus` / `MetricStrip`, but still lacks the shared
  primitives (one card / page-header / field). Admin Help moved fully onto the tokens
  in the member Help language (UID-063, 2026-09-08); a bounded sweep replaced every
  static inline-`style={{}}` object (23 sites) with `.od-admin-*` utility classes,
  taught bare `<select>` / `<textarea>` in a panel to inherit the `.od-admin-input`
  box, and tokenised the motion (`--od-motion-*`) and elevation (`--od-shadow-*`)
  literals in `styles.css` / `ops.css` (UID-062 pass). Remaining: `.od-art-studio*`
  / `.od-images-*` / `.od-ext-*` / `.od-scan-*` subsystems, and the
  `styles.css` / `ops.css` split.
