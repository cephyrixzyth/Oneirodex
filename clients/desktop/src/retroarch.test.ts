import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

import { invoke } from '@tauri-apps/api/core'
import {
  HANDHELD_PRESETS,
  buildAiServiceSetupNote,
  buildRetroArchArgs,
  fetchCheatText,
  inputFamilyArgs,
  resolveCheatStagePath,
  safeCheatFilename,
  shouldStageRetroArchCheat,
  stageCheatFile,
  wineLaunchEnv,
} from './retroarch.js'

describe('retroarch companion helpers', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(invoke).mockImplementation(async (command: string, args?: unknown) => {
      const typed = args as { subdir?: string } | undefined
      if (command === 'get_app_subdir') {
        return typed?.subdir === 'cheats' ? '/appdata/cheats' : '/appdata/other'
      }
      return undefined
    })
  })

  it('builds -L core rom args', () => {
    expect(
      buildRetroArchArgs({
        core: '/cores/dolphin_libretro.so',
        system: 'NGC',
        romPath: '/roms/game.iso',
      }),
    ).toEqual(['-L', '/cores/dolphin_libretro.so', '/roms/game.iso'])
  })

  it('builds AI service setup note when enabled', () => {
    expect(buildAiServiceSetupNote({ enabled: false })).toBeNull()
    expect(
      buildAiServiceSetupNote({
        enabled: true,
        targetLang: 'en',
        serviceUrl: 'http://127.0.0.1:4404',
      }),
    ).toMatch(/127\.0\.0\.1:4404/)
  })

  it('exposes handheld presets', () => {
    expect(HANDHELD_PRESETS.some((p) => p.id === 'steamdeck')).toBe(true)
  })

  it('builds wine prefix env', () => {
    expect(wineLaunchEnv({ prefixPath: '/home/u/.wine-gt', dxvk: true })).toMatchObject({
      WINEPREFIX: '/home/u/.wine-gt',
      DXVK_HUD: '0',
    })
  })

  it('sanitizes cheat filenames', () => {
    expect(safeCheatFilename('../evil/../codes.cht')).toBe('codes.cht')
    expect(safeCheatFilename('My Codes')).toBe('My_Codes.cht')
  })

  it('resolves cheat stage path under game uuid', () => {
    expect(resolveCheatStagePath('/appdata/cheats/', 'abc-123', 'inf.cht')).toBe(
      '/appdata/cheats/abc-123/inf.cht',
    )
  })

  it('fetchCheatText returns text on ok', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => 'cheat 0\n',
    })
    const result = await fetchCheatText({
      gameUuid: 'g1',
      filename: 'inf.cht',
      apiBase: 'https://gt.example',
      fetchImpl,
    })
    expect(result).toEqual({ ok: true, text: 'cheat 0\n' })
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://gt.example/api/games/g1/cheats/inf.cht',
      expect.objectContaining({ credentials: 'include', redirect: 'error' }),
    )
  })

  it('stageCheatFile writes under app_data/cheats via write_file_bytes', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => 'cheat 0\n',
    })
    const result = await stageCheatFile({
      gameUuid: 'game-42',
      filename: 'inf.cht',
      apiBase: 'https://gt.example',
      cheatSurface: 'retroarch',
      system: 'SNES',
      fetchImpl,
    })
    expect(result).toEqual({
      ok: true,
      path: '/appdata/cheats/game-42/inf.cht',
    })
    expect(invoke).toHaveBeenCalledWith('get_app_subdir', { subdir: 'cheats' })
    expect(invoke).toHaveBeenCalledWith('write_file_bytes', {
      path: '/appdata/cheats/game-42/inf.cht',
      bytes: expect.any(Uint8Array),
    })
    const writeCall = vi.mocked(invoke).mock.calls.find((c) => c[0] === 'write_file_bytes')
    const written = (writeCall?.[1] as { bytes: Uint8Array }).bytes
    expect(new TextDecoder().decode(written)).toBe('cheat 0\n')
  })

  it('stageCheatFile surfaces fetch failures', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 404 })
    const result = await stageCheatFile({
      gameUuid: 'game-42',
      filename: 'missing.cht',
      cheatSurface: 'retroarch',
      fetchImpl,
    })
    expect(result).toEqual({ ok: false, error: 'cheat download 404' })
    expect(invoke).not.toHaveBeenCalledWith('write_file_bytes', expect.anything())
  })

  it('shouldStageRetroArchCheat gates on cheat_surface=retroarch', () => {
    expect(
      shouldStageRetroArchCheat({
        cheatSurface: 'retroarch',
        gameUuid: 'g1',
        cheatFilename: 'inf.cht',
        system: 'SNES',
      }),
    ).toBe(true)
    expect(
      shouldStageRetroArchCheat({
        cheatSurface: 'pc_wand',
        gameUuid: 'g1',
        cheatFilename: 'inf.cht',
        system: 'PCWIN',
      }),
    ).toBe(false)
    expect(
      shouldStageRetroArchCheat({
        cheatSurface: 'none',
        gameUuid: 'g1',
        cheatFilename: 'inf.cht',
        system: 'PS5',
      }),
    ).toBe(false)
  })

  it('shouldStageRetroArchCheat soft-degrades: hide PC platforms when surface absent', () => {
    for (const system of ['PCWIN', 'PCDOS', 'MAC', 'OTHER']) {
      expect(
        shouldStageRetroArchCheat({
          gameUuid: 'g1',
          cheatFilename: 'inf.cht',
          system,
        }),
      ).toBe(false)
    }
    expect(
      shouldStageRetroArchCheat({
        gameUuid: 'g1',
        cheatFilename: 'inf.cht',
        system: 'SNES',
      }),
    ).toBe(true)
  })

  it('stageCheatFile skips non-retroarch surfaces without fetch', async () => {
    const fetchImpl = vi.fn()
    const result = await stageCheatFile({
      gameUuid: 'game-42',
      filename: 'inf.cht',
      cheatSurface: 'pc_wand',
      system: 'PCWIN',
      fetchImpl,
    })
    expect(result).toEqual({
      ok: false,
      error: 'cheat staging skipped: not retroarch surface',
    })
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(invoke).not.toHaveBeenCalledWith('write_file_bytes', expect.anything())
  })
})

describe('input family remaps (INSP-43)', () => {
  it('appends a remap for spinner, lightgun and trackball only', () => {
    expect(inputFamilyArgs('spinner')).toEqual([
      '--appendconfig',
      'input_remapping_path=oneirodex-spinner.rmp',
    ])
    expect(inputFamilyArgs('LightGun')).toEqual([
      '--appendconfig',
      'input_remapping_path=oneirodex-lightgun.rmp',
    ])
    expect(inputFamilyArgs('trackball')[1]).toContain('trackball')
    expect(inputFamilyArgs('joystick')).toEqual([])
    expect(inputFamilyArgs('dance mat')).toEqual([])
    expect(inputFamilyArgs(null)).toEqual([])
    expect(inputFamilyArgs(undefined)).toEqual([])
  })

  it('puts the family remap before caller args so an explicit one still wins', () => {
    const args = buildRetroArchArgs({
      core: 'mame_libretro.dll',
      system: 'ARCADE',
      romPath: 'D:/arcade/tempest.zip',
      inputFamily: 'spinner',
      extraArgs: ['--fullscreen'],
    })
    expect(args).toEqual([
      '-L',
      'mame_libretro.dll',
      'D:/arcade/tempest.zip',
      '--appendconfig',
      'input_remapping_path=oneirodex-spinner.rmp',
      '--fullscreen',
    ])
    expect(buildRetroArchArgs({ core: 'c', system: 'ARCADE', romPath: 'r' })).toEqual([
      '-L',
      'c',
      'r',
    ])
  })
})
