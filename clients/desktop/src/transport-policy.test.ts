import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  checkDownloadRedirectUrl,
  checkModSourceUrl,
  checkServerUrl,
  hasAcceptableDnsLabels,
  isPrivateOrLoopbackHost,
  savedServerUrlProblem,
} from './transport-policy.js'

// The Rust twin is `validate_server_base_url` in src-tauri/src/lib.rs. Both test
// suites read their URLs and verdicts from the one file below, so a rule changed
// on one side only fails a test instead of drifting.
interface UrlCase {
  url: string
  ok: boolean
  why?: string
}

const fixture = JSON.parse(
  readFileSync(new URL('../fixtures/server-urls.json', import.meta.url), 'utf-8'),
) as { cases: UrlCase[] }

const cases = fixture.cases
const isHttp = (url: string) => /^http:/i.test(url)
const isHttps = (url: string) => /^https:/i.test(url)
// Padded URLs only make sense for checkServerUrl; the mod-source tests append a path.
const unpadded = (c: UrlCase) => c.url === c.url.trim()

const allowedHttp = cases.filter((c) => c.ok && isHttp(c.url) && unpadded(c)).map((c) => c.url)
const refusedHttp = cases.filter((c) => !c.ok && isHttp(c.url) && unpadded(c)).map((c) => c.url)

describe('checkServerUrl', () => {
  it('gives the verdict the shared fixture records, for every URL in it', () => {
    // Same file, same verdicts as the Rust `validate_server_base_url` test.
    expect(cases.length).toBeGreaterThan(50)
    for (const { url, ok } of cases) {
      const result = checkServerUrl(url)
      expect(result.ok, url).toBe(ok)
      if (!result.ok) {
        // Whatever the reason, the message points at the fix.
        expect(result.message, url).toMatch(/https:\/\//)
      }
    }
  })

  it('accepts https:// for any host that parses, unchanged', () => {
    const accepted = cases.filter((c) => c.ok && isHttps(c.url))
    expect(accepted.length).toBeGreaterThan(3)
    for (const { url } of accepted) {
      expect(checkServerUrl(url).ok, url).toBe(true)
    }
  })

  it('accepts http:// for loopback and private LAN hosts', () => {
    for (const url of allowedHttp) {
      expect(checkServerUrl(url).ok, url).toBe(true)
    }
  })

  it('refuses http:// for every other host and says to use https', () => {
    for (const url of refusedHttp) {
      const result = checkServerUrl(url)
      expect(result.ok, url).toBe(false)
      expect(result.ok === false && result.message, url).toMatch(/https:\/\//)
    }
  })

  it('names the refused host and the token in the message', () => {
    const result = checkServerUrl('http://games.example.com/app')
    expect(result).toEqual({
      ok: false,
      message: expect.stringMatching(/games\.example\.com.*API token/s),
    })
  })

  it('refuses a blank URL (Rust treats blank as "clear the saved URL", so it is not in the fixture)', () => {
    for (const url of ['', '   ']) {
      expect(checkServerUrl(url).ok, JSON.stringify(url)).toBe(false)
    }
  })

  it('does not take a domain name that only reads like an address for the address', () => {
    // WHATWG keeps `127.0.0.1..` a domain (one trailing dot would fold to the
    // address); Rust's url crate does the same, so the dotted-quad rule must not
    // strip dots first. The refusal is the generic https hint, not "invalid URL".
    for (const url of ['http://127.0.0.1../', 'http://192.168.1.1../', 'http://10.0.0.1..:5006']) {
      const result = checkServerUrl(url)
      expect(result.ok, url).toBe(false)
      expect(result.ok === false && result.message, url).toMatch(/API token/)
    }
    for (const url of ['http://127.0.0.1./', 'http://10.0.0.1./']) {
      expect(checkServerUrl(url).ok, url).toBe(true)
    }
    expect(isPrivateOrLoopbackHost('127.0.0.1..')).toBe(false)
    expect(isPrivateOrLoopbackHost('127.0.0.1')).toBe(true)
  })

  it('refuses a host with invalid punycode the way the url crate does, for https too', () => {
    for (const url of [
      'http://xn--nas-.lan/',
      'https://xn--nas-.lan/',
      'http://nas.xn--nas-.local/',
    ]) {
      const result = checkServerUrl(url)
      expect(result, url).toEqual({
        ok: false,
        message: expect.stringMatching(/not a valid URL.*https:\/\//s),
      })
    }
    expect(checkServerUrl('http://xn--mnchen-3ya.lan/').ok).toBe(true)
  })

  it('trims surrounding whitespace', () => {
    expect(checkServerUrl('  https://games.example.com  ').ok).toBe(true)
    expect(checkServerUrl('  http://games.example.com  ').ok).toBe(false)
  })
})

describe('checkModSourceUrl', () => {
  it('applies the same rule to admin-supplied mod source URLs', () => {
    expect(checkModSourceUrl('https://cdn.example.com/hd.zip').ok).toBe(true)
    for (const url of allowedHttp) {
      expect(checkModSourceUrl(`${url.replace(/\/$/, '')}/hd.zip`).ok, url).toBe(true)
    }
    for (const url of refusedHttp) {
      const result = checkModSourceUrl(`${url.replace(/\/$/, '')}/hd.zip`)
      expect(result.ok, url).toBe(false)
      expect(result.ok === false && result.message, url).toMatch(/https:\/\//)
    }
    for (const url of [
      'ftp://cdn.example.com/x.zip',
      'file:///C:/x.zip',
      'cdn.example/x.zip',
      '',
    ]) {
      expect(checkModSourceUrl(url).ok, url).toBe(false)
    }
  })

  it('refuses an invalid-punycode host, which the url crate would refuse too', () => {
    expect(checkModSourceUrl('https://xn--nas-.example.com/hd.zip').ok).toBe(false)
    expect(checkDownloadRedirectUrl('https://xn--nas-.example.com/game.zip').ok).toBe(false)
    expect(checkModSourceUrl('https://xn--mnchen-3ya.example.com/hd.zip').ok).toBe(true)
  })
})

describe('isPrivateOrLoopbackHost', () => {
  it('takes URL.hostname forms, brackets included for IPv6', () => {
    expect(isPrivateOrLoopbackHost('localhost')).toBe(true)
    expect(isPrivateOrLoopbackHost('[::1]')).toBe(true)
    expect(isPrivateOrLoopbackHost('[::2]')).toBe(false)
    expect(isPrivateOrLoopbackHost('192.168.0.1')).toBe(true)
    expect(isPrivateOrLoopbackHost('192.168.0.256')).toBe(false)
    expect(isPrivateOrLoopbackHost('example.com')).toBe(false)
    expect(isPrivateOrLoopbackHost('')).toBe(false)
    expect(isPrivateOrLoopbackHost('.')).toBe(false)
    expect(isPrivateOrLoopbackHost('[not-an-address]')).toBe(false)
  })

  it('takes the router suffixes and the Tailscale range as local', () => {
    for (const host of [
      'tower.lan',
      'nas.home.arpa',
      'nas.internal',
      'nas.localdomain',
      'nas.local',
      '100.64.0.0',
      '100.127.255.255',
    ]) {
      expect(isPrivateOrLoopbackHost(host), host).toBe(true)
    }
    for (const host of [
      'lan',
      'example.lan.com',
      '.lan',
      '.internal',
      '100.63.0.1',
      '100.128.0.1',
    ]) {
      // A bare `lan` is a dotless name, so it is local for that reason alone.
      expect(isPrivateOrLoopbackHost(host), host).toBe(host === 'lan')
    }
  })
})

describe('hasAcceptableDnsLabels', () => {
  it('passes ordinary names, valid punycode and IP literals', () => {
    for (const host of [
      'example.com',
      'nas',
      'nas.local',
      '127.0.0.1',
      '[::1]',
      'xn--mnchen-3ya.lan',
      'XN--MNCHEN-3YA.lan',
      'xn--e1afmkfd.lan',
      'a.xn--fiq228c.local',
    ]) {
      expect(hasAcceptableDnsLabels(host), host).toBe(true)
    }
  })

  it('fails an xn-- label that is not punycode, decodes to ASCII or to nothing', () => {
    for (const host of [
      'xn--nas-.lan', // "nas" is ASCII: it should not have been encoded
      'xn--a-.lan',
      'xn--nas.lan', // not valid punycode
      'xn--.lan', // nothing after the prefix
      'xn--zzzzzzzzzzzzzzzzzzzzzzzzzz.lan', // overflows
      'xn--nas!.lan', // a character punycode has no digit for
      'xn--mnchen-3y.lan', // runs out of digits
      'nas.xn--nas-.local',
    ]) {
      expect(hasAcceptableDnsLabels(host), host).toBe(false)
    }
  })
})

describe('savedServerUrlProblem', () => {
  it('is null for nothing saved and for a URL that is still allowed', () => {
    expect(savedServerUrlProblem('')).toBeNull()
    expect(savedServerUrlProblem('   ')).toBeNull()
    expect(savedServerUrlProblem('https://games.example.com')).toBeNull()
    expect(savedServerUrlProblem('http://tower.lan:5006')).toBeNull()
    expect(savedServerUrlProblem('http://100.101.102.103:5006')).toBeNull()
  })

  it('explains a saved URL that the policy now refuses', () => {
    // What the thin client shows on start-up, instead of sitting idle.
    expect(savedServerUrlProblem('http://games.example.com')).toMatch(
      /Refusing http:\/\/ for games\.example\.com.*API token/s,
    )
    expect(savedServerUrlProblem('ftp://games.example.com')).toMatch(/https:\/\//)
  })
})

describe('checkDownloadRedirectUrl', () => {
  it('accepts an https hop and an http hop on the local network', () => {
    for (const url of [
      'https://cdn.example.com/game.zip',
      'http://192.168.1.5:5006/download_zip/7',
      'http://tower.lan/file.zip',
      'http://100.100.100.100/file.zip',
    ]) {
      expect(checkDownloadRedirectUrl(url).ok, url).toBe(true)
    }
  })

  it('refuses a plain http hop on a public host and says an archive could be tampered with', () => {
    for (const url of ['http://cdn.example.com/game.zip', 'http://8.8.8.8/x.zip']) {
      const result = checkDownloadRedirectUrl(url)
      expect(result.ok, url).toBe(false)
      expect(result.ok === false && result.message, url).toMatch(/tampered with.*https:\/\//s)
    }
  })

  it('refuses other schemes and junk', () => {
    for (const url of ['ftp://cdn.example.com/x.zip', 'file:///C:/x.zip', '']) {
      expect(checkDownloadRedirectUrl(url).ok, url).toBe(false)
    }
  })
})
