import { describe, expect, test } from 'vitest'

import {
  ADMIN_NAV,
  HUB_LINKS,
  INTEGRATION_SECTIONS,
  RAIL_SECTION_MODE,
  SETTINGS_GROUPS,
  railDestinations,
  railSubSections,
  resolveNavSection,
} from './navConfig'

/**
 * Deep links into the Integrations page have to land somewhere (W27-A8).
 *
 * Every `/admin/integrations#<id>` in the nav was dead, in two separate ways,
 * and both failed silently — the browser finds no matching element, stays at
 * the top of the page, and the click looks like it did nothing:
 *
 *   1. The page rendered its only id on the heading, as `int-<id>`, while every
 *      link pointed at bare `#<id>`. That broke all nine at once.
 *   2. Five of the anchors named a provider with no section of its own at all
 *      (`#email`, `#indexers`, `#giantbomb`, `#hltb`, `#steamgriddb`), so they
 *      would still have missed once the prefix was fixed.
 *
 * A dead link is worse than an ugly one: it teaches people the nav is
 * unreliable. Nothing but a test catches this, because a wrong fragment is
 * valid HTML and throws no error.
 */

const INTEGRATIONS = '/admin/integrations#'

function collectHrefs() {
  const found = []

  for (const group of SETTINGS_GROUPS) {
    for (const item of group.items || []) {
      if (item.to) found.push(item.to)
    }
  }

  for (const group of INTEGRATION_SECTIONS) {
    for (const item of group.items) found.push(item.to)
  }

  for (const links of Object.values(HUB_LINKS)) {
    for (const link of links) {
      if (link.href) found.push(link.href)
    }
  }

  return found
}

describe('integrations deep links', () => {
  // The hub renders an element id for every child that points at a fragment.
  const cardIds = new Set(
    INTEGRATION_SECTIONS.flatMap((group) => group.items)
      .map((item) => item.to.split('#')[1])
      .filter(Boolean),
  )
  const anchors = collectHrefs()
    .filter((href) => href.startsWith(INTEGRATIONS))
    .map((href) => href.slice(INTEGRATIONS.length))

  test('the nav actually contains some integrations deep links', () => {
    // Guards the test itself: if the links are renamed, the assertion below
    // would pass over an empty list and prove nothing.
    expect(anchors.length).toBeGreaterThan(0)
  })

  test('every anchor names a row the hub renders', () => {
    const orphans = [...new Set(anchors)].filter((id) => !cardIds.has(id))

    expect(orphans).toEqual([])
  })
})

/**
 * A sub-page must keep its section selected (W27-A5).
 *
 * The rail decided this by prefix-matching each nav item's own path, so a
 * section stayed lit only while you sat on its landing page. Three pages listed
 * in the Libraries rail live under unrelated prefixes, and opening any of them
 * deselected Libraries and collapsed its sub-links — leaving no route back
 * except navigating to Libraries & scans again.
 */
describe('section ownership', () => {
  test.each([
    ['/admin/extensions', 'libraries'],
    ['/admin/art_studio', 'libraries'],
    ['/admin/edit_filters', 'libraries'],
    ['/scan_management', 'libraries'],
    ['/admin/whitelist', 'users'],
    ['/admin/smtp_settings', 'integrations'],
  ])('%s belongs to %s', (pathname, expected) => {
    expect(resolveNavSection(pathname)).toBe(expected)
  })

  test('query strings and fragments do not change ownership', () => {
    expect(resolveNavSection('/scan_management?active_tab=libraries')).toBe('libraries')
    expect(resolveNavSection('/scan_management?active_tab=tools')).toBe('libraries')
    expect(resolveNavSection('/admin/integrations#oidc')).toBe('integrations')
  })

  test('library tools hub link points at the scan-management tools page', () => {
    const hrefs = HUB_LINKS.libraries.map((item) => item.href)
    expect(hrefs).toContain('/scan_management?active_tab=tools')
    expect(hrefs).not.toContain('/admin/library_tools')
  })

  test('every resolved section is a real nav id', () => {
    const navIds = new Set(ADMIN_NAV.map((item) => item.id))
    const resolved = Object.keys(HUB_LINKS)

    // A hub keyed to something the nav does not render would light up nothing,
    // which is the same invisible failure in a different place.
    expect(resolved.filter((id) => !navIds.has(id))).toEqual([])
  })
})

describe('rail destinations vs hub catalogue', () => {
  test('settings and integrations unfold into sub-sections; libraries is a hub', () => {
    expect(RAIL_SECTION_MODE.libraries).toBe('hub')
    expect(RAIL_SECTION_MODE.settings).toBe('groups')
    expect(RAIL_SECTION_MODE.integrations).toBe('groups')
    expect(railDestinations('libraries').length).toBeGreaterThan(0)
    expect(railDestinations('settings')).toEqual([])
    expect(railDestinations('integrations')).toEqual([])
    expect(railSubSections('settings')).toHaveLength(4)
    expect(railSubSections('integrations')).toHaveLength(4)
    expect(railSubSections('libraries')).toEqual([])
  })

  test('hub catalogue owns library sibling pages for section highlight', () => {
    const hrefs = HUB_LINKS.libraries.map((item) => item.href)
    expect(hrefs).toContain('/libraries')
    expect(hrefs).toContain('/admin/extensions')
    expect(hrefs).toContain('/scan_management?active_tab=tools')
  })

  test('content / users / system still expose hub destinations on the rail', () => {
    expect(railDestinations('users').length).toBeGreaterThan(0)
    expect(railDestinations('system').length).toBeGreaterThan(0)
    expect(railDestinations('content').length).toBeGreaterThan(0)
  })

  test('settings landing points at the hub, not a single module form', () => {
    const settings = ADMIN_NAV.find((item) => item.id === 'settings')
    expect(settings!.path).toBe('/admin/settings')
  })
})
