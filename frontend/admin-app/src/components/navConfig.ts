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

/** Settings rows, grouped like the scans page rather than a flat card grid (UX-C9). */
export const SETTINGS_GROUPS = [
  {
    id: 'library',
    title: 'Library & matching',
    items: [
      {
        to: '/admin/new_server_settings',
        title: 'Server settings',
        blurb: 'Scan threads, download batching, site URL.',
      },
      {
        to: '/admin/scan_match',
        title: 'Scan / match policy',
        blurb:
          'Propose-only, dupe/match thresholds, peel profile — soft-degrades if Backend mid-rollout.',
      },
      {
        to: '/admin/reference_sets',
        title: 'ROM reference sets',
        blurb: 'Upload No-Intro/Redump DATs for set completeness.',
      },
      { to: '/admin/quality_profiles', title: 'Quality profiles', blurb: 'Release quality rules.' },
      {
        to: '/admin/storage',
        title: 'Storage',
        blurb: 'Same-volume hardlink preview/apply helpers.',
        statusKey: 'storage',
      },
    ],
  },
  {
    id: 'play',
    title: 'Play & emulation',
    items: [
      {
        to: '/admin/emulator_profiles',
        title: 'Emulators',
        blurb: 'WebRetro cores, BIOS, NES Nostalgist pilot, cloud saves.',
      },
      {
        to: '/admin/remote_play',
        title: 'Remote play',
        blurb: 'BYO Sunshine/Wolf Moonlight host — off by default.',
      },
      {
        to: '/admin/arr',
        title: 'Arr module',
        blurb: 'BYO Prowlarr/Jackett + qBittorrent (no bundled indexers).',
        statusKey: 'arr',
      },
      {
        // Was an "Export packs" card in Integrations, labelled with the bare
        // tool names (GT-B8). "ES-DE export" and "Pegasus" mean nothing unless
        // you already run those launchers, and Integrations is for services
        // Oneirodex talks *to* — this writes a file for another emulator
        // frontend to read, which is emulation, not an integration.
        to: '/admin/plugins',
        title: 'Export to emulator frontends',
        blurb:
          'Write your library as a game list that ES-DE or Pegasus can read, so those launchers show your games. Export only — nothing on disk is changed.',
      },
    ],
  },
  {
    id: 'presentation',
    title: 'Presentation',
    items: [
      {
        to: '/admin/themes',
        title: 'Themes',
        blurb: 'Reset default CSS after deploy. Pick a look in Preferences.',
      },
      {
        to: '/admin/art_studio',
        title: 'Art studio',
        blurb: 'Placeholders + artwork picker / image queue.',
      },
      { to: '/admin/detail_layout', title: 'Detail layout', blurb: 'Game details field layout.' },
      {
        to: '/admin/attract_mode_settings',
        title: 'Attract mode',
        blurb: 'Idle trailer slideshow and filters.',
      },
    ],
  },
  {
    id: 'extend',
    title: 'Extend',
    items: [
      {
        to: '/admin/ai',
        title: 'AI assist',
        blurb: 'AI identification and helpers.',
        statusKey: 'ai',
      },
      { to: '/admin/plugins', title: 'Plugins', blurb: 'Connector / export / emu registry.' },
    ],
  },
]

/** Flat view — kept so existing links/tests that expect one list keep working. */
export const SETTINGS_CARDS = SETTINGS_GROUPS.flatMap((group) => group.items)

/** Grouped Integrations hub cards (React chrome; forms stay Jinja). */
export const INTEGRATION_CARDS = [
  {
    id: 'igdb',
    title: 'IGDB',
    blurb: 'Primary game metadata credentials and sync.',
    href: '/admin/igdb_settings',
    links: [
      { href: '/admin/igdb_settings', label: 'IGDB settings' },
      { href: '/admin/integrations#igdb', label: 'Integrations · IGDB tab' },
    ],
  },
  {
    id: 'artwork',
    title: 'Artwork & secondary metadata',
    blurb: 'SteamGridDB covers, Giant Bomb, HowLongToBeat, Meta/Quest — not IGDB-only.',
    href: '/admin/integrations#artwork',
    links: [
      { href: '/admin/integrations#artwork', label: 'SteamGridDB art' },
      { href: '/admin/integrations#artwork', label: 'Giant Bomb' },
      { href: '/admin/integrations#artwork', label: 'HowLongToBeat' },
      { href: '/admin/integrations#ownership', label: 'Meta / Quest ownership' },
      // Fragment dropped: admin_art_studio.html carries no ids at all, so
      // `#images` was another anchor that silently landed at the top of the
      // page. The page itself is the destination.
      { href: '/admin/art_studio', label: 'Art studio picker' },
    ],
  },
  {
    id: 'smtp',
    title: 'SMTP',
    blurb: 'Outbound mail for invites, resets, and notices.',
    href: '/admin/smtp_settings',
    links: [
      { href: '/admin/smtp_settings', label: 'SMTP settings' },
      { href: '/admin/integrations#smtp', label: 'Integrations · Email tab' },
    ],
  },
  {
    id: 'oidc',
    title: 'OIDC',
    blurb: 'Optional SSO (Authentik). Leave off for home-only installs.',
    href: '/admin/integrations#oidc',
    links: [{ href: '/admin/integrations#oidc', label: 'OIDC / SSO tab' }],
  },
  {
    id: 'livekit',
    title: 'LiveKit',
    blurb: 'Household voice rooms — enable under Features + LIVEKIT_* secrets.',
    href: '/admin/features',
    links: [
      { href: '/admin/features', label: 'Features (LiveKit toggle)' },
      { href: '/admin/ops', label: 'Ops voice pulse' },
    ],
  },
  {
    id: 'community',
    title: 'Community chat',
    blurb: 'Optional BYO Stoat/Matrix deep-link — not Discord webhooks.',
    href: '/admin/integrations#community',
    links: [
      { href: '/admin/integrations#community', label: 'Community tab' },
      { href: '/admin/chat_emoji', label: 'Custom chat emoji' },
    ],
  },
  {
    id: 'acquire',
    title: 'Acquire / Arr',
    blurb: 'Native Torznab registry + optional Prowlarr/Jackett/qBit hubs.',
    href: '/admin/arr',
    links: [
      { href: '/admin/arr', label: 'Arr module' },
      { href: '/admin/integrations#acquire', label: 'Integrations · Indexers' },
    ],
  },
  {
    id: 'ownership',
    title: 'Ownership registers',
    blurb:
      'Register-only store links: each member’s connection state, last sync result and repair.',
    href: '/admin/ownership',
    links: [
      { href: '/admin/ownership', label: 'Store connections' },
      { href: '/admin/integrations#ownership', label: 'Ownership tab' },
    ],
  },
  {
    id: 'remote_play',
    title: 'Remote play',
    blurb: 'BYO Sunshine/Wolf for Moonlight — enable under Features + host URL.',
    href: '/admin/remote_play',
    links: [
      { href: '/admin/remote_play', label: 'Remote play settings' },
      { href: '/admin/features', label: 'Features toggle' },
    ],
  },
  {
    id: 'support',
    title: 'Support',
    blurb: 'Member issue inbox and optional GitHub sync.',
    href: '/admin/support',
    links: [{ href: '/admin/support', label: 'Support inbox' }],
  },
]

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
  settings: 'landing',
  integrations: 'landing',
  content: 'hub',
  users: 'hub',
  system: 'hub',
} as const

/**
 * A section's rail destinations — empty when the section is landing-only.
 * @param {string} sectionId
 */
export function railDestinations(sectionId: string) {
  const mode = RAIL_SECTION_MODE[sectionId as keyof typeof RAIL_SECTION_MODE] || 'hub'
  if (mode === 'landing') return []
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
    { href: '/scan_management?active_tab=image_queue', label: 'Image queue' },
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
  integrations: [
    { href: '/admin/integrations', label: 'Integrations hub' },
    { href: '/admin/smtp_settings', label: 'SMTP' },
    { href: '/admin/igdb_settings', label: 'IGDB metadata' },
    { href: '/admin/integrations#oidc', label: 'OIDC / SSO' },
    { href: '/admin/features', label: 'LiveKit (Features)' },
    { href: '/admin/support', label: 'Support inbox' },
    { href: '/admin/integrations#artwork', label: 'SteamGridDB art' },
    { href: '/admin/integrations#artwork', label: 'Giant Bomb' },
    { href: '/admin/integrations#artwork', label: 'HowLongToBeat' },
    { href: '/admin/integrations#ownership', label: 'Meta / Quest' },
    { href: '/admin/integrations#ownership', label: 'Ownership registers' },
    { href: '/admin/integrations#community', label: 'Community chat' },
    { href: '/admin/arr', label: 'Acquire / Arr' },
    // ES-DE / Pegasus exports left Integrations with GT-B8 — they write a file
    // for another emulator frontend to read, so they live under Play &
    // emulation. Two raw /api/export links in a nav list were also downloads
    // masquerading as destinations.
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
