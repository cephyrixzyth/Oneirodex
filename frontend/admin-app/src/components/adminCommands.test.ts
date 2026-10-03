import { describe, expect, it } from 'vitest'

import {
  buildAdminCommands,
  filterAdminCommands,
  scoreCommand,
  type AdminCommand,
} from './adminCommands'
import { ADMIN_NAV, HUB_LINKS, INTEGRATION_SECTIONS, SETTINGS_GROUPS } from './navConfig'

/**
 * The palette's value depends entirely on being complete (GT-A7).
 *
 * A search box that silently omits a destination is worse than no search box:
 * the operator concludes the page does not exist. These assert the index is
 * derived from navConfig rather than drifting from it.
 */

describe('buildAdminCommands', () => {
  const commands = buildAdminCommands()
  const hrefs = new Set(commands.map((c) => c.href))

  it('indexes every top-nav section', () => {
    for (const link of ADMIN_NAV) {
      expect(hrefs.has(link.path)).toBe(true)
    }
  })

  it('indexes every settings destination', () => {
    for (const group of SETTINGS_GROUPS) {
      for (const item of group.items) {
        expect(hrefs.has(item.to)).toBe(true)
      }
    }
  })

  it('indexes every integration destination', () => {
    for (const group of INTEGRATION_SECTIONS) {
      for (const item of group.items) {
        expect(hrefs.has(item.to)).toBe(true)
      }
    }
  })

  it('indexes every hub link', () => {
    for (const links of Object.values(HUB_LINKS)) {
      for (const link of links) {
        expect(hrefs.has(link.href)).toBe(true)
      }
    }
  })

  it('gives every entry a section heading and a stable id', () => {
    const ids = new Set()
    for (const command of commands) {
      expect(command.section).toBeTruthy()
      expect(command.label).toBeTruthy()
      expect(ids.has(command.id)).toBe(false)
      ids.add(command.id)
    }
  })
})

describe('filterAdminCommands', () => {
  const commands = buildAdminCommands()

  it('returns everything for an empty query', () => {
    expect(filterAdminCommands(commands, '   ')).toHaveLength(commands.length)
  })

  it('finds SMTP by the word an operator actually types', () => {
    // The whole reason KEYWORDS exists: nothing in the label says "email".
    const labels = filterAdminCommands(commands, 'email').map((c) => c.label)
    expect(labels.some((l) => /smtp/i.test(l))).toBe(true)
  })

  it.each([
    ['themes', /theme/i],
    ['logs', /ops|log/i],
    ['invites', /invite/i],
    ['moonlight', /remote play/i],
    ['prowlarr', /arr|acquire/i],
    ['no-intro', /reference set/i],
    ['nostalgist', /emulator/i],
  ])('finds a destination for %s', (query, expected) => {
    const results = filterAdminCommands(commands, query)
    expect(results.length).toBeGreaterThan(0)
    expect(results.some((c) => expected.test(c.label))).toBe(true)
  })

  it('ranks an exact label above a substring match', () => {
    const results = filterAdminCommands(commands, 'users')
    expect(results[0].label).toBe('Users')
  })

  it('returns nothing for a query that matches nothing', () => {
    expect(filterAdminCommands(commands, 'zzzznotathing')).toEqual([])
  })
})

describe('scoreCommand', () => {
  const command: AdminCommand = {
    id: 'smtp',
    href: '/admin/settings#smtp',
    label: 'SMTP',
    section: 'Integrations',
    blurb: 'Outbound mail.',
    keywords: 'email mail',
  }

  it('scores exact above prefix above keyword', () => {
    // scoreCommand reads label / section / blurb / keywords only; id and href are routing.
    expect(scoreCommand(command, 'smtp')).toBeGreaterThan(scoreCommand(command, 'mail'))
    expect(scoreCommand(command, 'email')).toBeGreaterThan(0)
    expect(scoreCommand(command, 'nope')).toBe(-1)
  })
})
