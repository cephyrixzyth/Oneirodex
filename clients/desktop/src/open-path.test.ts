import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import {
  isAbsoluteOsPath,
  isNetworkOrDevicePath,
  isRevealAllowedUnderRoots,
  NETWORK_PATH_REFUSED,
  revealPathInOs,
  validateRevealPath,
} from './open-path.js'

describe('open-path validation', () => {
  it('recognises Windows drive, UNC, and Unix absolute shapes (UNC is refused by validateRevealPath)', () => {
    expect(isAbsoluteOsPath('C:\\Games\\Foo')).toBe(true)
    expect(isAbsoluteOsPath('Z:/games/bar')).toBe(true)
    expect(isAbsoluteOsPath('\\\\nas\\share\\games')).toBe(true)
    expect(isAbsoluteOsPath('/mnt/user/games/Foo')).toBe(true)
  })

  it('rejects relative and empty paths', () => {
    expect(isAbsoluteOsPath('')).toBe(false)
    expect(isAbsoluteOsPath('games\\Foo')).toBe(false)
    expect(isAbsoluteOsPath('./Foo')).toBe(false)
    expect(validateRevealPath('  ')).toEqual({ ok: false, error: 'Path is required' })
    expect(validateRevealPath('relative\\path').ok).toBe(false)
  })

  it('rejects control characters and .. segments', () => {
    expect(validateRevealPath('C:\\Games\\Foo\0bar').ok).toBe(false)
    expect(validateRevealPath('C:\\Games\\..\\Windows').ok).toBe(false)
    expect(validateRevealPath('C:\\Games\\Foo\\..\\Bar').ok).toBe(false)
  })

  it('enforces optional allowed roots for local installs', () => {
    const root = 'C:\\Oneirodex\\installs'
    expect(isRevealAllowedUnderRoots(`${root}\\game-1`, [root])).toBe(true)
    expect(isRevealAllowedUnderRoots('C:\\Windows\\System32', [root])).toBe(false)
    expect(isRevealAllowedUnderRoots('C:\\Windows\\System32', [])).toBe(true)
  })
})

describe('UNC and device paths', () => {
  // On Windows even probing one of these makes the OS answer an NTLM challenge
  // from whichever host the path names. `open_path` paths come from the server.
  const refused = [
    '\\\\attacker\\x',
    '\\\\attacker\\share\\game',
    '//attacker/x',
    '\\/attacker\\x',
    '/\\attacker/x',
    '\\\\?\\C:\\Windows',
    '\\\\?\\UNC\\attacker\\x',
    '\\\\.\\pipe\\x',
    '\\??\\C:\\Windows',
    '//?/C:/Windows',
    '  \\\\attacker\\x  ',
  ]

  it('detects network and device paths but not local ones', () => {
    for (const path of refused) {
      expect(isNetworkOrDevicePath(path.trim()), path).toBe(true)
    }
    for (const path of [
      'C:\\Games\\Foo',
      'Z:/games/bar',
      '/mnt/user/games/Foo',
      '/home/me/games',
      '\\single\\leading',
      '/a//b',
    ]) {
      expect(isNetworkOrDevicePath(path), path).toBe(false)
    }
  })

  it('validateRevealPath refuses them with the network-path message', () => {
    for (const path of refused) {
      expect(validateRevealPath(path), path).toEqual({ ok: false, error: NETWORK_PATH_REFUSED })
    }
    expect(validateRevealPath('Z:\\games\\Foo')).toEqual({ ok: true, path: 'Z:\\games\\Foo' })
  })

  it('revealPathInOs never calls the native command for them, with or without roots', async () => {
    vi.mocked(invoke).mockReset()
    for (const path of refused) {
      expect(await revealPathInOs(path), path).toEqual({ ok: false, error: NETWORK_PATH_REFUSED })
      expect(await revealPathInOs(path, { allowedRoots: ['\\\\attacker\\x'] }), path).toEqual({
        ok: false,
        error: NETWORK_PATH_REFUSED,
      })
    }
    expect(invoke).not.toHaveBeenCalled()
  })
})

describe('revealPathInOs', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
  })

  it('invokes Tauri reveal with validated absolute path', async () => {
    vi.mocked(invoke).mockResolvedValue({
      path: 'C:\\Oneirodex\\installs\\game-1',
      revealed_as: 'directory',
    })
    const result = await revealPathInOs('C:\\Oneirodex\\installs\\game-1')
    expect(result).toEqual({
      ok: true,
      path: 'C:\\Oneirodex\\installs\\game-1',
      revealed_as: 'directory',
    })
    expect(invoke).toHaveBeenCalledWith('reveal_path_in_os', {
      path: 'C:\\Oneirodex\\installs\\game-1',
      select: true,
    })
  })

  it('returns validation errors without invoking Tauri', async () => {
    const result = await revealPathInOs('../evil')
    expect(result.ok).toBe(false)
    expect(invoke).not.toHaveBeenCalled()
  })

  it('blocks paths outside allowedRoots', async () => {
    const result = await revealPathInOs('C:\\Windows', {
      allowedRoots: ['C:\\Oneirodex\\installs'],
    })
    expect(result).toEqual({ ok: false, error: 'Path is outside allowed roots' })
    expect(invoke).not.toHaveBeenCalled()
  })
})
