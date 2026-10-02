# Libraries & scans — top-bar unfurls + Libraries DataTable

> **Doc status:** Archive

**Date:** 2026-08-31  
**Status:** Approved — implementing / deploying  
**Deploy:** Full Unraid rebuild + Reset Themes when implementation lands

## Problem

1. Libraries pane still shows in-page **Add Library** / **Library tools** that duplicate the top bar.
2. Top bar lists **Auto scan** and **Manual scan** as peer segs — too many top-level items.
3. Libraries table is Bootstrap/Jinja: mismatched action buttons, broken library thumbs (`image_url` often stale/absolute), no consistent sort/filter.
4. Outer page shell card nesting was already being flattened (local `GENERATOR_VERSION` 23 work).

## Goals

- Thin top bar owns navigation actions via **unfurl menus** (same chrome as member View).
- Libraries list is a proper **admin SPA DataTable** with sort + **per-column** filters.
- Row actions are one **`od-cbtn-group`** bar: Scan · Edit · Delete.
- Thumbs resolve reliably (API + UI fallback).
- Keep **Library tools** pane in the top bar; remove only the in-page duplicate button.
- Full rebuild + Reset Themes after ship of this slice.

## Non-goals

- Rewriting Auto / Manual / Unmatched / Filters / Extensions / Image queue panes into React this pass.
- Trail summary popover (libraries · games chip) — deferred.
- Removing drag-reorder forever (may pause while DataTable owns sort; restore later if needed).

## Decisions (locked)

| Topic | Choice |
|---|---|
| Scan collapse | One **Scan** seg → unfurl: Auto scan · Manual scan |
| Add library | **Libraries** seg → unfurl: Libraries (list) · Add library |
| Tools | Keep top-bar Tools pane; remove in-page Library tools button |
| Row actions | Compact `od-cbtn-group` per row |
| Table tech | React **DataTable** mounted into the Libraries pane |
| Filters | Per-column filter inputs (extend shared DataTable) |
| Deploy | Full rebuild + Reset Themes |

## Design

### 1. Top-bar contextbar unfurls

**Markup (Jinja `chrome.contextbar` + theme JS, or portal-time enhance in admin SPA):**

Segment order after change:

`Libraries ▾` · `Scan ▾` · `Library tools` · `Unmatched` · `Filters` · `Extensions` · `Image queue`

- **Libraries** trigger: unfurl panel  
  - **Libraries** → `#librariesPanel` (Bootstrap tab)  
  - **Add library** → `/admin/library/add` (navigation)
- **Scan** trigger: unfurl panel  
  - **Auto scan** → `#autoScan`  
  - **Manual scan** → `#manualScan`
- Active state: if Auto or Manual pane is active, **Scan** reads active; if Libraries pane or Add Library destination context, **Libraries** reads active.
- Reuse member CSS: `.od-seg__unfurl-anchor`, `.od-contextbar__views-unfurl`, `.is-unfurled` from `od-appbar.css`.
- Prefer enhancing the portaled bar in admin SPA (or small theme JS) so Bootstrap tab switching still works for pane hrefs.

### 2. Libraries pane chrome

- Remove toolbar links: Add Library, Library tools.
- Keep selection count on the table edge + sticky multi-select batch bar (Scan / Edit / Delete) wired to existing batch APIs.
- Mount point: `#odLibrariesPanel` (or a dedicated `#odLibrariesReactRoot` inside the pane) hosted by admin-app while on `/libraries` or `/scan_management?active_tab=libraries`.

### 3. DataTable

**Columns**

| Column | Sort | Per-column filter | Notes |
|---|---|---|---|
| ☐ select | no | no | Checkbox; select-all in header |
| Library | yes | text | Thumb + name; platform as muted secondary or own column |
| Platform | yes | text/select | From `platform` |
| Games | yes | numeric/text | Count |
| Actions | no | no | `od-cbtn-group`: Scan · Edit · Delete |

**Data:** Prefer enriching `GET /api/get_libraries` (or admin batch list) with `platform`, `game_count`, resolved `image_url`. Avoid `library.games|length` N+1 in Jinja.

**Images:** Server returns a resolvable URL; if file missing, fall back to `newstyle/default_library.jpg` (or platform system mark when available). Client `onError` swaps to the same default so broken paths never stick.

**DataTable enhancement:** optional `columnFilters` mode — second header row or inline inputs under each filterable column; AND across columns; keep global filter optional/off for this table if per-column is enough.

**Row actions**

- Scan → existing scan start / conflict flow (same as today).
- Edit → `/admin/library/<uuid>/edit` (or current edit route).
- Delete → existing typed-confirm / delete modal path (reuse Jinja modal hosts or port minimal confirm).

### 4. Page shell flatten (already in tree)

- `.admin_manage_scanjobs-nav-panel > .container-settings.od-adminpage` + `.admin_manage_scanjobs-tab-content`: no card chrome.
- `GENERATOR_VERSION` **23**.

## Approaches considered

1. **Jinja table + theme JS sort/filter** — faster, but drifts from admin DataTable. Rejected by product choice.
2. **Full React Libraries & scans page** — replaces all panes. Too large for this slice.
3. **Hybrid (chosen):** keep Jinja multi-pane document; React owns Libraries list + top-bar unfurl behavior; other panes stay Jinja.

## Risks

- Bootstrap tab + unfurl: Scan/Libraries triggers must not break `data-bs-toggle="tab"` for sibling panes.
- Portal tests (`useLegacyContextbarPortal`) need updating for nested unfurl markup / summary.
- Drag-reorder vs client sort: document that display order follows DataTable sort while filters active; optional follow-up to restore grip reorder on unsorted view.

## Success criteria

- No in-page Add Library / Library tools on Libraries pane.
- Top bar: Libraries and Scan unfurl as specified; Tools pane still reachable.
- Libraries table sorts and filters per column; actions are one themed button bar.
- Library images show default (or mark) instead of broken icons.
- Verified in browser after full rebuild + Reset Themes.

## Docs to touch on implement

- `docs/admin/libraries-and-scans.md`
- `docs/admin/themes-reset.md` (v23 already noted)
- `docs/dev/ui-debt-log.md` (UID-031 follow-up)
- `docs/strategy/progress.md` living head
