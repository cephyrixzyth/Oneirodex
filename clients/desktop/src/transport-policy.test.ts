import { describe, expect, it } from 'vitest'

import { checkModSourceUrl, checkServerUrl, isPrivateOrLoopbackHost } from './transport-policy.js'

// The Rust twin is `validate_server_base_url` in src-tauri/src/lib.rs; the host
// lists below mirror its tests so the two stay in step.

const allowedHttp = [
  'http://localhost:5000',
  'http://127.0.0.1:5000',
  'http://127.255.0.3',
  'http://[::1]:5000',
  'http://10.1.2.3',
  'http://172.16.0.1',
  'http://172.31.255.254',
  'http://192.168.1.50:8080',
  'http://169.254.10.10',
  'http://[fd12:3456:789a::1]',
  'http://[fc00::1]',
  'http://[fe80::1]',
  'http://[::ffff:192.168.1.5]',
  'http://nas.local',
  'http://NAS.LOCAL:8080/app',
  'http://nas.local./',
  'http://nas',
  'http://nas:5000',
  // WHATWG host parsing folds these to 127.0.0.1 / 192.168.0.1.
  'http://0x7f.1/',
  'http://2130706433/',
  'http://0300.0250.0.1/',
  // The host is 192.168.1.1; `evil.com` is only userinfo.
  'http://evil.com@192.168.1.1/',
]

const refusedHttp = [
  'http://games.example.com',
  'http://games.example.com:5000/app',
  'http://8.8.8.8',
  'http://172.15.0.1',
  'http://172.32.0.1',
  'http://192.169.1.1',
  'http://11.0.0.1',
  'http://0.0.0.0',
  'http://100.64.0.1',
  'http://[2001:db8::1]',
  'http://[::ffff:8.8.8.8]',
  'http://[fec0::1]',
  // Looks local, is a public name.
  'http://192.168.1.1.evil.com',
  'http://10.0.0.1.nip.io',
  'http://localhost.evil.com',
  'http://nas.local.evil.com',
  'http://.local',
  // Hex-encoded public address.
  'http://0x08080808/',
  // The host is evil.com; 192.168.1.1 is only userinfo.
  'http://192.168.1.1@evil.com/',
]

describe('checkServerUrl', () => {
  it('accepts https:// for any host, unchanged', () => {
    for (const url of [
      'https://games.example.com',
      'https://games.example.com:8443/prefix',
      'https://8.8.8.8',
      'HTTPS://Games.Example.Com',
      'https://nas.local',
    ]) {
      const result = checkServerUrl(url)
      expect(result.ok, url).toBe(true)
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

  it('refuses other schemes and things that are not URLs', () => {
    for (const url of [
      'ftp://games.example.com',
      'file:///etc/passwd',
      'ws://localhost:5000',
      'javascript:alert(1)',
      'games.example.com',
      'localhost:5000',
      'https://',
      '//games.example.com',
      '',
      '   ',
    ]) {
      expect(checkServerUrl(url).ok, JSON.stringify(url)).toBe(false)
    }
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
})
