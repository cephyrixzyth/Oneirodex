import { describe, expect, it, vi, beforeEach } from 'vitest'

import { createLifecycleRegistry } from './lifecycle.js'
import { kickoffUninstall, kickoffUpdate } from './uninstall.js'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

vi.mock('./install-store.js', () => ({
  loadInstallsFromDisk: vi.fn(),
  saveInstallsToDisk: vi.fn(),
}))

vi.mock('./install.js', () => ({
  getInstallRecord: vi.fn(),
  extractInstallArchive: vi.fn(),
}))

vi.mock('./download.js', () => ({
  downloadGameArchive: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import { downloadGameArchive } from './download.js'
import { extractInstallArchive, getInstallRecord } from './install.js'
import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'

describe('uninstall helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(loadInstallsFromDisk).mockReset()
    vi.mocked(saveInstallsToDisk).mockReset()
    vi.mocked(getInstallRecord).mockReset()
    vi.mocked(extractInstallArchive).mockReset()
    vi.mocked(downloadGameArchive).mockReset()
  })

  it('removes extract path, staging, and archive then clears registry to not_downloaded', async () => {
    const registry = createLifecycleRegistry()
    registry.apply('game-7', 'download')
    registry.apply('game-7', 'install')

    vi.mocked(getInstallRecord).mockResolvedValue({
      archivePath: '/appdata/downloads/game-7.zip',
      extractPath: '/appdata/installs/game-7',
      exePath: '/appdata/installs/game-7/game.exe',
    })
    vi.mocked(loadInstallsFromDisk).mockResolvedValue({
      'game-7': {
        archivePath: '/appdata/downloads/game-7.zip',
        extractPath: '/appdata/installs/game-7',
      },
    })
    vi.mocked(invoke).mockResolvedValue(undefined)

    const next = await kickoffUninstall(registry, 'game-7')

    expect(invoke).toHaveBeenCalledWith('remove_path', {
      path: '/appdata/installs/game-7',
    })
    expect(invoke).toHaveBeenCalledWith('remove_path', {
      path: '/appdata/installs/game-7.staging',
    })
    expect(invoke).toHaveBeenCalledWith('remove_path', {
      path: '/appdata/downloads/game-7.zip',
    })
    expect(saveInstallsToDisk).toHaveBeenCalledWith({})
    expect(next).toBe('not_downloaded')
    expect(registry.get('game-7')).toBe('not_downloaded')
    // Nothing is kept, so no snapshot copy is made (it would be orphaned at once).
    expect(invoke).not.toHaveBeenCalledWith('preserve_install_files', expect.anything())
  })

  it.each(['.', '..', 'a/b', 'a\\b', ''])(
    'refuses game id %j without touching the filesystem',
    async (hostileId) => {
      const registry = createLifecycleRegistry({
        initial: [{ gameUuid: hostileId, state: 'installed' }],
      })
      vi.mocked(getInstallRecord).mockResolvedValue({
        archivePath: '/appdata/downloads/.zip',
        // What an unvalidated "." produced: the installs root itself.
        extractPath: '/appdata/installs/.',
      })

      await expect(kickoffUninstall(registry, hostileId)).rejects.toThrow(/Invalid game id/)
      await expect(kickoffUpdate({} as never, {} as never, registry, hostileId)).rejects.toThrow(
        /Invalid game id/,
      )

      expect(invoke).not.toHaveBeenCalled()
      expect(getInstallRecord).not.toHaveBeenCalled()
      expect(saveInstallsToDisk).not.toHaveBeenCalled()
      expect(downloadGameArchive).not.toHaveBeenCalled()
    },
  )
})

describe('update helper', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
    vi.mocked(loadInstallsFromDisk).mockReset()
    vi.mocked(saveInstallsToDisk).mockReset()
    vi.mocked(getInstallRecord).mockReset()
    vi.mocked(extractInstallArchive).mockReset()
    vi.mocked(downloadGameArchive).mockReset()
  })

  it('commits a separate update generation and retains the working files', async () => {
    const registry = createLifecycleRegistry()
    registry.apply('game-9', 'download')
    registry.apply('game-9', 'install')
    registry.signalUpdateAvailable('game-9')

    vi.mocked(getInstallRecord).mockResolvedValue({
      archivePath: '/appdata/downloads/game-9.zip',
      extractPath: '/appdata/installs/game-9',
      exePath: '/appdata/installs/game-9/old.exe',
    })
    vi.mocked(downloadGameArchive).mockResolvedValue({
      archivePath: '/appdata/downloads/game-9-update.zip',
      extractPath: '/appdata/installs/game-9-update',
    })
    vi.mocked(extractInstallArchive).mockResolvedValue({
      archivePath: '/appdata/downloads/game-9-update.zip',
      extractPath: '/appdata/installs/game-9-update',
      exePath: '/appdata/installs/game-9-update/game.exe',
    })
    vi.mocked(loadInstallsFromDisk).mockResolvedValue({})
    vi.mocked(invoke).mockResolvedValue(undefined)

    const api = {} as never
    const auth = {} as never
    const next = await kickoffUpdate(api, auth, registry, 'game-9')

    expect(extractInstallArchive).toHaveBeenCalledWith(
      'game-9',
      expect.objectContaining({ extractPath: '/appdata/installs/game-9-update' }),
      { persist: false },
    )
    expect(invoke).toHaveBeenCalledWith('retain_install_files', {
      from: '/appdata/installs/game-9',
      to: '/appdata/installs/game-9-update',
    })
    expect(saveInstallsToDisk).toHaveBeenCalledWith({
      'game-9': {
        archivePath: '/appdata/downloads/game-9-update.zip',
        extractPath: '/appdata/installs/game-9-update',
        exePath: '/appdata/installs/game-9-update/game.exe',
        // The generation this update replaced stays recoverable until the next one.
        superseded: {
          archivePath: '/appdata/downloads/game-9.zip',
          extractPath: '/appdata/installs/game-9',
        },
      },
    })
    expect(next).toBe('installed')
    expect(registry.get('game-9')).toBe('installed')
    expect(invoke.mock.calls.some(([command]) => command === 'remove_path')).toBe(false)
  })

  it.each(['download', 'extract', 'retain', 'commit'])(
    'keeps the working install on %s failure',
    async (failure) => {
      const registry = createLifecycleRegistry({
        initial: [{ gameUuid: 'game', state: 'update_available' }],
      })
      const old = {
        archivePath: '/downloads/old.zip',
        extractPath: '/installs/old',
        exePath: '/installs/old/game.exe',
      }
      const next = {
        archivePath: '/downloads/new.zip',
        extractPath: '/installs/new',
        exePath: '/installs/new/game.exe',
      }
      vi.mocked(getInstallRecord).mockResolvedValue(old)
      vi.mocked(loadInstallsFromDisk).mockResolvedValue({ game: old })
      vi.mocked(downloadGameArchive).mockResolvedValue(next)
      vi.mocked(extractInstallArchive).mockResolvedValue(next)
      const error = new Error('injected failure')
      if (failure === 'download') vi.mocked(downloadGameArchive).mockRejectedValue(error)
      if (failure === 'extract') vi.mocked(extractInstallArchive).mockRejectedValue(error)
      if (failure === 'retain') vi.mocked(invoke).mockRejectedValue(error)
      if (failure === 'commit') vi.mocked(saveInstallsToDisk).mockRejectedValue(error)
      await expect(kickoffUpdate({} as never, {} as never, registry, 'game')).rejects.toThrow(
        'injected failure',
      )
      expect(registry.get('game')).toBe('update_available')
      expect(invoke.mock.calls.some(([command]) => command === 'remove_path')).toBe(false)
      if (failure !== 'commit') expect(saveInstallsToDisk).not.toHaveBeenCalled()
    },
  )
})
