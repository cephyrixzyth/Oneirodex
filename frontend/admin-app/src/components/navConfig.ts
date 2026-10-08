/** Primary admin top nav. */
export const ADMIN_NAV = [
  { id: 'dashboard', path: '/admin/dashboard', label: 'Dashboard' },
  // Libraries and scans are one tabbed page (UX-C2) — two top-nav buttons
  // pointing into the same page was the leftover from before they merged.
  // LHN is the landing only; tab strip stays in the top bar (contextbar).
  { id: 'libraries', path: '/libraries', label: 'Libraries & scans' },
  // Landing is the Settings hub — module forms live on that page, not as a
  // second copy of every row in the rail (confirmed admin IA).
  { id: 'settings', path: '/admin/settings', label: 'Settings' },
  { id: 'content', path: '/admin/discovery_sections', label: 'Content' },
  { id: 'users', path: '/admin/users', label: 'Users' },
  { id: 'integrations', path: '/admin/integrations', label: 'Integrations' },
  { id: 'system', path: '/admin/ops', label: 'System' },
]

export interface SubSectionItem {
  to: string
  title: string
  icon: string
  blurb?: string
  statusKey?: string
}

/**
 * A rail sub-section: one LHN row (with an icon) whose children are buttons in
 * the top bar. Settings and Integrations are both built from this shape.
 */
export interface SubSection {
  id: string
  title: string
  icon: string
  items: SubSectionItem[]
}

/** Settings rows, grouped like the scans page rather than a flat card grid (UX-C9). */
export const SETTINGS_GROUPS: SubSection[] = [
  {
    id: 'library',
    title: 'Library & matching',
    icon: 'matching',
    items: [
      {
        to: '/admin/new_server_settings',
        icon: 'server',
        title: 'Server settings',
        blurb: 'Scan threads, download batching, site URL.',
      },
      {
        to: '/admin/scan_match',
        icon: 'matching',
        title: 'Scan / match policy',
        blurb:
          'Propose-only, dupe/match thresholds, peel profile — soft-degrades if Backend mid-rollout.',
      },
      {
        to: '/admin/reference_sets',
        icon: 'reference',
        title: 'ROM reference sets',
        blurb: 'Upload No-Intro/Redump DATs for set completeness.',
      },
      {
        to: '/admin/quality_profiles',
        icon: 'quality',
        title: 'Quality profiles',
        blurb: 'Release quality rules.',
      },
      {
        to: '/admin/storage',
        icon: 'storage',
        title: 'Storage',
        blurb: 'Same-volume hardlink preview/apply helpers.',
        statusKey: 'storage',
      },
    ],
  },
  {
    id: 'play',
    title: 'Play & emulation',
    icon: 'emulators',
    items: [
      {
        to: '/admin/emulator_profiles',
        icon: 'emulators',
        title: 'Emulators',
        blurb: 'WebRetro cores, BIOS, NES Nostalgist pilot, cloud saves.',
      },
      {
        to: '/admin/remote_play',
        icon: 'remote',
        title: 'Remote play',
        blurb: 'BYO Sunshine/Wolf Moonlight host — off by default.',
      },
    ],
  },
  {
    id: 'presentation',
    title: 'Presentation',
    icon: 'themes',
    items: [
      {
        to: '/admin/themes',
        icon: 'themes',
        title: 'Themes',
        blurb: 'Reset default CSS after deploy. Pick a look in Preferences.',
      },
      {
        to: '/admin/art_studio',
        icon: 'art',
        title: 'Art studio',
        blurb: 'Placeholders + artwork picker / image queue.',
      },
      {
        to: '/admin/detail_layout',
        icon: 'layout',
        title: 'Detail layout',
        blurb: 'Game details field layout.',
      },
      {
        to: '/admin/attract_mode_settings',
        icon: 'attract',
        title: 'Attract mode',
        blurb: 'Idle trailer slideshow and filters.',
      },
    ],
  },
  {
    id: 'extend',
    title: 'Extend',
    icon: 'plugins',
    items: [
      {
        to: '/admin/ai',
        icon: 'ai',
        title: 'AI assist',
        blurb: 'AI identification and helpers.',
        statusKey: 'ai',
      },
      {
        // ES-DE / Pegasus export lives here: it writes a game list another
        // emulator frontend reads, so it is a plugin, not an integration
        // (GT-B8). It used to be a second card pointing at this same page.
        to: '/admin/plugins',
        icon: 'plugins',
        title: 'Plugins & exports',
        blurb:
          'Connector and emulator registry, plus ES-DE / Pegasus game-list export. Export only — nothing on disk is changed.',
      },
    ],
  },
]

/** Flat view — kept so existing links/tests that expect one list keep working. */
export const SETTINGS_CARDS = SETTINGS_GROUPS.flatMap((group) => group.items)

/**
 * Integrations, shaped exactly like Settings: four LHN sub-sections, children
 * as top-bar buttons. Each destination has one home — Arr moved here from
 * Settings (it talks to Prowlarr / qBittorrent), the Support inbox lives under
 * Users, Art studio under Settings → Presentation, Remote play under Settings →
 * Play. The hub page (`/admin/integrations`) is the overview, not a section.
 */
export const INTEGRATION_SECTIONS: SubSection[] = [
  {
    id: 'metadata',
    title: 'Metadata & art',
    icon: 'metadata',
    items: [
      {
        to: '/admin/igdb_settings',
        icon: 'metadata',
        title: 'IGDB',
        blurb: 'Primary game metadata credentials and sync.',
      },
      {
        to: '/admin/integrations#artwork',
        icon: 'art',
        title: 'Artwork & secondary',
        blurb: 'SteamGridDB covers, Giant Bomb, HowLongToBeat.',
      },
      {
        to: '/admin/integrations#retro-achievements-settings',
        icon: 'emulators',
        title: 'RetroAchievements',
        blurb: 'Connect the household account used for achievement sets and member progress.',
      },
    ],
  },
  {
    id: 'stores',
    title: 'Stores & ownership',
    icon: 'stores',
    items: [
      {
        to: '/admin/ownership',
        icon: 'stores',
        title: 'Store connections',
        blurb: 'Each member’s connection state, last sync result and repair.',
      },
      {
        to: '/admin/integrations#ownership',
        icon: 'ownership',
        title: 'Meta / Quest',
        blurb: 'Register-only ownership links.',
      },
    ],
  },
  {
    id: 'messaging',
    title: 'Messaging & identity',
    icon: 'identity',
    items: [
      {
        to: '/admin/smtp_settings',
        icon: 'mail',
        title: 'SMTP',
        blurb: 'Outbound mail for invites, resets and notices.',
      },
      {
        to: '/admin/integrations#oidc',
        icon: 'identity',
        title: 'OIDC / SSO',
        blurb: 'Optional SSO (Authentik). Leave off for home-only installs.',
      },
      {
        to: '/admin/integrations#community',
        icon: 'chat',
        title: 'Community chat',
        blurb: 'Optional BYO Stoat/Matrix deep-link.',
      },
      { to: '/admin/chat_emoji', icon: 'favorites', title: 'Chat emoji', blurb: 'Custom emoji.' },
      {
        to: '/admin/features',
        icon: 'voice',
        title: 'LiveKit voice',
        blurb: 'Household voice rooms — enable under Features.',
      },
    ],
  },
  {
    id: 'acquire',
    title: 'Acquisition',
    icon: 'acquire',
    items: [
      {
        to: '/admin/arr',
        icon: 'acquire',
        title: 'Arr module',
        blurb: 'BYO Prowlarr/Jackett + qBittorrent (no bundled indexers).',
        statusKey: 'arr',
      },
      {
        to: '/admin/integrations#acquire',
        icon: 'scan',
        title: 'Indexers',
        blurb: 'Native Torznab registry.',
      },
    ],
  },
]

/** Sections whose LHN entry unfolds into icon sub-sections (children live in the top bar). */
export const SUBSECTIONS: Record<string, SubSection[]> = {
  settings: SETTINGS_GROUPS,
  integrations: INTEGRATION_SECTIONS,
}

/**
 * Which sub-section (and child) a location belongs to, or null on the hub
 * pages themselves. Children that share a page (Integrations tabs) are told
 * apart by the URL fragment; without one the overview page owns the path.
 */
export function findSubSection(pathname: string, hash = '') {
  const path = (pathname || '/').split('?')[0].replace(/\/+$/, '') || '/'
  const frag = hash && hash !== '#' ? (hash.startsWith('#') ? hash : `#${hash}`) : ''
  for (const [sectionId, subs] of Object.entries(SUBSECTIONS)) {
    for (const sub of subs) {
      const matches = sub.items.filter((item) => item.to.split('#')[0] === path)
      if (!matches.length) continue
      const exact = matches.find(
        (item) => (item.to.split('#')[1] ? `#${item.to.split('#')[1]}` : '') === frag,
      )
      const item = exact || (matches.every((m) => m.to.includes('#')) ? null : matches[0])
      if (item) return { sectionId, sub, item, siblings: subs }
    }
  }
  return null
}

/**
 * Links that are *actions on a page*, not destinations (GT-B7).
 *
 * The rail lists a section's hub links when that section is active. Several of
 * these are not places — "Add one library", the two "Add many" anchors — they
 * are things you do once you are on the Libraries page. Listing them as
 * destinations made the rail long enough to break its own rhythm, and put verbs
 * in a column of nouns.
 *
 * They stay in HUB_LINKS because the pages still render them; the rail filters
 * them out with railDestinations().
 */
export const PAGE_ACTION_HREFS = new Set([
  '/admin/library/add',
  '/libraries#propose-leaf',
  '/libraries#import-leaf',
])

/**
 * Which top-level section a pathname belongs to (W27-A5).
 *
 * The rail used to decide this by comparing the pathname against each nav
 * item's own `path`, which meant a section only stayed selected while you were
 * on its landing page. Several pages listed *in* a section's rail links live
 * under a different prefix — `/admin/extensions`, `/admin/art_studio` and
 * `/admin/edit_filters` are all Libraries links — so clicking one deselected
 * Libraries, collapsed its sub-links, and left you with no way back except
 * navigating to Libraries & scans again.
 *
 * Derived from HUB_LINKS rather than a second hand-written table: a page listed
 * in a section's rail links *is* part of that section, by definition. A new
 * link cannot forget to register itself here.
 *
 * @param {string} pathname
 * @returns {string|null} an ADMIN_NAV id, or null when nothing owns the path
 */
export function resolveNavSection(pathname: string): string | null {
  // Fragment and query stripped from the input as well as the href: a router
  // pathname will not carry either, but callers pass raw hrefs too and a
  // section that depended on which of the two forms it was handed would be a
  // subtle way to reintroduce exactly this bug.
  const path = (pathname || '/').split('#')[0].split('?')[0].replace(/\/+$/, '') || '/'

  const owns = (href: string | undefined) => {
    // Fragments and query strings are the same page for ownership purposes.
    const base = (href || '').split('#')[0].split('?')[0].replace(/\/+$/, '')
    if (!base || base === '/') return false
    return path === base || path.startsWith(`${base}/`)
  }

  // Hub links first — they are the more specific statement of membership.
  for (const [sectionId, links] of Object.entries(HUB_LINKS)) {
    if (links.some((link) => owns(link.href))) return sectionId
  }

  for (const item of ADMIN_NAV) {
    if (owns(item.path)) return item.id
  }

  return null
}

/**
 * How the left rail presents each ADMIN_NAV section.
 *
 * `landing` — section row is the only LHN control (click goes to ADMIN_NAV.path).
 *   Used when the page already owns tabs/actions in the top bar, or when the
 *   hub page is the catalogue of destinations (Settings / Integrations).
 * `hub` — fold open to show HUB_LINKS destinations (minus page actions).
 *
 * HUB_LINKS stays complete for section ownership + command palette; the rail
 * deliberately shows less so LHN and THN stop restating each other.
 */
export const RAIL_SECTION_MODE = {
  dashboard: 'landing',
  // Libraries siblings are separate pages again — show them under the fold.
  libraries: 'hub',
  // Unfold into icon sub-sections; their children are top-bar buttons.
  settings: 'groups',
  integrations: 'groups',
  content: 'hub',
  users: 'hub',
  system: 'hub',
} as const

/**
 * A section's rail destinations — empty when the section is landing-only.
 * @param {string} sectionId
 */
export function railSubSections(sectionId: string): SubSection[] {
  const mode = RAIL_SECTION_MODE[sectionId as keyof typeof RAIL_SECTION_MODE]
  return mode === 'groups' ? SUBSECTIONS[sectionId] || [] : []
}

export function railDestinations(sectionId: string) {
  const mode = RAIL_SECTION_MODE[sectionId as keyof typeof RAIL_SECTION_MODE] || 'hub'
  if (mode === 'landing' || mode === 'groups') return []
  const links = HUB_LINKS[sectionId as keyof typeof HUB_LINKS] || []
  return links.filter((link) => !PAGE_ACTION_HREFS.has(link.href))
}

export const HUB_LINKS = {
  // Libraries & scans sibling pages (no longer one Bootstrap tab document).
  libraries: [
    { href: '/libraries', label: 'Libraries' },
    // Auto + Manual share one LHN row; mode switch lives in the THN.
    { href: '/scan_management?active_tab=auto', label: 'Scan' },
    { href: '/scan_management?active_tab=jobs', label: 'Scan Jobs' },
    { href: '/scan_management?active_tab=tools', label: 'Library tools' },
    { href: '/scan_management?active_tab=unmatched', label: 'Unmatched' },
    { href: '/scan_management?active_tab=scan_filters', label: 'Filters' },
    { href: '/admin/edit_filters', label: 'Release filters' },
    { href: '/admin/extensions', label: 'Extensions' },
    { href: '/admin/images', label: 'Image queue' },
    { href: '/admin/art_studio', label: 'Art & images' },
    // Page actions — filtered out of the rail by PAGE_ACTION_HREFS.
    { href: '/admin/library/add', label: 'Add one library' },
    { href: '/libraries#propose-leaf', label: 'Add many — scan a folder for libraries' },
    { href: '/libraries#import-leaf', label: 'Add many — import CSV / JSON' },
  ],
  // Ownership + command-palette catalogue for Settings. Built from
  // SETTINGS_GROUPS so a new card cannot forget section membership. The rail
  // is landing-only — the hub page lists these rows.
  settings: [
    { href: '/admin/settings', label: 'All settings' },
    ...SETTINGS_GROUPS.flatMap((group) =>
      group.items.map((item) => ({ href: item.to, label: item.title })),
    ),
  ],
  users: [
    { href: '/admin/users', label: 'Users' },
    { href: '/admin/invites', label: 'Invites' },
    { href: '/admin/whitelist', label: 'Whitelist' },
    { href: '/admin/support', label: 'Support inbox' },
    { href: '/admin/manage_invites', label: 'Invite quotas' },
  ],
  // Built from INTEGRATION_SECTIONS so a new child cannot forget membership.
  integrations: [
    { href: '/admin/integrations', label: 'Integrations hub' },
    ...INTEGRATION_SECTIONS.flatMap((sub) =>
      sub.items.map((item) => ({ href: item.to, label: item.title })),
    ),
  ],
  system: [
    // Server status is no longer its own section (UX-C1) — its signals live on
    // the dashboard, so the standalone page is not offered as a destination.
    // "Server info" retired (W27-D1) — Ops is the one pane. It showed the same
    // host facts from a second template, and its System / Database / Logs /
    // Configuration panels all render on Ops now.
    // Server logs retired into Ops Full-log popup (UID-034) — deep links
    // /admin/server_logs and /admin/system_logs redirect to /admin/ops?open=full-log.
    { href: '/admin/ops', label: 'Ops glance' },
    { href: '/admin/statistics', label: 'Statistics' },
    { href: '/admin/manage-downloads', label: 'Downloads admin' },
    { href: '/admin/system/danger', label: 'Danger zone' },
    { href: '/admin/help', label: 'Admin help' },
  ],
  content: [
    { href: '/admin/discovery_sections', label: 'Discovery sections' },
    { href: '/admin/newsletter', label: 'Newsletter' },
    { href: '/admin/announcements', label: 'Announcements' },
    { href: '/admin/attract_mode_settings', label: 'Attract mode' },
  ],
}

/** Glyph for a hub sub-link, keyed by its label (Settings / Integrations carry their own). */
const HUB_ICONS: Record<string, string> = {
  Libraries: 'libraries',
  Scan: 'scan',
  'Scan Jobs': 'activity',
  'Library tools': 'tools',
  Unmatched: 'unmatched',
  Filters: 'filter',
  'Release filters': 'filter',
  Extensions: 'plugins',
  'Image queue': 'art',
  'Art & images': 'art',
  Users: 'users',
  Invites: 'mail',
  Whitelist: 'admin',
  'Support inbox': 'chat',
  'Invite quotas': 'quality',
  'Discovery sections': 'discover',
  Newsletter: 'news',
  Announcements: 'notifications',
  'Attract mode': 'attract',
  'Ops glance': 'activity',
  Statistics: 'chart',
  'Downloads admin': 'downloads',
  'Danger zone': 'danger',
  'Admin help': 'help',
}

export function hubIcon(label: string): string {
  return HUB_ICONS[label] || 'systems'
}
