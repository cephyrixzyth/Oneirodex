import { beforeEach, expect, it, vi } from 'vitest'
import { kickoffUninstall, kickoffUpdate } from './uninstall.js'
import { kickoffInstall } from './install.js'
import { createLifecycleRegistry } from './lifecycle.js'
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))
vi.mock('./download.js', () => ({ downloadGameArchive: vi.fn() }))
import { invoke } from '@tauri-apps/api/core'
import { downloadGameArchive } from './download.js'

let stored: any
let trees: Map<string, Record<string, string>>
beforeEach(() => {
  stored = {
    installs: {
      game: { archive_path: '/downloads/base.zip', extract_path: '/installs/base', exe_path: null },
    },
  }
  trees = new Map([['/installs/base', { 'game.exe': 'base', 'save.dat': 'progress' }]])
  vi.mocked(downloadGameArchive).mockResolvedValue({
    archivePath: '/downloads/patch.zip',
    extractPath: '/installs/update',
  })
  vi.mocked(invoke)
    .mockReset()
    .mockImplementation(async (command, args: any) => {
      if (command === 'load_installs') return structuredClone(stored)
      if (command === 'save_installs') stored = structuredClone(args.installsFile)
      if (command === 'extract_zip_archive') {
        trees.set(args.destDir, { 'patch.dat': 'patch' })
        return { extract_path: args.destDir, exe_path: null }
      }
      if (command === 'retain_install_files')
        trees.set(args.to, { ...trees.get(args.from), ...trees.get(args.to) })
      if (command === 'preserve_install_files') {
        trees.set(args.backupPath, { ...trees.get(args.path) })
        return args.backupPath
      }
      if (command === 'remove_path') trees.delete(args.path)
      if (command === 'restore_install_snapshot') {
        trees.set(args.to, { ...trees.get(args.from) })
        return { extract_path: args.to, exe_path: `${args.to}/game.exe` }
      }
      return undefined
    })
})

it('preserves base files and saves through pack update, retained uninstall and reinstall', async () => {
  const registry = createLifecycleRegistry({
    initial: [{ gameUuid: 'game', state: 'update_available' }],
  })
  await kickoffUpdate({} as never, {} as never, registry, 'game', { kind: 'extra' })
  expect(trees.get('/installs/update')).toEqual({
    'game.exe': 'base',
    'save.dat': 'progress',
    'patch.dat': 'patch',
  })
  await kickoffUninstall(registry, 'game', { removeArchive: false })
  expect(trees.has('/installs/update')).toBe(false)
  await kickoffInstall(registry, 'game')
  expect(trees.get(stored.installs.game.extract_path)).toEqual({
    'game.exe': 'base',
    'save.dat': 'progress',
    'patch.dat': 'patch',
  })
})

it('keeps the source install if snapshot persistence fails', async () => {
  const registry = createLifecycleRegistry({ initial: [{ gameUuid: 'game', state: 'installed' }] })
  const implementation = vi.mocked(invoke).getMockImplementation()!
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    if (command === 'save_installs') throw new Error('disk full')
    return implementation(command, args)
  })
  await expect(kickoffUninstall(registry, 'game', { removeArchive: false })).rejects.toThrow(
    'disk full',
  )
  expect(trees.get('/installs/base')?.['save.dat']).toBe('progress')
  expect(registry.get('game')).toBe('installed')
})

it.each([false, true])('reuses complete snapshot when cleanup was interrupted (partial=%s)', async (partial) => {
  stored.installs.game.retained_path = '/installs/snapshot'
  stored.installs.game.pending_uninstall = true
  trees.set('/installs/snapshot', { 'game.exe': 'base', 'save.dat': 'progress' })
  if (partial) trees.set('/installs/base', { 'game.exe': 'base' })
  else trees.delete('/installs/base')
  const registry = createLifecycleRegistry({ initial: [{ gameUuid: 'game', state: 'installed' }] })
  await kickoffUninstall(registry, 'game', { removeArchive: false })
  expect(invoke).not.toHaveBeenCalledWith('preserve_install_files', expect.anything())
  await kickoffInstall(registry, 'game')
  expect(trees.get(stored.installs.game.extract_path)?.['save.dat']).toBe('progress')
  expect(stored.installs.game.pending_uninstall).toBeUndefined()
})
