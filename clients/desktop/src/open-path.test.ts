import { readFileSync } from 'node:fs'

import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import {
  isAbsoluteOsPath,
  isDevicePath,
  isNetworkOrDevicePath,
  isRevealAllowedUnderRoots,
  NETWORK_PATH_REFUSED,
  revealPathInOs,
  validateRevealPath,
} from './open-path.js'

describe('open-path validation', () => {
  it('recognises Windows drive, UNC, and Unix absolute shapes (shape only; trust is decided natively)', () => {
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
  // On Windows even probing a network path makes the OS answer an NTLM challenge
  // from whichever host the path names. `open_path` paths come from the server.
  const uncPaths = [
    '\\\\attacker\\x',
    '\\\\attacker\\share\\game',
    '//attacker/x',
    '\\/attacker\\x',
    '/\\attacker/x',
    '  \\\\attacker\\x  ',
  ]
  // Win32 / NT device namespaces: never openable, whatever the user trusts.
  const devicePaths = [
    '\\\\?\\C:\\Windows',
    '\\\\?\\UNC\\attacker\\x',
    '\\\\.\\pipe\\x',
    '\\??\\C:\\Windows',
    '//?/C:/Windows',
    '//./pipe/x',
    '/??/C:/Windows',
    '  \\\\?\\C:\\Windows  ',
  ]

  it('detects network and device paths but not local ones', () => {
    for (const path of [...uncPaths, ...devicePaths]) {
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

  it('tells device paths from plain UNC shares', () => {
    for (const path of devicePaths) {
      expect(isDevicePath(path.trim()), path).toBe(true)
    }
    for (const path of [...uncPaths, 'C:\\Games\\Foo', '/mnt/user/games/Foo']) {
      expect(isDevicePath(path.trim()), path).toBe(false)
    }
  })

  it('validateRevealPath refuses device paths with the network-path message', () => {
    for (const path of devicePaths) {
      expect(validateRevealPath(path), path).toEqual({ ok: false, error: NETWORK_PATH_REFUSED })
    }
    expect(validateRevealPath('Z:\\games\\Foo')).toEqual({ ok: true, path: 'Z:\\games\\Foo' })
  })

  it('validateRevealPath leaves a UNC share to the native command, which owns the trust list', () => {
    expect(validateRevealPath('\\\\nas\\roms\\Game')).toEqual({
      ok: true,
      path: '\\\\nas\\roms\\Game',
    })
    // The other checks still apply to it.
    expect(validateRevealPath('\\\\nas\\roms\\..\\other').ok).toBe(false)
    expect(validateRevealPath('\\\\nas\\roms\\a\0b').ok).toBe(false)
  })

  it('revealPathInOs never calls the native command for a device path, with or without roots', async () => {
    vi.mocked(invoke).mockReset()
    for (const path of devicePaths) {
      expect(await revealPathInOs(path), path).toEqual({ ok: false, error: NETWORK_PATH_REFUSED })
      expect(await revealPathInOs(path, { allowedRoots: ['\\\\attacker\\x'] }), path).toEqual({
        ok: false,
        error: NETWORK_PATH_REFUSED,
      })
    }
    expect(invoke).not.toHaveBeenCalled()
  })

  it('hands a UNC path to the native command and shows its refusal when the share is not trusted', async () => {
    vi.mocked(invoke).mockReset()
    // Tauri rejects with the command's error string, not an Error.
    vi.mocked(invoke).mockRejectedValue(NETWORK_PATH_REFUSED)
    expect(await revealPathInOs('\\\\attacker\\share\\game')).toEqual({
      ok: false,
      error: NETWORK_PATH_REFUSED,
    })
    expect(invoke).toHaveBeenCalledWith('reveal_path_in_os', {
      path: '\\\\attacker\\share\\game',
      select: true,
    })
  })

  it('opens a UNC path when the native side accepted it (its share is trusted)', async () => {
    vi.mocked(invoke).mockReset()
    vi.mocked(invoke).mockResolvedValue({
      path: '\\\\nas\\roms\\Game',
      revealed_as: 'directory',
    })
    expect(await revealPathInOs('\\\\nas\\roms\\Game', { select: false })).toEqual({
      ok: true,
      path: '\\\\nas\\roms\\Game',
      revealed_as: 'directory',
    })
    expect(invoke).toHaveBeenCalledWith('reveal_path_in_os', {
      path: '\\\\nas\\roms\\Game',
      select: false,
    })
  })

  it('still enforces allowed roots for a UNC path before the native command is called', async () => {
    vi.mocked(invoke).mockReset()
    expect(
      await revealPathInOs('\\\\nas\\roms\\Game', { allowedRoots: ['C:\\Oneirodex\\installs'] }),
    ).toEqual({ ok: false, error: 'Path is outside allowed roots' })
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

describe('NETWORK_PATH_REFUSED parity with the native side', () => {
  it('is the very string src-tauri/src/lib.rs refuses a network or device path with', () => {
    // Both only said "keep in step"; this makes a one-sided edit fail instead.
    const rust = readFileSync(new URL('../src-tauri/src/lib.rs', import.meta.url), 'utf-8')
    const match = /const NETWORK_PATH_REFUSED: &str =\s*"((?:[^"\\]|\\.)*)";/.exec(rust)
    expect(match, 'NETWORK_PATH_REFUSED is declared in lib.rs').not.toBeNull()
    // The Rust literal is read as JSON text: the escapes both use (\" and \\) agree.
    expect(JSON.parse(`"${match![1]}"`)).toBe(NETWORK_PATH_REFUSED)
  })

  it('is what a device path is refused with here too', () => {
    for (const path of ['\\\\?\\C:\\Windows', '\\\\.\\pipe\\x', '\\??\\C:\\Windows']) {
      expect(validateRevealPath(path)).toEqual({ ok: false, error: NETWORK_PATH_REFUSED })
    }
  })
})
