/**
 * Pure pathname -> admin section-kind classifier.
 *
 * Split out of pages.jsx in PR-4 (b). It is consumed by AdminTopNav for
 * "which section am I in" (SECTION_HOME) and, in (c), by the route table.
 * It renders nothing and must stay free of React / JSX imports.
 *
 * '/admin/help' is the dedicated operator guide. Member help remains available
 * at its own route and is linked from the admin guide where useful.
 */
export function resolveAdminPage(pathname: string): string {
  if (pathname === '/admin/dashboard' || pathname === '/admin' || pathname === '/admin/') {
    return 'dashboard'
  }
  if (pathname === '/admin/support') return 'support'
  if (pathname === '/admin/invites') return 'invites'
  if (pathname === '/admin/plugins') return 'plugins'
  if (pathname === '/admin/extensions') return 'extensions'
  if (pathname === '/admin/features' || pathname === '/admin/chat_emoji') return 'integrations'
  if (
    pathname.startsWith('/libraries') ||
    pathname.startsWith('/admin/library') ||
    pathname.includes('library_tools') ||
    pathname.includes('/admin/filters')
  ) {
    return 'libraries'
  }
  if (pathname === '/admin/settings') return 'settings'
  if (pathname === '/admin/themes' || pathname.startsWith('/admin/themes/')) return 'themes'
  if (pathname === '/admin/art_studio') return 'art_studio'
  if (pathname === '/admin/images') return 'images'
  if (pathname === '/admin/remote_play') return 'remote_play'
  if (pathname === '/admin/quality_profiles') return 'quality_profiles'
  if (pathname === '/admin/storage') return 'storage'
  if (pathname === '/admin/scan_match') return 'scan_match'
  if (pathname === '/admin/help') return 'help'
  // Scans live under the merged "Libraries & scans" nav item (UX-C2), so these
  // paths must highlight 'libraries' — 'scans' is no longer a top-nav id.
  // 'image_queue' dropped from this list with the standalone page (W27-C6) —
  // it is a tab of /scan_management now, which the prefix below already covers,
  // and it only ever appears as a query parameter rather than in the pathname.
  if (
    pathname.startsWith('/scan_management') ||
    pathname.includes('game_identify') ||
    pathname.includes('game_edit')
  ) {
    return 'libraries'
  }
  if (
    pathname.startsWith('/admin/users') ||
    pathname.includes('manage_invites') ||
    pathname.includes('whitelist')
  ) {
    return 'users'
  }
  if (pathname.includes('integration') || pathname.includes('smtp') || pathname.includes('igdb')) {
    return 'integrations'
  }
  if (pathname.includes('new_server_settings')) {
    return 'settings-section'
  }
  if (pathname.includes('/admin/system/danger') || pathname.includes('system_reset')) {
    return 'system-danger'
  }
  if (
    pathname.includes('/admin/ops') ||
    pathname.includes('server_') ||
    pathname.includes('statistics') ||
    pathname.includes('manage-downloads')
    // 'new_server_info' dropped with the page (W27-D1) — resolving a path that
    // no longer routes anywhere is how a stale id outlives its page.
  ) {
    return 'system'
  }
  if (
    pathname.includes('discovery') ||
    pathname.includes('newsletter') ||
    pathname.includes('attract')
  ) {
    return 'content'
  }
  if (pathname.includes('announcement')) {
    return 'announcements'
  }
  if (
    pathname.includes('settings') ||
    pathname.includes('emulator') ||
    pathname.includes('detail_layout') ||
    pathname.includes('/admin/ai') ||
    pathname.includes('/admin/storage') ||
    pathname.includes('/admin/arr') ||
    pathname.includes('new_server_settings')
  ) {
    return 'settings-section'
  }
  return 'generic'
}
