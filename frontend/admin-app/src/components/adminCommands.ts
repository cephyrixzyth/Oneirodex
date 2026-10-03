import { ADMIN_NAV, HUB_LINKS, INTEGRATION_SECTIONS, SETTINGS_GROUPS } from './navConfig'

/**
 * One flat, searchable index of every admin destination (GT-A7).
 *
 * The admin IA is not badly organised — UX-C1..C9 gave it seven sections,
 * grouped settings and per-section hubs. The gap is that none of it is
 * *searchable*: reaching SMTP settings requires knowing it lives under
 * Integrations rather than under Settings, and there are roughly sixty
 * destinations spread across sections, hubs and in-page tabs.
 *
 * Reorganising the menus again would not fix that — no tree puts "SMTP" in the
 * place every operator looks first. Search sidesteps the question entirely, and
 * the member app already proved the pattern with its ⌘K palette.
 *
 * Built entirely from navConfig rather than a parallel list, so a destination
 * added to a hub or a settings group becomes searchable with no extra step and
 * cannot silently fall out of the index.
 */

export interface AdminCommand {
  id: string
  href: string
  label: string
  section: string
  blurb?: string
  keywords: string
}

/** Where a link came from, used as the group heading in the palette. */
const SECTION_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  libraries: 'Libraries & scans',
  settings: 'Settings',
  content: 'Content',
  users: 'Users',
  integrations: 'Integrations',
  system: 'System',
}

/**
 * Extra search terms for destinations whose label does not contain the word an
 * operator would actually type. Without these, searching "email" finds nothing
 * even though SMTP is exactly what was wanted.
 */
const KEYWORDS: Record<string, string> = {
  '/admin/smtp_settings': 'email mail outbound invite reset',
  '/admin/igdb_settings': 'metadata api credentials',
  '/admin/themes': 'colours colors appearance preset skin',
  '/admin/ops': 'health status monitoring glance errors debugging log logs full-log',
  '/admin/new_server_settings': 'threads workers performance',
  '/admin/users': 'accounts members people',
  '/admin/whitelist': 'allowlist signup registration',
  '/admin/invites': 'invitation signup',
  '/admin/reference_sets': 'dat no-intro redump rom completeness',
  '/admin/emulator_profiles': 'webretro bios cores saves nostalgist nes',
  '/admin/remote_play': 'sunshine wolf moonlight streaming',
  '/admin/arr': 'prowlarr jackett qbittorrent torrent indexer acquire',
  '/admin/plugins': 'export esde pegasus connector',
  '/admin/attract_mode_settings': 'idle screensaver trailer',
  '/admin/discovery_sections': 'shelves storefront curated',
  '/admin/statistics': 'stats metrics numbers',
  '/admin/support': 'issues reports inbox tickets',
  '/scan_management': 'scan jobs scanning folders',
  '/admin/storage': 'hardlink disk volume',
}

/** Normalise a href for dedupe: same page, different anchor, is one entry. */
function dedupeKey(href: string): string {
  return href.split('#')[0].split('?')[0]
}

export function buildAdminCommands(): AdminCommand[] {
  const seen = new Set<string>()
  const commands: AdminCommand[] = []

  function push({
    href,
    label,
    section,
    blurb,
  }: {
    href: string
    label: string
    section: string
    blurb?: string
  }) {
    if (!href || !label) return
    // Anchored links into a page already listed are kept only when they carry a
    // distinct label — otherwise the palette fills with near-duplicates.
    const key = `${dedupeKey(href)}::${label.toLowerCase()}`
    if (seen.has(key)) return
    seen.add(key)
    commands.push({
      id: `${href}::${label}`,
      href,
      label,
      section,
      blurb,
      keywords: KEYWORDS[dedupeKey(href)] || '',
    })
  }

  for (const link of ADMIN_NAV) {
    push({ href: link.path, label: link.label, section: 'Sections' })
  }

  for (const group of SETTINGS_GROUPS) {
    for (const item of group.items) {
      push({
        href: item.to,
        label: item.title,
        section: `Settings · ${group.title}`,
        blurb: item.blurb,
      })
    }
  }

  push({ href: '/admin/integrations', label: 'Integrations overview', section: 'Integrations' })
  for (const group of INTEGRATION_SECTIONS) {
    for (const item of group.items) {
      push({
        href: item.to,
        label: item.title,
        section: `Integrations · ${group.title}`,
        blurb: item.blurb,
      })
    }
  }

  for (const [hubId, links] of Object.entries(HUB_LINKS)) {
    const section = SECTION_LABELS[hubId] || hubId
    for (const link of links as { href: string; label: string }[]) {
      push({ href: link.href, label: link.label, section })
    }
  }

  return commands
}

/**
 * Rank commands against a query.
 *
 * Deliberately simple substring scoring rather than fuzzy matching: operators
 * type the name of the thing they want ("smtp", "logs", "themes"), and fuzzy
 * matching mostly buys false positives at this list size. Prefix beats
 * word-start beats substring beats keyword, so "user" puts Users above
 * "Manage users (classic)".
 */
export function scoreCommand(command: AdminCommand, query: string): number {
  const q = query.trim().toLowerCase()
  if (!q) return 0

  const label = command.label.toLowerCase()
  if (label === q) return 100
  if (label.startsWith(q)) return 80
  if (new RegExp(`\\b${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`).test(label)) return 60
  if (label.includes(q)) return 40
  if ((command.blurb || '').toLowerCase().includes(q)) return 20
  if (command.keywords.includes(q)) return 15
  if (command.section.toLowerCase().includes(q)) return 10
  return -1
}

export function filterAdminCommands(commands: AdminCommand[], query: string): AdminCommand[] {
  if (!query.trim()) return commands
  return commands
    .map((command) => ({ command, score: scoreCommand(command, query) }))
    .filter(({ score }) => score >= 0)
    .sort((a, b) => b.score - a.score || a.command.label.localeCompare(b.command.label))
    .map(({ command }) => command)
}
