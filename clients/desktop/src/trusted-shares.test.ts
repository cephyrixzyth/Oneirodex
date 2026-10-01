import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: vi.fn(() => true) }))

import { invoke } from '@tauri-apps/api/core'
import { isTauriRuntime } from './config-store.js'
import {
  formatTrustedShares,
  loadTrustedShares,
  parseTrustedShares,
  saveTrustedShares,
} from './trusted-shares.js'

describe('trusted network share list text', () => {
  it('reads one share per line and ignores blank lines and padding', () => {
    expect(parseTrustedShares('\\\\nas\\roms\r\n\r\n  \\\\nas\\archive  \n\n')).toEqual([
      '\\\\nas\\roms',
      '\\\\nas\\archive',
    ])
    expect(parseTrustedShares('')).toEqual([])
    expect(parseTrustedShares('  \n \r\n')).toEqual([])
  })

  it('keeps spaces and punctuation inside a share, since a UNC path may contain them', () => {
    expect(parseTrustedShares('\\\\nas\\ROMs and ISOs, 2024; backup')).toEqual([
      '\\\\nas\\ROMs and ISOs, 2024; backup',
    ])
  })

  it('writes the list back one per line', () => {
    expect(formatTrustedShares(['\\\\nas\\roms', '\\\\nas\\archive'])).toBe(
      '\\\\nas\\roms\n\\\\nas\\archive',
    )
    expect(formatTrustedShares([])).toBe('')
  })
})

describe('trusted network share storage', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(isTauriRuntime).mockReturnValue(true)
  })

  it('loads the list from the native side', async () => {
    vi.mocked(invoke).mockResolvedValue(['\\\\nas\\roms'])
    await expect(loadTrustedShares()).resolves.toEqual(['\\\\nas\\roms'])
    expect(invoke).toHaveBeenCalledWith('load_trusted_shares')
  })

  it('saves through the native validator and returns what was stored', async () => {
    vi.mocked(invoke).mockResolvedValue(['\\\\nas\\roms'])
    await expect(saveTrustedShares(['//nas/roms/'])).resolves.toEqual(['\\\\nas\\roms'])
    expect(invoke).toHaveBeenCalledWith('save_trusted_shares', { roots: ['//nas/roms/'] })
  })

  it('surfaces the native validation message as an Error', async () => {
    // Tauri rejects with the command's error string.
    vi.mocked(invoke).mockRejectedValue('C:\\Games is not a network share path.')
    await expect(saveTrustedShares(['C:\\Games'])).rejects.toThrow(
      'C:\\Games is not a network share path.',
    )
  })

  it('does nothing outside the desktop app', async () => {
    vi.mocked(isTauriRuntime).mockReturnValue(false)
    await expect(loadTrustedShares()).resolves.toEqual([])
    await expect(saveTrustedShares(['\\\\nas\\roms'])).resolves.toEqual(['\\\\nas\\roms'])
    expect(invoke).not.toHaveBeenCalled()
  })
})
