/**
 * Phase 3 of the security/legal playbook (S5).
 *
 * An assist overlay module (since removed, it was never wired into the app)
 * interpolated server-supplied `pack.title` / `pack.policy` straight into
 * innerHTML while every other site in this client escaped. In a Tauri webview
 * that is script execution with IPC reach.
 *
 * Testing the fixed function alone would not stop the next one, and this client
 * has no DOM in its test environment anyway — so the guard is a source scan, in
 * the same shape as the member app's buttonLanguage / envelopeContract tests:
 * every interpolation into an innerHTML template must be escaped at the point
 * of use, or be a fragment this file names as already-escaped.
 */
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { escapeHtml } from './html.js'

const SRC_DIR = dirname(fileURLToPath(import.meta.url))

/**
 * Fragments assembled *from* escaped parts earlier in the same function, so
 * escaping them again would double-encode. Each must stay that way — if one
 * starts carrying raw server data, it belongs out of this list, not in it.
 */
const PRE_ESCAPED = new Set([
  'rows', // app.ts renderLifecyclePanel — every field escaped in the map
  'cards', // app.ts renderLibrary — same
  'offlineBanner', // app.ts — static markup chosen by a boolean
])

const INNER_HTML_TEMPLATE = /innerHTML\s*=\s*`((?:[^`\\]|\\.)*)`/gs
const INTERPOLATION = /\$\{([^}]*)\}/g

interface Site {
  file: string
  expression: string
}

function interpolationSites(): Site[] {
  const found: Site[] = []
  for (const file of readdirSync(SRC_DIR)) {
    if (!file.endsWith('.ts') || file.endsWith('.test.ts') || file.endsWith('.d.ts')) {
      continue
    }
    const source = readFileSync(join(SRC_DIR, file), 'utf8')
    for (const template of source.matchAll(INNER_HTML_TEMPLATE)) {
      for (const interpolation of template[1].matchAll(INTERPOLATION)) {
        found.push({ file, expression: interpolation[1].trim() })
      }
    }
  }
  return found
}

function isSafe(expression: string): boolean {
  return expression.includes('escapeHtml(') || PRE_ESCAPED.has(expression)
}

describe('escapeHtml', () => {
  it('escapes every character that can break out of markup', () => {
    expect(escapeHtml('<&>"\'')).toBe('&lt;&amp;&gt;&quot;&#39;')
  })

  it('escapes the ampersand first, so entities are not double-encoded wrong', () => {
    expect(escapeHtml('&lt;')).toBe('&amp;lt;')
  })

  it('neutralises an image-onerror payload', () => {
    expect(escapeHtml('<img src=x onerror="alert(1)">')).not.toContain('<img')
  })

  it('survives null and undefined', () => {
    expect(escapeHtml(undefined as unknown as string)).toBe('')
    expect(escapeHtml(null as unknown as string)).toBe('')
  })

  it('leaves ordinary game titles alone', () => {
    expect(escapeHtml('Chrono Trigger')).toBe('Chrono Trigger')
  })
})

describe('innerHTML interpolation contract', () => {
  it('finds the sites it is meant to be guarding', () => {
    // A scan that silently matches nothing would pass forever.
    expect(interpolationSites().length).toBeGreaterThan(0)
  })

  it('escapes every interpolation into an innerHTML template', () => {
    const unsafe = interpolationSites()
      .filter((site) => !isSafe(site.expression))
      .map((site) => `${site.file}: \${${site.expression}}`)

    expect(unsafe).toEqual([])
  })

  it('keeps one shared implementation rather than per-file copies', () => {
    const copies = readdirSync(SRC_DIR).filter((file) => {
      if (file === 'html.ts' || !file.endsWith('.ts') || file.endsWith('.test.ts')) {
        return false
      }
      return readFileSync(join(SRC_DIR, file), 'utf8').includes('function escapeHtml')
    })

    expect(copies).toEqual([])
  })
})
