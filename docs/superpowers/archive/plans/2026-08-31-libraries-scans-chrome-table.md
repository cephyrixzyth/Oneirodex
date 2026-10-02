# Libraries & scans chrome + DataTable — Implementation Plan

> **Doc status:** Archive

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Top-bar Libraries/Scan unfurls, remove in-page Add/Tools buttons, mount a themed DataTable with per-column filters and fixed thumbs on the Libraries pane; full Unraid rebuild + Reset Themes.

**Architecture:** Keep Jinja multi-pane `/scan_management` + `/libraries`. Admin SPA enhances the portaled contextbar with unfurl menus and mounts a React Libraries table into `#odLibrariesReactRoot`. Enrich `GET /api/get_libraries` for platform/game_count/image. Extend shared `DataTable` with optional per-column filters.

**Tech Stack:** Flask/Jinja, admin-app React, DataTable, od-appbar unfurl CSS, Bootstrap tabs, pytest/vitest.

---

## File map

| File | Responsibility |
|---|---|
| `oneirodex/routes_apis/library.py` | Enrich `get_libraries` payload |
| `oneirodex/templates/partials/chrome.html` | Optional unfurl-capable view tuples (if Jinja emits structure) |
| `oneirodex/templates/admin/admin_manage_scanjobs.html` | Contextbar view list → Libraries/Scan groups |
| `oneirodex/templates/admin/admin_manage_libraries.html` | Same contextbar shape |
| `oneirodex/templates/admin/partials/admin_libraries_panel.html` | Strip toolbar; React mount + keep modals/batch bar |
| `frontend/admin-app/src/DataTable.jsx` (+ css/tests) | Per-column filters |
| `frontend/admin-app/src/LibrariesPanel.jsx` (+ test) | DataTable + selection + actions |
| `frontend/admin-app/src/useLibrariesContextbarUnfurl.js` (+ test) | Portaled seg → Libraries/Scan unfurls |
| `frontend/admin-app/src/App.jsx` / portal hook | Mount panel + wire unfurl |
| `oneirodex/setup/default_theme/css/admin/admin_manage_*.css` | Shell flatten (done) + panel polish |
| Docs | libraries-and-scans, ui-debt, progress, themes-reset |

---

### Task 1: Enrich `GET /api/get_libraries`

**Files:** `oneirodex/routes_apis/library.py`, `tests/` covering get_libraries if present

- Return `platform` (string value), `game_count` (SQL count, not relationship load), resolved `image_url` with static default when empty.
- Keep existing fields (`uuid`, `name`, `last_scan_folder`, watch payload).

**Verify:** pytest slice on library API.

### Task 2: DataTable per-column filters

**Files:** `frontend/admin-app/src/DataTable.jsx`, `DataTable.css`, `DataTable.test.jsx` (create/extend)

- Add `columnFilters` prop (default false). When true, render filter inputs for columns with `filterable !== false` (skip select/actions).
- AND across column needles; keep optional global `toolbar` filter.
- Vitest: filter narrows rows; sort still works.

### Task 3: `LibrariesPanel` React mount

**Files:** `LibrariesPanel.jsx`, test, `admin_libraries_panel.html`, App/portal wiring

- Columns: select, name+thumb, platform, games, actions (`od-cbtn-group`).
- Wire scan/edit/delete to existing routes/modals/APIs where possible.
- Multi-select + sticky batch bar: either keep Jinja batch bar driven by custom events, or reimplement minimally in React calling same APIs.
- `img onError` → default library image.
- Mount only when `#odLibrariesReactRoot` exists.

### Task 4: Contextbar unfurls

**Files:** Jinja contextbar callers, `useLibrariesContextbarUnfurl.js`, portal tests, `od-appbar.css` if gaps

- Seg list: Libraries (unfurl) · Scan (unfurl) · tools · unmatched · filters · extensions · image_queue.
- Libraries menu: list pane + Add library link.
- Scan menu: Auto + Manual panes (Bootstrap tab).
- Active styling on parent when child pane active.
- Update `useLegacyContextbarPortal` tests.

### Task 5: Strip in-page toolbar + docs

- Remove Add Library / Library tools from panel toolbar (Add lives in unfurl).
- Docs-sync: libraries-and-scans, ui-debt UID-031, progress, themes-reset.
- Browser verify after deploy.

### Task 6: Full deploy

- `python scripts/ops/unraid_rebuild_and_reset.py` (or project equivalent) + Reset Themes.
- Hard-refresh admin Libraries pane; verify unfurls, table, images, actions.

---

**Commit policy:** Do not commit unless user says ship; deploy is authorized.
