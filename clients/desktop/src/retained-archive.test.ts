import { beforeEach, expect, it, vi } from 'vitest'
import { kickoffUninstall } from './uninstall.js'
import { kickoffInstall } from './install.js'
import { createLifecycleRegistry } from './lifecycle.js'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))
import { invoke } from '@tauri-apps/api/core'

let stored: { installs: Record<string, unknown> }
beforeEach(() => {
  stored = {
    installs: {
      game: {
        archive_path: '/downloads/game.zip',
        extract_path: '/installs/game',
        exe_path: '/installs/game/game.exe',
      },
    },
  }
  vi.mocked(invoke)
    .mockReset()
    .mockImplementation(async (command, args: any) => {
      if (command === 'load_installs') return structuredClone(stored)
      if (command === 'save_installs') stored = structuredClone(args.installsFile)
      if (command === 'preserve_install_files') return args.backupPath
      if (command === 'restore_install_snapshot')
        return { extract_path: args.to, exe_path: `${args.to}/game.exe` }
      if (command === 'extract_zip_archive')
        return { extract_path: args.destDir, exe_path: `${args.destDir}/game.exe` }
      return undefined
    })
})

it('reinstalls a retained archive using the persisted record, without a download', async () => {
  const registry = createLifecycleRegistry({ initial: [{ gameUuid: 'game', state: 'installed' }] })
  expect(await kickoffUninstall(registry, 'game', { removeArchive: false })).toBe('downloaded')
  expect(stored.installs.game).toEqual({
    archive_path: '/downloads/game.zip',
    extract_path: '/installs/game',
    exe_path: null,
    retained_path: expect.stringContaining('.uninstalled-'),
    pending_uninstall: true,
  })
  expect(await kickoffInstall(registry, 'game')).toBe('installed')
  expect(invoke).toHaveBeenCalledWith(
    'restore_install_snapshot',
    expect.objectContaining({
      from: expect.stringContaining('.uninstalled-'),
      to: expect.stringContaining('.reinstall-'),
    }),
  )
  expect(invoke).not.toHaveBeenCalledWith('remove_path', { path: '/downloads/game.zip' })
})

it('retaining an already downloaded archive remains reinstallable', async () => {
  const registry = createLifecycleRegistry({ initial: [{ gameUuid: 'game', state: 'downloaded' }] })
  expect(await kickoffUninstall(registry, 'game', { removeArchive: false })).toBe('downloaded')
  expect(await kickoffInstall(registry, 'game')).toBe('installed')
})
