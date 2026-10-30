import { forwardRef, type AnchorHTMLAttributes } from 'react'
import { Link, useInRouterContext } from 'react-router-dom'

type AdminLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { to: string }

const ADMIN_EXACT_PATHS = new Set([
  '/admin',
  '/admin/dashboard',
  '/admin/support',
  '/admin/help',
  '/admin/whitelist',
  '/admin/invites',
  '/admin/manage_invites',
  '/admin/plugins',
  '/admin/extensions',
  '/admin/settings',
  '/admin/themes',
  '/admin/themes/readme',
  '/admin/art_studio',
  '/admin/images',
  '/admin/remote_play',
  '/admin/quality_profiles',
  '/admin/storage',
  '/admin/smtp_settings',
  '/admin/attract_mode_settings',
  '/admin/igdb_settings',
  '/admin/chat_emoji',
  '/admin/features',
  '/admin/reference_sets',
  '/admin/scan_match',
  '/admin/users',
  '/admin/system/danger',
  '/admin/ops',
  '/admin/announcements',
  '/admin/integrations',
  '/admin/ownership',
  '/admin/edit_filters',
  '/admin/library/add',
  '/admin/library',
  '/admin/filters',
  '/admin/detail_layout',
  '/admin/ai',
  '/admin/arr',
  '/admin/emulator_profiles',
  '/admin/new_server_settings',
  '/admin/newsletter',
  '/admin/integrations/oidc',
  '/admin/manage-downloads',
  '/admin/statistics',
  '/admin/scan-jobs',
  '/admin/scan-controls',
  '/admin/unmatched',
  '/admin/discovery_sections',
  '/libraries',
  '/scan_management',
  '/scan_manual_folder',
  '/add_game_manual',
])

export function isAdminAppPath(to: string): boolean {
  const pathname = to.split(/[?#]/, 1)[0]
  return (
    ADMIN_EXACT_PATHS.has(pathname) ||
    pathname.startsWith('/admin/themes/') ||
    pathname.startsWith('/admin/users/') ||
    pathname.startsWith('/admin/system/danger/') ||
    pathname.startsWith('/admin/ops/') ||
    pathname.startsWith('/admin/library/') ||
    pathname.startsWith('/admin/filters/') ||
    pathname.startsWith('/admin/newsletter/') ||
    pathname.startsWith('/libraries/') ||
    pathname.startsWith('/scan_management/') ||
    pathname.startsWith('/game_edit/') ||
    pathname.startsWith('/edit_game_images/')
  )
}

/**
 * Same-app admin routes use client-side navigation. Cross-app paths keep native
 * document navigation, and isolated component renders still have usable links.
 */
export const AdminLink = forwardRef<HTMLAnchorElement, AdminLinkProps>(function AdminLink(
  { to, ...props },
  ref,
) {
  const inRouter = useInRouterContext()
  return inRouter && isAdminAppPath(to) ? (
    <Link to={to} {...props} ref={ref} />
  ) : (
    <a href={to} {...props} ref={ref} />
  )
})
