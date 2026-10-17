import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AnnouncementsPage } from '../pages/AnnouncementsPage'
import { ArtStudioPage } from '../pages/ArtStudioPage'
import { DashboardPage } from '../pages/DashboardPage'
import { ExtensionsPage } from '../pages/ExtensionsPage'
import { ImagesPage } from '../pages/ImagesPage'
import { IntegrationsPage } from '../pages/IntegrationsPage'
import { WhitelistPage } from '../pages/WhitelistPage'
import { InvitesPage } from '../pages/InvitesPage'
import { LibrariesPage } from '../pages/LibrariesPage'
import { NativeLibrariesPage } from '../pages/NativeLibrariesPage'
import { OpsPage } from '../pages/OpsPage'
import { OwnershipDiagnosticsPage } from '../pages/OwnershipDiagnosticsPage'
import { PluginsPage } from '../pages/PluginsPage'
import { QualityProfilesPage } from '../pages/QualityProfilesPage'
import { RemotePlayPage } from '../pages/RemotePlayPage'
import { ScanMatchSettingsPage } from '../pages/ScanMatchSettingsPage'
import { SettingsPage } from '../pages/SettingsPage'
import { StoragePage } from '../pages/StoragePage'
import { SmtpPage } from '../pages/SmtpPage'
import { AttractModePage } from '../pages/AttractModePage'
import { IgdbSettingsPage } from '../pages/IgdbSettingsPage'
import { ChatEmojiPage } from '../pages/ChatEmojiPage'
import { FeaturesPage } from '../pages/FeaturesPage'
import { ReferenceSetsPage } from '../pages/ReferenceSetsPage'
import { ServerSettingsPage } from '../pages/ServerSettingsPage'
import { NewsletterPage } from '../pages/NewsletterPage'
import { OidcSettingsPage } from '../pages/OidcSettingsPage'
import { DownloadsPage } from '../pages/DownloadsPage'
import { StatisticsPage } from '../pages/StatisticsPage'
import { ScansPage } from '../pages/ScansPage'
import { UnmatchedPage } from '../pages/UnmatchedPage'
import { ManualIdentifyPage } from '../pages/ManualIdentifyPage'
import { EditGameImagesPage } from '../pages/EditGameImagesPage'
import { ScanFiltersPage } from '../pages/ScanFiltersPage'
import { ScanControlsPage } from '../pages/ScanControlsPage'
import { DiscoverySectionsPage } from '../pages/DiscoverySectionsPage'
import { SupportInboxPage } from '../pages/SupportInboxPage'
import { ThemesPage } from '../pages/ThemesPage'
import { ThemeAuthoringPage } from '../pages/ThemeAuthoringPage'
import { SystemDangerPage } from '../pages/SystemDangerPage'
import { UsersPage } from '../pages/UsersPage'
import { HubPage } from './HubPage'
import { DetailLayoutPage } from '../pages/DetailLayoutPage'
import { EmulatorsPage } from '../pages/EmulatorsPage'
import { AiAssistPage } from '../pages/AiAssistPage'
import { ArrPage } from '../pages/ArrPage'
import { AdminHelpPage } from '../pages/AdminHelpPage'
import { LibraryEditorPage } from '../pages/LibraryEditorPage'
import { SETTINGS_CARDS, railDestinations } from './navConfig'

/**
 * Explicit admin route table (PR-4 c).
 *
 * Replaces the single `<Route path="*">` + `resolveAdminPage` → `renderAdminKind`
 * switch that used to live in App.jsx. Every `data-admin-render="spa"` admin
 * template now has a `<Route>` whose element is exactly the page the old switch
 * returned for that pathname — no URL changed, and the page rendered for each
 * path is unchanged:
 *
 *   /admin, /admin/dashboard ............ DashboardPage
 *   /admin/support ..................... SupportInboxPage
 *   /admin/invites .................... InvitesPage
 *   /admin/plugins ................... PluginsPage
 *   /admin/extensions .............. ExtensionsPage
 *   /admin/settings .............. SettingsPage
 *   /admin/themes[/…] .......... ThemesPage  (renders chrome-only today; kept
 *                                             so a future spa template works)
 *   /admin/art_studio ....... ArtStudioPage
 *   /admin/images ......... ImagesPage
 *   /admin/remote_play .. RemotePlayPage
 *   /admin/quality_profiles ... QualityProfilesPage
 *   /admin/storage ........... StoragePage
 *   /admin/scan_match ....... ScanMatchSettingsPage
 *   /admin/users[/…] ..... UsersPage
 *   /admin/system/danger[/…] . SystemDangerPage
 *   /admin/ops[/…] ......... OpsPage
 *   /admin/announcements .... AnnouncementsPage
 *   /admin/integrations .... IntegrationsPage
 *   /libraries[/…], /admin/library[/…], /scan_management[/…], /admin/filters[/…]
 *                          ... LibrariesPage
 *   /admin/detail_layout ......... DetailLayoutPage  (H-D.5 port 1)
 *   /admin/emulator_profiles ..... EmulatorsPage     (H-D.5 port 2)
 *   /admin/ai .................... AiAssistPage
 *   /admin/arr .................. ArrPage
 *   /admin/new_server_settings ... SettingsSectionPage
 *   (anything else) ........ HubPage "Admin"  (the old switch `default`)
 *
 * `resolveAdminPage` is unchanged and still owns "which section is active" for
 * AdminTopNav — its fuzzy `includes()` branches classify legacy Jinja pathnames
 * for the nav highlight only; those pages render chrome-only, so they never
 * needed a route here.
 *
 * Distinct routes give each page a stable element identity, which is what the
 * old `useMemo(…, [kind])` in RoutedAdminPage was for. Prefix families collapse
 * onto one element via a `/*` splat (e.g. every `/scan_management/…` variant is
 * the same `<LibrariesPage />`), so same-section navigation still does not
 * remount.
 */

/**
 * Temporary fallback for settings modules that do not have a React body yet.
 * Keep their destination visible instead of showing a blank panel.
 */
function SettingsSectionPage() {
  const { pathname } = useLocation()
  const card = SETTINGS_CARDS.find((c) => c.to === pathname)
  return (
    <HubPage
      title={card?.title || 'Settings module'}
      lede={card?.blurb || 'Server module settings.'}
      links={card ? [{ href: card.to, label: `Open ${card.title}` }] : []}
    />
  )
}

function ScanManagementRoute() {
  const { search } = useLocation()
  const tab = new URLSearchParams(search).get('active_tab') || 'auto'
  if (tab === 'jobs') return <ScansPage />
  if (tab === 'tools' || tab === 'libraries') return <NativeLibrariesPage />
  if (tab === 'unmatched') return <UnmatchedPage />
  if (tab === 'scan_filters') return <ScanFiltersPage />
  if (tab === 'file_extensions') return <ExtensionsPage />
  if (tab === 'image_queue') return <ImagesPage />
  return <ScanControlsPage />
}

export function AdminRoutes() {
  return (
    <Routes>
      <Route path="/admin" element={<DashboardPage />} />
      <Route path="/admin/dashboard" element={<DashboardPage />} />

      <Route path="/admin/support" element={<SupportInboxPage />} />
      <Route path="/admin/help" element={<AdminHelpPage />} />
      <Route path="/admin/whitelist" element={<WhitelistPage />} />
      <Route path="/admin/invites" element={<InvitesPage />} />
      <Route path="/admin/manage_invites" element={<InvitesPage />} />
      <Route path="/admin/plugins" element={<PluginsPage />} />
      <Route path="/admin/extensions" element={<ExtensionsPage />} />
      <Route path="/admin/settings" element={<SettingsPage />} />
      {/* No data-admin-render="spa" themes template today — App renders chrome
          only for this path, so this element is not reached. Wired so the route
          exists the moment the template flips. */}
      <Route path="/admin/themes" element={<ThemesPage />} />
      <Route path="/admin/themes/readme" element={<ThemeAuthoringPage />} />
      <Route path="/admin/themes/*" element={<ThemesPage />} />
      <Route path="/admin/art_studio" element={<ArtStudioPage />} />
      <Route path="/admin/images" element={<ImagesPage />} />
      <Route path="/admin/remote_play" element={<RemotePlayPage />} />
      <Route path="/admin/quality_profiles" element={<QualityProfilesPage />} />
      <Route path="/admin/storage" element={<StoragePage />} />
      <Route path="/admin/smtp_settings" element={<SmtpPage />} />
      <Route path="/admin/attract_mode_settings" element={<AttractModePage />} />
      <Route path="/admin/igdb_settings" element={<IgdbSettingsPage />} />
      <Route path="/admin/chat_emoji" element={<ChatEmojiPage />} />
      <Route path="/admin/features" element={<FeaturesPage />} />
      <Route path="/admin/reference_sets" element={<ReferenceSetsPage />} />
      <Route path="/admin/scan_match" element={<ScanMatchSettingsPage />} />
      <Route path="/admin/users/*" element={<UsersPage />} />
      <Route path="/admin/system/danger/*" element={<SystemDangerPage />} />
      <Route path="/admin/ops/*" element={<OpsPage />} />
      <Route path="/admin/announcements" element={<AnnouncementsPage />} />
      <Route path="/admin/integrations" element={<IntegrationsPage />} />
      <Route path="/admin/ownership" element={<OwnershipDiagnosticsPage />} />
      <Route path="/admin/edit_filters" element={<ScanFiltersPage />} />

      {/* "Libraries & scans" — the merged nav item (UX-C2). Every legacy path
          the old resolver folded onto 'libraries' renders LibrariesPage. */}
      <Route path="/libraries" element={<NativeLibrariesPage />} />
      <Route path="/admin/library/add" element={<NativeLibrariesPage />} />
      <Route path="/admin/library/edit/:libraryUuid" element={<LibraryEditorPage />} />
      <Route path="/libraries/*" element={<LibrariesPage />} />
      <Route path="/admin/library/*" element={<LibrariesPage />} />
      <Route path="/admin/filters/*" element={<LibrariesPage />} />
      <Route path="/scan_management/*" element={<LibrariesPage />} />
      <Route path="/scan_management" element={<ScanManagementRoute />} />
      <Route
        path="/scan_manual_folder"
        element={<Navigate replace to="/scan_management?active_tab=manual" />}
      />

      {/* Remaining settings modules. */}
      <Route path="/admin/detail_layout" element={<DetailLayoutPage />} />
      <Route path="/admin/ai" element={<AiAssistPage />} />
      <Route path="/admin/arr" element={<ArrPage />} />
      <Route path="/admin/emulator_profiles" element={<EmulatorsPage />} />
      <Route path="/admin/new_server_settings" element={<ServerSettingsPage />} />

      <Route path="/admin/newsletter" element={<NewsletterPage />} />
      <Route path="/admin/newsletter/:newsletterId" element={<NewsletterPage />} />
      <Route path="/admin/integrations/oidc" element={<OidcSettingsPage />} />
      <Route path="/admin/manage-downloads" element={<DownloadsPage />} />
      <Route path="/admin/statistics" element={<StatisticsPage />} />
      <Route path="/admin/scan-jobs" element={<ScansPage />} />
      <Route path="/admin/scan-controls" element={<ScanControlsPage />} />
      <Route path="/add_game_manual" element={<ManualIdentifyPage />} />
      <Route path="/game_edit/:gameUuid" element={<ManualIdentifyPage />} />
      <Route path="/edit_game_images/:gameUuid" element={<EditGameImagesPage />} />
      <Route path="/admin/unmatched" element={<UnmatchedPage />} />
      {/* Discovery shelves, newsletter, announcements, attract mode. */}
      <Route path="/admin/discovery_sections" element={<DiscoverySectionsPage />} />
      <Route
        path="/admin/content/*"
        element={
          <HubPage
            title="Content"
            lede="Discovery shelves, newsletter, announcements, and attract mode."
            links={railDestinations('content')}
          />
        }
      />

      {/* The old switch `default`. */}
      <Route
        path="*"
        element={<HubPage title="Admin" lede="Pick a section from the rail on the left." />}
      />
    </Routes>
  )
}
