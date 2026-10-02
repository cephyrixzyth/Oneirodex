# Commit attribution — `c6fd7bf7` (W31)

> **Doc status:** Archive

`c6fd7bf7` bundles two independent bodies of work: a security/legal audit
remediation and the W29/W30 UI pass. They were committed together because they
were both uncommitted in the same tree at the same moment, not because they are
related.

The commit message says they "share the same files and could not be split
cleanly at file granularity". Measured against the diff hunks, that is
overstated: **only 6 of 236 files carry both**, and 104 of the 110 files with
identifying markers are cleanly one side or the other.

A split was considered and deliberately **not** performed. By the time it was
assessed the branch was already pushed and the security agent had committed
again on top (`fb693641`), so a rewrite would have broken a branch under active
work; and two of the six overlaps are `models.py` and `updateschema.py`, so a
split UI branch would carry a *different database schema* rather than merely
different code. This map exists so the commit can still be reviewed per area.

## Verified non-conflicting

| Check | Result |
|---|---|
| Font fix `fb693641` vs UI work | Touches only `tests/test_boot_assets.py` — no overlap |
| Security changes reaching UI files | `EMULATOR_BIOS_MAX_BYTES`, envelope baseline 151 -> 149 — both coexist, nothing to adopt |
| Admin suite | 38 files / 291 tests passed |
| Member suite | 90 files / 639 tests passed |
| Backend (CI subset + scan + reset + BIOS) | 133 + 57 + 13 + 21 passed |
| `api_envelope_lint` / `css-token-lint` | OK, none new |

## The 6 overlapping files

Both sides touched these, additively and in distinct regions:

| File | UI side | Security side |
|---|---|---|
| `oneirodex/models.py` | `scan_jobs.owner_token` | `api_tokens.expires_at` |
| `oneirodex/updateschema.py` | `owner_token` migration | `expires_at` migration |
| `oneirodex/templates/base_admin.html` | admin identity attributes for the account control | AGPL source-offer footer |
| `oneirodex/templates/site/member_spa.html` | W29 shell config | AGPL / source URL |
| `oneirodex/setup/default_theme/css/od-shell.css` | W29/W30 rail + shell | — (minor) |
| local strategy notes (`progress.md`, that commit) | W29/W30 wave rows | security wave rows |

## UI pass (W29 + W30) — 130 files

**backend** (13)

- `oneirodex/routes.py`
- `oneirodex/routes_admin_ext/system.py`
- `oneirodex/routes_apis/account.py`
- `oneirodex/routes_apis/discover.py`
- `oneirodex/routes_discover.py`
- `oneirodex/utilities.py`
- `oneirodex/utils/avatar.py`
- `oneirodex/utils/discover_pins.py`
- `oneirodex/utils/emulator_bios.py`
- `oneirodex/utils/game_details_payload.py`
- `oneirodex/utils/preset_themes.py`
- `oneirodex/utils/scan_queue.py`
- `oneirodex/utils/system_reset.py`

**docs** (8)

- `docs/admin/ops-summary.md`
- `docs/dev/ui-debt-log.md`
- `docs/runbooks/emulator-bios.md`
- local strategy notes (`docs-map.md`, that commit)
- local strategy notes (`icon-themes.md`, that commit)
- `docs/user/getting-started.md`
- `docs/user/library-and-systems.md`
- `docs/user/preferences-themes.md`

**frontend/admin-app** (28)

- `frontend/admin-app/src/AdminSideRail.jsx`
- `frontend/admin-app/src/AdminTopNav.jsx`
- `frontend/admin-app/src/AdminTopNav.test.jsx`
- `frontend/admin-app/src/AnnouncementsPage.jsx`
- `frontend/admin-app/src/ArtStudioPage.jsx`
- `frontend/admin-app/src/ArtworkPicker.jsx`
- `frontend/admin-app/src/DupeGlance.jsx`
- `frontend/admin-app/src/EmulatorFirmwarePanel.jsx`
- `frontend/admin-app/src/ExtensionsPage.jsx`
- `frontend/admin-app/src/ImagesPage.jsx`
- `frontend/admin-app/src/ImportLeafLibraries.jsx`
- `frontend/admin-app/src/InvitesPage.jsx`
- `frontend/admin-app/src/OpsPage.jsx`
- `frontend/admin-app/src/PageStatus.jsx`
- `frontend/admin-app/src/PageStatus.test.jsx`
- `frontend/admin-app/src/ProposeLeafLibraries.jsx`
- `frontend/admin-app/src/QualityProfilesPage.jsx`
- `frontend/admin-app/src/ScanMatchSettingsPage.jsx`
- `frontend/admin-app/src/StockPicker.jsx`
- `frontend/admin-app/src/StoragePage.jsx`
- `frontend/admin-app/src/SupportInboxPage.jsx`
- `frontend/admin-app/src/SystemResetPanel.jsx`
- `frontend/admin-app/src/SystemResetPanel.test.jsx`
- `frontend/admin-app/src/UsersPage.jsx`
- `frontend/admin-app/src/ops.css`
- `frontend/admin-app/src/pages.jsx`
- `frontend/admin-app/src/statusLanguage.test.js`
- `frontend/admin-app/src/useAdminShellFrame.js`

**frontend/member-app** (56)

- `frontend/member-app/src/DiscoverApp.jsx`
- `frontend/member-app/src/FavoritesApp.jsx`
- `frontend/member-app/src/FilterBar.test.jsx`
- `frontend/member-app/src/api/discoverPins.js`
- `frontend/member-app/src/buttonLanguage.test.js`
- `frontend/member-app/src/chrome/AccountModal.jsx`
- `frontend/member-app/src/chrome/ContextBar.jsx`
- `frontend/member-app/src/chrome/SideRail.jsx`
- `frontend/member-app/src/chrome/TileSizeControl.css`
- `frontend/member-app/src/chrome/TopBar.jsx`
- `frontend/member-app/src/chrome/iconVisibility.test.js`
- `frontend/member-app/src/chrome/navConfig.js`
- `frontend/member-app/src/components/AddToCollection.css`
- `frontend/member-app/src/components/AddToCollection.jsx`
- `frontend/member-app/src/components/ChatPanel.jsx`
- `frontend/member-app/src/components/DiscoverRowSettings.css`
- `frontend/member-app/src/components/DiscoverRowSettings.jsx`
- `frontend/member-app/src/components/DiscoverShelf.css`
- `frontend/member-app/src/components/DiscoverShelf.jsx`
- `frontend/member-app/src/components/FilterBar.jsx`
- `frontend/member-app/src/components/GameCard.jsx`
- `frontend/member-app/src/components/NewsCard.css`
- `frontend/member-app/src/components/PageStatus.css`
- `frontend/member-app/src/components/PcCheatsPanel.jsx`
- `frontend/member-app/src/components/SocialCompanionDock.jsx`
- `frontend/member-app/src/components/libraryFilters.css`
- `frontend/member-app/src/components/useRowScroll.js`
- `frontend/member-app/src/pages/CalendarPage.css`
- `frontend/member-app/src/pages/CalendarPage.jsx`
- `frontend/member-app/src/pages/CalendarPage.test.jsx`
- `frontend/member-app/src/pages/CollectionDetailPage.jsx`
- `frontend/member-app/src/pages/Collections.css`
- `frontend/member-app/src/pages/CollectionsPage.jsx`
- `frontend/member-app/src/pages/CollectionsPage.test.jsx`
- `frontend/member-app/src/pages/DiscoverRowPage.jsx`
- `frontend/member-app/src/pages/DownloadsPage.jsx`
- `frontend/member-app/src/pages/DownloadsPage.test.jsx`
- `frontend/member-app/src/pages/GameDetailsPage.css`
- `frontend/member-app/src/pages/GameDetailsPage.jsx`
- `frontend/member-app/src/pages/GameDetailsPage.test.jsx`
- `frontend/member-app/src/pages/MemberProfilePage.jsx`
- `frontend/member-app/src/pages/MorePage.css`
- `frontend/member-app/src/pages/NewsPage.jsx`
- `frontend/member-app/src/pages/NewsPage.test.jsx`
- `frontend/member-app/src/pages/NotificationsPage.jsx`
- `frontend/member-app/src/pages/OwnershipPage.jsx`
- `frontend/member-app/src/pages/OwnershipPage.test.jsx`
- `frontend/member-app/src/pages/PlaytimePage.jsx`
- `frontend/member-app/src/pages/PlaytimePage.test.jsx`
- `frontend/member-app/src/pages/TrailersPage.css`
- `frontend/member-app/src/pages/TrailersPage.jsx`
- `frontend/member-app/src/pages/UpdatesPage.jsx`
- `frontend/member-app/src/pages/UpdatesPage.test.jsx`
- `frontend/member-app/src/pages/VrPage.jsx`
- `frontend/member-app/src/pages/WishlistPage.jsx`
- `frontend/member-app/src/pages/WishlistPage.test.jsx`

**scripts** (1)

- `scripts/css-token-lint.baseline.json`

**templates** (6)

- `oneirodex/templates/admin/admin_discovery_sections.html`
- `oneirodex/templates/partials/rail.html`
- `oneirodex/templates/settings/modal_preferences.html`
- `oneirodex/templates/settings/settings_profile_edit.html`
- `oneirodex/templates/settings/settings_profile_view.html`
- `oneirodex/templates/site/styleguide.html`

**tests** (5)

- `tests/test_emulator_bios_discovery.py`
- `tests/test_emulator_bios_upload.py`
- `tests/test_preset_avatars.py`
- `tests/test_scan_queue.py`
- `tests/test_system_reset.py`

**theme assets** (13)

- `oneirodex/setup/default_theme/avatars/arcade.svg`
- `oneirodex/setup/default_theme/avatars/cartridge.svg`
- `oneirodex/setup/default_theme/avatars/controller.svg`
- `oneirodex/setup/default_theme/avatars/default.svg`
- `oneirodex/setup/default_theme/avatars/disc.svg`
- `oneirodex/setup/default_theme/avatars/dpad.svg`
- `oneirodex/setup/default_theme/avatars/joystick.svg`
- `oneirodex/setup/default_theme/css/games/library_browser.css`
- `oneirodex/setup/default_theme/css/od-appbar.css`
- `oneirodex/setup/default_theme/css/od-density.css`
- `oneirodex/setup/default_theme/css/od-primitives.css`
- `oneirodex/setup/default_theme/css/od-tokens.css`
- `oneirodex/setup/default_theme/css/modal-components.css`

## Security / legal audit — 100 files

**backend** (20)

- `.env.example`
- `.github/workflows/ci-tests.yml`
- `.gitignore`
- `README.md`
- `asgi.py`
- `config.py`
- `oneirodex/__init__.py`
- `oneirodex/init_data.py`
- `oneirodex/platform.py`
- `oneirodex/routes_login.py`
- `oneirodex/utils/api_response.py`
- `oneirodex/utils/api_tokens.py`
- `oneirodex/utils/arr_connectors.py`
- `oneirodex/utils/auth.py`
- `oneirodex/utils/challenge_solver.py`
- `oneirodex/utils/functions.py`
- `oneirodex/utils/http_retry.py`
- `oneirodex/utils/http_safe.py`
- `oneirodex/utils/security.py`
- `oneirodex/utils/security_headers.py`

**clients/desktop** (4)

- `clients/desktop/src/app.ts`
- `clients/desktop/src/assists.ts`
- `clients/desktop/src/html.test.ts`
- `clients/desktop/src/html.ts`

**docs** (4)

- `docs/README.md`
- `docs/admin/troubleshooting.md`
- local strategy notes (`security-legal-playbook.md`, that commit)
- local strategy notes (`security.md`, that commit)

**frontend/member-app** (3)

- `frontend/member-app/src/main.jsx`
- `frontend/member-app/src/pages/HelpPage.css`
- `frontend/member-app/src/pages/HelpPage.jsx`

**lockfiles** (2)

- `frontend/admin-app/package-lock.json`
- `frontend/member-app/package-lock.json`

**scripts** (2)

- `scripts/api_envelope_lint.baseline.json`
- `scripts/fetch-vendor-licenses.sh`

**tests** (6)

- `tests/test_auth_hardening.py`
- `tests/test_image_upload_hardening.py`
- `tests/test_legal_surface.py`
- `tests/test_security_headers.py`
- `tests/test_ssrf_hardening.py`
- `tests/test_vendor_licensing.py`

**vendored / webretro** (59)

_59 files — mechanical, not worth line review._
