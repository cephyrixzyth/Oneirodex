# Admin Jinja → React inventory (H-D.5)

> **Doc status:** Active

Measured 2026-09-19 on `main` after #150. The admin surface is a *declared*
hybrid: every admin template extends `base_admin.html` and states, through
`{% block admin_render %}`, whether React owns the body (`spa`) or the Jinja
body plus a `static/js` handler does (`auto` / `legacy`). This is the census
of what is still server-rendered, what it depends on, and the order in which
it gets ported. It closes the "progressive hybrid" verdict by making the tail
visible and sized instead of implied.

## The rule for a port

A port replaces **the template body and its JS handler together**: the
template flips to `admin_render` = `spa` and stops including the script; the
React page in `frontend/admin-app/src/pages/` talks to the same JSON API the
handler already used. The old handler file is deleted in the same commit — a
stale copy on the themes volume is harmless once no template loads it. Where a
handler talks to a *form* route rather than a JSON API, the API comes first
(see `docs/dev/pydantic-adoption.md`), then the page. Never rename a DOM id a
theme-volume handler still reads in the same release as the handler.

Each port adds the page to `AdminRoutes.tsx`, a vitest file next to the page,
and keeps the `<h1>` equal to the settings card title (that is what
`AdminRoutes.test.tsx` asserts).

## Census

48 templates under `templates/admin/` (45 pages + 3 partials).

**Tier 0 — already React (17).** Six-line shells; nothing to port:
`admin_announcements`, `admin_art_studio`, `admin_dashboard`, `admin_invites`,
`admin_manage_extensions`, `admin_ops`, `admin_remote_play`,
`admin_scan_match_settings`, `admin_settings_shell`, `admin_support`,
`admin_system_danger`, `admin_users`, `quality_profiles`, `storage`, plus
`admin_plugins` (empty `auto` body — React `PluginsPage` renders) and, since
this cycle, `detail_layout` and `emulator_profiles` (the first two ports below).

**Tier 1 — small panels (first).** One handler of under 80 lines; the API
exists or is one small PR away. Ordered by handler size.

| Template (lines) | Handler (lines) | API today | React page today |
|---|---|---|---|
| `detail_layout` (24) | `od_admin_detail_layout.js` (58) | `/api/layouts/detail` GET/PUT | **`DetailLayoutPage` — done** |
| `admin_newsletter` (87) + `view_newsletter` (35) | `od_admin_newsletter.js` (24) | form routes only — API first | — |
| `admin_manage_whitelist` (88) | `od_admin_whitelist.js` (38) | form routes + `DELETE /admin/whitelist/<id>` — API first | — |
| `features_settings` (116) | `od_admin_features.js` (39) | form route + `/api/admin/challenge-solver/*` | — |
| `admin_help` (294) | `od_admin_help.js` (58) | static content (no API) | — (HelpPage is member-side) |
| `admin_manage_downloads` (83) | `od_admin_downloads.js` (62) | server-rendered table + `/api/delete_download/<id>` | — |
| `admin_reference_sets` (160) | `od_admin_reference_sets.js` (172) | `/api/reference-sets/rehash`, `/api/reference-sets/repair-preview`, `/api/licensed-catalog/refresh` (+ server-rendered table) | — |
| `emulator_profiles` (32, `legacy`) | `od_admin_emulator_profiles.js` (68) | `/api/emulator-profiles` | **`EmulatorsPage` — done** (the firmware / RA / pilot island moved in with it) |
| `ai_assist` (77) | `od_admin_ai_assist.js` (75) | `/api/ai/config`, `/status`, `/triage`, `/apply-triage`, `/doctor-notes` | route stub |
| `admin_manage_igdb_settings` (33) · `admin_manage_smtp_settings` (40) | `admin_manage_igdb_settings.js` · `admin_manage_smtp_settings.js` (+ `password_visibility.js`) | form routes | `IntegrationsPage` (inventory only) |
| `admin_chat_emoji` (66) · `admin_manage_invites` (53) · `admin_statistics` (68) · `admin_server_logs` (99) · `admin_manage_themes_readme` (90) | small / chart-utils | mixed | `InvitesPage` covers invites |

**Tier 2 — medium forms and dashboards.** Each is a page of its own.

| Template (lines) | Handler(s) | Note |
|---|---|---|
| `admin_manage_filters` (145) | `admin_manage_filters.js` | scanning filter patterns |
| `admin_manage_library_create` (154) | `admin_manage_library_create.js` | `LibrariesPage` owns the list; create is still Jinja |
| `admin_manage_themes` (163) | `od_admin_themes.js` (177) | `ThemesPage` is chrome-only today; the picker + Reset Themes button is the body |
| `admin_discovery_sections` (174) | `admin/discovery_sections.js` (theme volume) | drag-order of Discover shelves |
| `admin_server_status` (195) | `admin/server_status.js` + `chart-utils.js` | charts; `OpsPage` has the tiles, not the history charts |
| `attract_mode_settings` (201) | `admin_attract_mode.js` + `od_attract_boot.js` | live preview iframe |
| `arr_module` (216) | `od_admin_arr.js` (386) | GET+PUT, bulk text; validator note in pydantic-adoption |
| `new_server_settings` (272) | `admin_manage_server_settings.js` | the big settings form; route stub exists |
| `admin_game_identify` (277) | `admin_game_identify.js` | add/edit game identify — shared with `routes_games_ext` |
| `integrations` (348) | six handlers incl. `od_admin_integrations_oidc.js` | `IntegrationsPage` shows the inventory; the credential forms are here |

**Tier 3 — the Libraries & scans hybrid (last).** `admin_manage_scanjobs`
(986) with partials `admin_libraries_panel` (120), `admin_library_tools_body`
(169), `admin_scan_jobs_panel` (123) and handlers `od_admin_scanjobs_inline.js`
(465), `od_admin_library_tools.js` (212), `admin_manage_scanjobs.js`,
`admin_manage_libs.js`, `od_reparent_lib_modals.js`. React already owns the
tab bar, the libraries panel mount (`useLibrariesPanelMount`), the propose and
import leaves and the scan toasts; the panels themselves are still
server-rendered. `admin_manage_libraries` (52) and `admin_library_tools` (11)
are redirect shells onto it. This is the one that pays for the others' pattern.

## Order

Tier 1 top to bottom, then Tier 2 by size, Tier 3 last. Each port is its own
PR (`v11/debt-admin-react-<n>`), with the live page read in the browser after
deploy — the `auto` heuristic in `base_admin.html` means a half-flipped
template can blank a route, which only the deployed page shows.

## Counts

| | 2026-09-19 |
|---|---|
| Templates | 48 |
| Server-rendered bodies (`auto` / `legacy`) | 28 pages + 3 partials |
| Template lines still server-rendered | 5,000 |
| Handler JS files still loaded by a Jinja page | 33 |
