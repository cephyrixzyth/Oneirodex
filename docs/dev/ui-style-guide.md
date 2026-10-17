# Oneirodex UI style guide

> **Doc status:** Active

This is the shared visual and interaction contract for Oneirodex web surfaces.
It guides the member and admin SPAs, Ops Glance, Python-built document shells,
and future consumers. It is a baseline for review, not proof that every page
already follows it. Unresolved page findings remain in the
[UI debt log](ui-debt-log.md).

## Product defaults

- Start in the dark green aurora theme, independent of the operating-system
  preference. Keep text, controls, focus and status readable. Where a surface
  offers light themes, support them through the same semantic token contract.
- Use the existing `--od-*` token vocabulary and `.od-*` primitives. Literal
  colors, spacing, type, shape, motion and elevation values belong in the
  canonical token/theme CSS, not in component styles. Run
  `node scripts/css-token-lint.mjs` after CSS or JSX style edits.
- Preserve theme layers: color palette controls semantic colors; room/era
  controls scenery and may select an era glyph hand; icon pack controls glyph
  appearance. Status colors and external brand marks retain their meaning.
- Buttons and fields must fit their labels at user zoom and larger text sizes.
  Buttons grow with content, retain the shared target-size floor, and every
  rendered React `<button>` has a class.
- Keep visible `:focus-visible` feedback, native keyboard behavior, and reduced
  motion. Icon-only controls need an accessible name; decorative glyphs are
  hidden from assistive technology.

## Forms and destructive actions

Use the shared field and button primitives for file uploads, settings and other forms. Multipart uploads go through the shared browser requester without setting `Content-Type` manually, so the browser supplies the form boundary; retain server-side type, size and content validation. Destructive actions use the shared named confirmation dialog, explain what changes, and keep Cancel as a no-op. Pages preserve a visible loading, failure/Retry, empty and success state.

## Source of truth and package boundary

`frontend/shared` is the private npm workspace package `@oneirodex/ui` (currently
version 1.1.9). Its public entry point is `frontend/shared/src/index.ts`; React
and React DOM are peer dependencies. Member, admin and Ops Glance apps consume
this package. Extend it when behavior is genuinely common; do not create a
second Oneirodex component package or copy an app's source into another app.

The current source map is:

| Concern | Canonical source today | Framework-neutral contract |
|---|---|---|
| Tokens and common CSS primitives | `oneirodex/setup/default_theme/css/od-tokens.css`, `od-primitives.css`, and related theme CSS | CSS custom properties and `.od-*` classes; page CSS consumes tokens. Theme volume copies must be refreshed through Reset Themes after source changes. |
| React controls and state | `frontend/shared/src/index.ts` and its exported modules | React adapters implement shared semantics and use the same tokens/classes as Python-built document shells. |
| Desktop shell presentation | `clients/desktop/src/styles.css` imports the canonical `od-tokens.css` | The desktop shell consumes the shared CSS token vocabulary and defines its own UI. Its full and thin shells intentionally use text-labeled controls; this does not imply that it uses the React component package or React rail-icon exports. App/window icons and the web favicon are brand assets, not themeable UI glyphs. |
| Rail icons | `frontend/shared/src/railIcons.tsx` and `railIconsEra.tsx` | Semantic icon keys, SVG geometry, `currentColor`, shared viewBox, theme-aware fallback; see Icons below. |
| Shared icon catalog | `frontend/shared/icons/manifest.json`, generated to `frontend/shared/src/generatedIconPaths.tsx` | Semantic names, aliases, safe SVG geometry and accessible-use guidance have one framework-neutral source. |
| App-specific meaning and data | Owning application | Keep routes, permissions, API schemas, query semantics, and feature options in the app that owns them. |

CSS custom properties are the runtime-neutral token interface: consumers load
the canonical theme stylesheet and use `var(--od-...)`. Do not create a parallel
token package, duplicate palette values in JavaScript, or require React, Flask,
or a CSS framework to consume the visual vocabulary. A non-React runtime may
provide a small adapter, but it must preserve the contract and must not import
React exports or Flask template helpers.

`@oneirodex/ui` is private. This guide does not promise an externally installable
package, public asset URL, semantic-versioning policy, or hosted icon service.
An external application can follow the CSS and markup contract only after it
has access to the theme assets. Public publication and asset distribution need
a separate release decision; do not fork or publish the private workspace as a
shortcut.

### Local catalog workflow

The inspectable catalog lives in `frontend/ui-catalog` and imports real exports
from the private `@oneirodex/ui` workspace. From the repository root, run:

```sh
npm run dev --workspace ui-catalog
npm run build --workspace ui-catalog
npm run test --workspace ui-catalog
```

Use `npm run typecheck --workspace ui-catalog` for a standalone TypeScript
check. The catalog is local developer tooling; it is not installed by external
applications or served as a public component library. After building it, the
loopback Project hub also serves it at `/ui-catalog/` alongside its decision,
phase and research boards. Run `npm run build --workspace ui-catalog` after
source changes so the hub serves the current bundle. Its dark green theme is
the initial palette. The light theme is a catalog-only preview derived from
current tokens; it does not establish that an end-user light preset ships.

When contributing a shared pattern:

1. Put semantic values and reusable CSS primitives in the canonical
   `oneirodex/setup/default_theme/css/od-tokens.css` and `od-primitives.css`;
   page/component styles consume those `--od-*` tokens. Refresh theme volume
   copies through the existing Reset Themes flow when source theme files change.
2. Add genuinely reusable React behavior under `frontend/shared/src/`, export it
   through `frontend/shared/src/index.ts`, and keep feature data, permissions,
   routes, and API behavior in the owning app. Do not add a second component
   package.
3. For an icon, follow the semantic key, drawing grid, accessibility, and theme
   rules above. Add a catalog specimen or searchable key entry so reviewers can
   see the shared export and its theme behavior. The framework-neutral icon
   manifest is the canonical source for migrated glyphs; the current catalog
   still reads the React icon map.
   The source coverage gaps and pack key sets are tracked in
   `docs/_private/evidence/icon-catalog-parity-2026-10-09.md`.
4. For filters, reuse `DataTable` search/column filtering when that behavior
   fits. Otherwise show app-owned filter markup as a clearly labeled pattern;
   do not present it as a shared export until one exists.
5. Add or update catalog examples for the export's meaningful variants and
   states. Keep the dark green initial view, inspect the light preview, and
   check keyboard focus, accessible names, disabled/busy behavior, and narrow
   layout where applicable.
6. Run the catalog build and tests above. For CSS/JSX style edits also run
   `node scripts/css-token-lint.mjs`; record exact commands, outcomes, and any
   unverified states with the change review. A catalog specimen alone does not
   close matching page findings in the [UI debt log](ui-debt-log.md).

External publication, asset distribution, a public versioning policy, remain follow-ups requiring separate design and release decisions. Further
manifest migration requires per-key semantic and geometry review.

## Token and theme contract

Token layers have distinct jobs:

1. **Foundation:** color, typography, spacing, shape, control sizing, focus,
   motion and elevation scales. `od-tokens.css` defines the dark default.
2. **Semantic:** page/background, surface, text/muted text, border, accent,
   focus and status (`success`, `warning`, `danger`, `info`). Components select
   purpose, not palette values. Status meaning must also have text, shape, or
   another non-color cue.
3. **Component:** `.od-*` primitives map semantic roles to buttons, fields,
   status blocks, cards, app bars and other shared surfaces.
4. **Theme:** a color preset may override semantic/foundation values. Room/era
   art and icon-pack treatment are independent layers; neither may erase status
   or brand meaning.

All apps and the inspectable catalog start with the dark green default. The
catalog must also show a complete light-theme presentation using the same
components and semantic roles. This is the design-system support requirement;
do not claim an end-user light preset ships until one exists in the theme
source. A surface that exposes theme selection must
apply a complete palette at initial render; it must not depend on
`prefers-color-scheme` to get the Oneirodex default. Preserve readable contrast
and native control `color-scheme` in each palette.

The canonical breakpoints are not yet a shared token. Use content-driven,
mobile-first layout; keep the document within the viewport at phone, tablet,
and desktop sizes. A component may define a local breakpoint when its content
requires one, but must not make a page-wide overflow the escape hatch.

## Shared component contract

The catalog should render components from `@oneirodex/ui`, not lookalike demos.
It should let a reviewer inspect variants, themes, sizes, focus, hover,
disabled/busy, empty/loading/error, and responsive states. If a pattern has no
shared implementation, label it as a documented pattern rather than implying
that a reusable component is exported.

| Pattern | Contract | Current shared implementation |
|---|---|---|
| Buttons | A link navigates; a button performs an action. Use primary for the main commit/start action, secondary for ordinary actions, danger for destructive actions, and ghost/quiet for low-emphasis controls. Show disabled and pending states; prevent duplicate submission. Labels wrap or controls grow without clipping. | `Button` (`default`, `primary`, `secondary`, `danger`, `ghost`, `quiet`; `sm`, `md`, `lg`; optional pill) maps to `.od-btn` classes. Each caller owns pending semantics and text. |
| Links | Use a real anchor for navigation, with a clear destination label. Do not style an action as a link while implementing it as an anchor without navigation. A fragment that names content inside a hidden tab or disclosure must reveal its container, preserve the requested fragment, and move the target into view after layout settles. | Native anchors plus shared theme classes; React routes and panels own deep links. |
| Fields and forms | Keep labels visible and programmatically associated. Associate help, validation and errors. Retain entered values when an unrelated action fails. Do not rely on placeholder text as the label. | Shared theme primitives; each app owns field schemas and form logic. |
| Dialogs | Give the dialog an accessible name. Move focus in, keep Tab/Shift+Tab inside, return focus to the opener, and make Escape/backdrop behavior explicit. Long content scrolls inside the dialog. | `Modal` provides portal, focus management, Escape/backdrop options and focus restoration; callers provide dialog content and styling. |
| Status | Distinguish loading, empty, success, warning, error and unavailable. Show a visible text label for semantic status; color and shape reinforce the text but never carry meaning alone. Missing or unavailable source data stays neutral and must not be inferred as healthy or failed. Use polite status announcements for routine changes; for polling, announce the initial state and meaningful state transitions without including changing timestamps or unchanged refreshes. Reserve assertive alerts for actionable errors. Preserve last-known data after refresh failure when the feature contract permits it. | `PageStatus` provides loading/error/empty presentation and announcement semantics. Success/warning content remains feature-owned. |
| Tables | Use table headers and caption/context. Sort controls expose state. Row actions name the subject. Bound wide content in a named, keyboard-focusable scroll region with visible focus. Provide an honest empty/no-match state. | `DataTable` supports sorting, a global text filter, optional column typeahead filters, count, density and `scrollLabel`; React pages use the shared component. |
| Charts | Give each visualization a clear heading. Pair visual proportions with labels and exact values; provide a useful empty state. Keep labels readable at phone widths and make the data available as text. | Statistics uses token-colored proportional bars with visible series labels and values; this is a page pattern, not a shared chart component. |
| Filters | Make applied values visible. Distinguish draft from immediately applied state; keep counts/chips synchronized with the query actually applied. Provide a reachable clear/reset action and touch-friendly selection. | `FilterChipGroup` in `@oneirodex/ui` renders controlled multi-select chips, a named group, optional applied-result status, and an optional clear action. The feature owns option meaning, query serialization, and whether `onChange` applies immediately or changes draft state. Pass only the count for applied results. This primitive is not a full filter toolbar or a replacement for `DataTable` search/column filters. |
| Horizontal shelves | Keep rows scrollable in both directions. For circular discovery, boundary arrows wrap to the opposite end. Let pointer drag start on linked cover art; a stationary click still navigates, while a drag past its threshold suppresses link activation. | `useRowScroll` provides drag, wheel, hover-arrow and keyboard scrolling; `DiscoverShelf` enables wrap-around arrows. |

The shared layer owns reusable presentation, keyboard/focus mechanics and
common state behavior. The feature owns option data, query meaning, permissions,
API requests and whether filter values apply immediately or after an explicit
Apply action. Do not silently change an API contract to make a visual component
fit.

### Interaction rules

- Use native buttons, links, inputs and disclosure controls where possible.
  Every button has an explicit `type` and a class. The shared button default is
  `type="button"`; submit controls opt in to `type="submit"`.
- Repeated row actions include the row subject in their accessible name (for
  example, “Edit Alice account”). Icon-only buttons name the action on the
  control, not on a decorative SVG.
- Destructive actions describe the consequence and use the shared confirmation
  flow when difficult to reverse. Busy controls expose pending state and do not
  accept duplicate activation.
- Disclosure controls use button/Tab behavior, accurate `aria-expanded`, and
  `aria-controls` only when the controlled region exists. Do not apply ARIA menu
  roles without implementing the full menu keyboard model. For an inline
  disclosure that reveals native links and buttons, Escape closes the panel and
  restores focus to its opener; outside-click dismissal leaves focus on the
  clicked destination. Keep the panel immediately after its disclosure in DOM
  order so Tab reaches its actions before unrelated controls, using normal
  native focus behavior. When a scroll or clipping ancestor would hide the
  panel, render the popup in the shell's overlay layer and anchor it to the
  disclosure. Reposition it on resize and scroll, keep it within the viewport,
  and make Tab from the disclosure enter the first action; Escape returns focus
  to the disclosure and outside-click dismissal preserves the clicked target.
- Dropdown hover and keyboard-focus states keep an opaque semantic surface
  behind readable text; avoid transparent highlights that let page content show
  through the control.
- Keep page titles, context controls, view selectors and primary actions in
  their shell's reserved areas. Avoid duplicate titles or nested panels with
  the same information role. Keep a page heading in the accessibility tree;
  `display: none` is not a visually hidden heading. At narrow widths, show the
  current destination or bring its active navigation link into view without
  moving keyboard focus or animating against reduced-motion preferences. Keep
  navigation and account areas in one visual shell; avoid a framed footer or
  divider unless it conveys a meaningful grouping.

## Icons and marks

Use stable semantic keys in kebab-case (for example `big-picture`), with
`currentColor` and the shared 24-unit drawing grid. React's `RailIcon` currently
uses a padded `-1 -1 26 26` viewBox, defaults to 18px, and reads the active era
when applicable. An unknown key renders nothing; callers should catch catalog
or key mistakes during development rather than substituting a misleading mark.

Icon accessibility belongs to the control/context:

- A decorative icon is `aria-hidden="true"` and not focusable.
- An icon-only control gets its accessible name from the button/link. Do not
  add a second competing name to the decorative SVG.
- If an icon itself conveys information outside a named control, provide a
  textual equivalent in the surrounding UI.
- Use `currentColor` and icon geometry tokens (`--od-icon-stroke`, line cap,
  line join, fill) so color/icon packs can adapt without hard-coded per-icon
  colors. Keep platform, file-type, avatar, cover-art and room-illustration
  asset families separate; they have different identity and provenance rules.

Catalog and alias requirements:

- Every canonical icon has one stable key, category, canonical geometry,
  accessible-use guidance, recommended sizes, and theme behavior.
- Aliases, when needed for compatibility, resolve to one canonical key. Show
  aliases in the catalog but do not draw or count them as separate icons.
  Normalize the rendered `data-icon` to the canonical key. The generated `sharedIconAliases` registry declares compatibility names; both
  renderers normalize those names and the catalog displays and searches them
  without counting duplicate specimens. Do not invent aliases for visual similarity.
- A theme may override a drawing or explicitly inherit the canonical drawing.
  Show both states in the catalog. `railIconsEra.tsx` currently overrides only
  the eight named destinations in `ERA_GLYPH_NAMES`; other rail glyphs inherit
  the shared drawing. Icon-pack tokens can restyle the shared drawing without
  duplicating paths. A drawing pack may apply its generic geometry only to keys
  for which it ships an SVG; every other key keeps the standard Outline shape.
  Keep the pack CSS and generated fallback selector in `icon_themes.py` aligned.
- UI glyphs, manufacturer/store/social marks and status icons are different
  categories. Keep external brand colors recognizable and use the established
  `--od-brand-*` tokens; never make brand identity depend on the active palette.

Most rail drawings remain in React icon maps, with shared geometry defined by
the framework-neutral catalog in `frontend/shared/icons/manifest.json`. It
defines `ownership`, `discover`, `integrations`, `report`, `menu`, `more`, `user`,
`download`, `downloads`, `play`, and `settings`, including category,
aliases (`plug`, `report-issue`, `cogs`, and `gear`), accessibility use, SVG shapes and theme
inheritance. `scripts/generate_icon_adapters.py` validates
the SVG whitelist and generates the React adapter. Run it after manifest edits;
`--check` detects stale output. Do not hand-edit `generatedIconPaths.tsx`.
The catalog now
shows all 61 canonical React glyph keys and, for the eight era overrides, the shared,
pixel, rounded, and angular drawings together. Its room-to-hand mapping is
visible beside the specimens. This makes renderer coverage inspectable; it does
not establish theme-pack parity beyond those eleven migrated keys. The former
`compass` drawing remains only as a React-era fallback. The catalog also shows all
six theme-pack manifests and their 17 declared keys. It renders the 85 shipped
non-outline SVG assets and the shared outline drawings; all 17 Outline keys now have shared drawings. These
pack assets are still a separate source from the neutral manifest. Extend the
manifest only after confirming each key has the same semantic meaning in each
consumer; do not convert the 120 historical branch names into aliases without
call-site review. Do not claim complete pack coverage until every
catalog key is accounted for.

The current member top bar uses only the Menu and User adapters. Both consume
shared drawings while preserving viewport, dimensions, caller props, and fixed
glyph hand. A call-site review found no consumers for the former Compass,
Download, More, Gamepad, Heart, Cogs, Systems exports or primary navigation map;
those obsolete definitions were removed. Current destination icons come from
the shared rail. The singular `download` action remains distinct from the
`downloads` destination glyph. React navigation uses the shared manifest-backed
destination drawing and the `downloads` key. Action controls continue using
`download`.

## Filters, tables, density and responsive behavior

Shared `DataTable` search, column filters and sort controls use a minimum
44px target at widths through 760px and on coarse-pointer devices. Desktop
mouse layouts retain compact controls. Keep this rule in the shared stylesheet
when adding table consumers.


The UI catalog demonstrates the shared `FilterChipGroup` and its applied-result
count, clear action, multi-select behavior, and responsive wrapping. It is a
controlled option-group primitive: consumers decide whether selection changes
apply immediately or remain draft until an Apply action, and keep result counts
bound to applied data. UID-091 remains open for broader filter-panel composition
and migration of the other app-owned filter workflows; do not merge visually
similar filters whose apply/query semantics differ.

- Filter controls report applied state and offer clear/reset. If a page has
  draft values, label or otherwise expose the Apply step; don't show draft
  counts as though results already changed. Touch users must be able to select
  multiple values without keyboard-modifier instructions.
- Keep field labels, focus, validation placement and control sizing consistent.
  Inputs and selects must remain practical to operate at narrow widths and
  browser zoom.
- Use `DataTable` when its sorting/filter behavior fits. Do not force a toolbar
  above tiny tables; use its documented options or a semantic table pattern.
  Page-specific tables may choose density, but should retain shared headers,
  row actions, empty states and theme tokens.
- Keep wide tables inside a bounded, named, keyboard-scrollable region. On
  narrow screens, let that region scroll horizontally or reflow the table when
  row relationships remain clear. Never make the whole document wider than the
  viewport.
- Use density to adjust repeated-content spacing without hiding essential
  labels, status, focus indicators or touch targets. Ensure controls and
  actions remain reachable at phone, intermediate/tablet and desktop widths.

## Standalone frontend entries

Static SPA entries that do not render inside a server-provided shell must load a
canonical theme foundation and set their own responsive page inset. Keep the
standalone default dark and token-backed; embedded entries inherit the host
shell. Record any theme-preference limitation explicitly rather than implying
that a static entry follows the signed-in user’s theme.

## Page review and audit evidence

Review each route in its real permission and data context: populated, loading,
empty, validation failure, request failure, disabled/busy and destructive
confirmation. Include keyboard focus, reduced motion, small-screen layout,
theme changes and meaningful icon rendering. Record what was actually checked;
source review alone does not establish a runtime result. The UI debt log keeps
the human symptom and acceptance criteria open until verified or explicitly
deferred. Store screenshots and route-specific evidence with the audit record;
refresh public captures from a populated instance when a shipped UI change
affects them.

### Admin field styling

Use the explicit `od-admin-input` hook for admin text, URL, number, password, email, select and textarea fields. Its page/panel rules must outrank legacy type selectors so each field consumes the shared surface, text, border and spacing tokens. Keyboard focus uses a visible token outline. Preserve native behavior for file, range, color, checkbox and radio controls.

### Modal surfaces and stable focus

Dialog panels must consume an opaque surface token with sufficient selector specificity to override generic glass panels. Use heading tokens for dialog titles and subordinate legends. Focus management must follow the open/close lifecycle; changing callbacks or busy guards must not move focus while typing. Acceptance includes sequential typing in a field other than the first, Escape, and focus return to the enabled opener.

### Message detail and delivery history

Render newsletter content as escaped plain text with `white-space: pre-wrap` and overflow wrapping. Preserve visible status distinctions for pending, sent and failed delivery. Keep the history table in a named, keyboard-scrollable region and give each detail action a subject-specific accessible name. Long recipient addresses must wrap inside narrow layouts.
