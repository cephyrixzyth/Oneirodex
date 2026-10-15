/// <reference types="node" />
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

/**
 * Guard: every api/ wrapper reports a failed response through the one helper.
 *
 * Each wrapper used to hand-roll this, and they had drifted into two broken
 * tiers — one that never read the body (so `PageStatus` showed a member
 * "announcements 500") and one that read `error` but dropped `error_code` and
 * `status`. Both are invisible in review because each file looks reasonable on
 * its own; only the set is wrong. So the set is what gets asserted.
 *
 * This counts rather than names, like the admin brand-mark guard: a new wrapper
 * is free to appear, it just has to use the helper.
 */

const API_DIR = path.dirname(fileURLToPath(import.meta.url))

/**
 * Failure paths that legitimately do not read an envelope. Keep this list
 * short and reasoned — it is the escape hatch that could hollow out the guard.
 */
const EXEMPT = new Map([
  ['discover.ts', 'guards a missing JSON body after an ok response, not a failed one'],
])

function sourceFiles() {
  return fs
    .readdirSync(API_DIR)
    .filter((name) => name.endsWith('.ts') && !name.endsWith('.test.ts') && !name.endsWith('.d.ts'))
    .filter((name) => name !== 'envelopeError.ts' && name !== 'csrf.ts')
}

describe('CSRF handling lives in one module', () => {
  /**
   * Fifteen modules used to carry their own copy, in nine variants differing in
   * how many fallbacks they tried. The short ones sent an empty token on any
   * page rendering the input field instead of the meta tag, and the 403 that
   * came back said nothing about why. Redefining it locally is the regression.
   */
  test.each(sourceFiles())('%s does not redefine the token lookup', (name) => {
    const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
    const local = source.match(/^(?:function|const)\s+(getCsrfToken|csrfToken|csrfHeaders)\b/gm)
    expect(
      local ?? [],
      `import { csrfHeaders } from '@oneirodex/ui' instead — the shared chain is the ` +
        `superset, so a local copy can only be narrower`,
    ).toEqual([])
  })

  test('nothing hand-builds the X-CSRFToken header', () => {
    const offenders = sourceFiles().filter((name) => {
      const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
      return /'X-CSRFToken'\s*:/.test(source)
    })
    expect(offenders, 'use csrfHeaders(extra) so window.CSRFUtils is honoured').toEqual([])
  })
})

/**
 * The api/ tests above are not enough. CSRF copies grew back in pages,
 * components, and hooks (NotificationsPage went meta-only again) because the
 * ratchet never looked there. This walk is the whole member SPA source tree.
 * Every file must be zero — there is no baseline map to absorb a new copy.
 */
const SRC_ROOT = path.resolve(API_DIR, '..')

function walkSrcFiles(dir = SRC_ROOT, acc: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      walkSrcFiles(full, acc)
      continue
    }
    if (!/\.(js|jsx|ts|tsx)$/.test(entry.name)) continue
    // Production modules only. Tests may set a meta tag or assert the header
    // object csrfHeaders() produced; those are not local lookup copies.
    if (/\.test\.(js|jsx|ts|tsx)$/.test(entry.name)) continue
    if (entry.name.endsWith('.d.ts')) continue
    const rel = path.relative(SRC_ROOT, full).split(path.sep).join('/')
    if (
      rel === 'api/csrf.js' ||
      rel === 'api/csrf.ts' ||
      rel === 'api/envelopeError.js' ||
      rel === 'api/envelopeError.ts'
    )
      continue
    acc.push(rel)
  }
  return acc
}

const LOCAL_CSRF_DEF =
  /^\s*(?:export\s+)?(?:async\s+)?(?:function|const)\s+(getCsrfToken|csrfToken|csrfHeaders)\b/
const META_CSRF = /meta\[name=["']csrf-token["']\]/
const HEADER_CSRF = /['"]X-CSRFToken['"]\s*:/

function csrfOffendersIn(source: any) {
  return source.split(/\r?\n/).flatMap((line: any, index: any) => {
    if (LOCAL_CSRF_DEF.test(line) || META_CSRF.test(line) || HEADER_CSRF.test(line)) {
      return [`${index + 1}: ${line.trim()}`]
    }
    return []
  })
}

describe('CSRF handling lives in one module across src/', () => {
  const files = walkSrcFiles().sort()

  test('the walk finds production modules', () => {
    expect(files.length).toBeGreaterThan(20)
    expect(files).not.toContain('api/csrf.js')
    expect(files).not.toContain('api/csrf.ts')
    expect(files).not.toContain('api/envelopeError.js')
    expect(files).not.toContain('api/envelopeError.ts')
  })

  test.each(files)('%s has no local CSRF lookup', (rel) => {
    const source = fs.readFileSync(path.join(SRC_ROOT, rel), 'utf8')
    expect(
      csrfOffendersIn(source),
      `import { csrfHeaders } from '@oneirodex/ui' instead — the shared chain is the ` +
        `superset, so a local copy can only be narrower`,
    ).toEqual([])
  })
})

describe('api wrappers report failures through the shared envelope helper', () => {
  test.each(sourceFiles())('%s', (name) => {
    const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
    const lines = source.split('\n')

    const offenders: any[] = []
    lines.forEach((line, index) => {
      if (!/throw new Error\(/.test(line)) {
        return
      }
      // Only failure-branch throws matter. A DOM guard or a content-type check
      // is not a response and has no envelope to report.
      const preceding = lines.slice(Math.max(0, index - 3), index).join('\n')
      if (/if \(!\w+\.ok\)/.test(preceding)) {
        offenders.push(`${name}:${index + 1} ${line.trim()}`)
      }
    })

    if (EXEMPT.has(name)) {
      return
    }
    expect(
      offenders,
      `use \`throw await errorFromResponse(response, '<label>')\` so the backend's ` +
        `sentence and its error_code reach PageStatus`,
    ).toEqual([])
  })

  test.each(sourceFiles())('%s does not rebuild the message from data.error', (name) => {
    // The first version of this guard only looked for `throw new Error(` right
    // after an `if (!x.ok)`, which missed the same flattening one level down in
    // a helper — `tokens.js` had `readError()` doing exactly that, and it read
    // as tidy code. What identifies the bug is reaching for `data.error` to
    // build an Error, wherever that happens.
    const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
    const offenders = source
      .split('\n')
      .map((line, index) => ({ line: line.trim(), number: index + 1 }))
      .filter(({ line }) => /new Error\(/.test(line) && /data\??\.\w*error/i.test(line))
      .map(({ line, number }) => `${name}:${number} ${line}`)

    expect(
      offenders,
      'let errorFromResponse() read the body — it keeps status and error_code too',
    ).toEqual([])
  })

  test('every wrapper that reports failures imports the helper', () => {
    const missing = sourceFiles().filter((name) => {
      const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
      if (!/errorFromResponse\(/.test(source)) {
        return false
      }
      // errorFromResponse moved into `@oneirodex/ui` (wave B1.2); it may be
      // imported on its own or alongside csrfHeaders from the same specifier.
      const importsHelper = /import\s*\{[^}]*\berrorFromResponse\b[^}]*\}\s*from\s*'@oneirodex\/ui'/
      return !importsHelper.test(source)
    })
    expect(missing).toEqual([])
  })

  test('a fallback label never embeds the status twice', () => {
    // The helpers append ` ${status}` themselves, so a label that already has it
    // renders "cheats list 500 500". Checking only `errorFromResponse(` missed
    // this when the label was passed through a module's own wrapper —
    // `cheats.js` did that at four sites. Interpolating the status into a
    // template literal is the tell, so match that instead of a callee name.
    const offenders: any[] = []
    for (const name of sourceFiles()) {
      const source = fs.readFileSync(path.join(API_DIR, name), 'utf8')
      source.split('\n').forEach((line, index) => {
        if (/`[^`]*\$\{\s*\w*\.?status\s*\}[^`]*`/.test(line)) {
          offenders.push(`${name}:${index + 1} ${line.trim()}`)
        }
      })
    }
    expect(offenders, 'pass a bare label — errorFromResponse/errorFromBody add the status').toEqual(
      [],
    )
  })
})
