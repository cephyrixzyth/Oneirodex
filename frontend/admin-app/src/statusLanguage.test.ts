/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/* PR-4 moved the flat `src/` into pages/ components/ api/ hooks/. This guard
 * still lives at `src/` root, so it walks the subtree to keep covering every
 * `.jsx`. Baseline rows stay keyed by basename — they are unique across the
 * admin `src/` tree. */

/**
 * One status language for admin (GT-B33). Hand-written status/alert roles are
 * kept out of pages and widgets so the shared PageStatus component owns their
 * live-region semantics and visual treatment. PageStatus supports rich live
 * content as well as loading, error and empty messages.
 */

const HERE = dirname(fileURLToPath(import.meta.url))

/* basename -> absolute path, gathered recursively from `src/`. PR-4 (e) renamed
 * the components to `.tsx`; JSX still lives in a `.jsx`/`.tsx` file, so match
 * both and key the baseline by `.tsx`. */
function collectJsx(dir: any, acc: any) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules') continue
      collectJsx(full, acc)
    } else if (
      (entry.name.endsWith('.jsx') || entry.name.endsWith('.tsx')) &&
      !entry.name.includes('.test.')
    ) {
      acc.set(entry.name, full)
    }
  }
  return acc
}
const JSX_BY_NAME = collectJsx(HERE, new Map())

/* All admin source now uses the shared PageStatus implementation for
 * announcements. Keep this empty baseline to prevent local role regressions. */
const STATUS_BASELINE: Record<string, number> = {}

/**
 * PageStatus is the shared implementation — it is meant to carry these roles.
 * It moved into `@oneirodex/ui` in wave B1.2, so there is no local file to
 * exempt any more; the set is kept as a guard in case a copy is ever re-added.
 */
const EXEMPT = new Set(['PageStatus.jsx', 'PageStatus.tsx'])

const STATUS_ROLE = /role="(?:status|alert)"/g

function sourceFiles() {
  return [...JSX_BY_NAME.keys()].filter((name) => !EXEMPT.has(name))
}

function countStatusRoles(name: any) {
  const full = JSX_BY_NAME.get(name) ?? join(HERE, name)
  const source = readFileSync(full, 'utf8')
  return (source.match(STATUS_ROLE) || []).length
}

describe('admin status language', () => {
  it('never exceeds the recorded per-file baseline', () => {
    const regressions = []
    for (const name of sourceFiles()) {
      const count = countStatusRoles(name)
      const allowed = (STATUS_BASELINE as Record<string, number>)[name] ?? 0
      if (count > allowed) {
        regressions.push(`${name}: ${count} hand-rolled status sites, baseline ${allowed}`)
      }
    }
    expect(
      regressions,
      `Use PageStatus from '@oneirodex/ui' instead of a new role="status"/role="alert" block.\n` +
        regressions.join('\n'),
    ).toEqual([])
  })

  it('has no baseline row that has outlived its violations', () => {
    // A stale row would silently permit a regression back up to its number,
    // which is how a ratchet quietly stops ratcheting.
    const stale = []
    for (const [name, allowed] of Object.entries(STATUS_BASELINE)) {
      const count = countStatusRoles(name)
      if (count < allowed) {
        stale.push(`${name}: baseline ${allowed}, actually ${count} — lower it`)
      }
    }
    expect(stale).toEqual([])
  })

  it('exposes the shared component the baseline is meant to drive toward', async () => {
    const module = await import('@oneirodex/ui')
    expect(typeof module.PageStatus).toBe('function')
    expect(typeof module.resolveErrorMessage).toBe('function')
    expect(typeof module.resolveErrorDetail).toBe('function')
  })
})
