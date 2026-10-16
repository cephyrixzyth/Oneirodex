import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { csrfHeaders, getCsrfToken, setCsrfToken } from './csrf.js'

function setBody(html: any) {
  document.body.innerHTML = html
  document.head.innerHTML = ''
}

function setMeta(value: any) {
  document.head.innerHTML = `<meta name="csrf-token" content="${value}">`
}

describe('getCsrfToken fallback chain', () => {
  beforeEach(() => {
    setBody('')
  })

  test('prefers the meta tag', () => {
    setMeta('from-meta')
    document.body.innerHTML = '<input name="csrf_token" value="from-input">'
    expect(getCsrfToken()).toBe('from-meta')
  })

  test('falls back to a form input', () => {
    setBody('<input name="csrf_token" value="from-input">')
    expect(getCsrfToken()).toBe('from-input')
  })

  test('falls back to the #csrf_token element', () => {
    // The chain 6 of the 15 modules were missing — on a page that renders this
    // element rather than the meta tag they sent an empty token and got a 403.
    setBody('<span id="csrf_token">from-element</span>')
    expect(getCsrfToken()).toBe('from-element')
  })

  test('returns an empty string when the page carries no token', () => {
    setBody('')
    expect(getCsrfToken()).toBe('')
  })
})

describe('setCsrfToken', () => {
  test('updates the shared token or creates the standard meta tag', () => {
    setBody('')
    setCsrfToken('bootstrapped')
    expect(getCsrfToken()).toBe('bootstrapped')
    setCsrfToken('refreshed')
    expect(document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')).toBe(
      'refreshed',
    )
  })
})

describe('csrfHeaders', () => {
  afterEach(() => {
    delete window.CSRFUtils
  })

  test('merges the token with the caller headers', () => {
    setMeta('tok')
    expect(csrfHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'X-CSRFToken': 'tok',
      'Content-Type': 'application/json',
    })
  })

  test('defers to window.CSRFUtils when the page provides it', () => {
    const getHeaders = vi.fn(() => ({ 'X-CSRFToken': 'from-utils' }))
    window.CSRFUtils = { getHeaders }
    expect(csrfHeaders({ Accept: 'application/json' })).toEqual({
      'X-CSRFToken': 'from-utils',
    })
    expect(getHeaders).toHaveBeenCalledWith({ Accept: 'application/json' })
  })

  test('works with no arguments', () => {
    setMeta('tok')
    expect(csrfHeaders()).toEqual({ 'X-CSRFToken': 'tok' })
  })
})
