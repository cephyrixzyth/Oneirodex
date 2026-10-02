/**
 * Uninstall and update against a stateful fake filesystem, so the ORDER of
 * operations and what survives a failure are checked — not just which commands
 * were issued. (`uninstall.test.ts` mocks the store and the invoke results, which
 * is how a failing `preserve_install_files` and a half-done removal went unnoticed.)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createLifecycleRegistry } from './lifecycle.js'
import { kickoffUninstall, kickoffUpdate } from './uninstall.js'
import { kickoffInstall } from './install.js'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))
vi.mock('./download.js', () => ({ downloadGameArchive: vi.fn() }))
import { invoke } from '@tauri-apps/api/core'
import { downloadGameArchive } from './download.js'

/** Directories (path -> files) and loose files (archives). */
let dirs: Map<string, Record<string, string>>
let files: Set<string>
let stored: { installs: Record<string, any> }
/** Paths whose removal throws, like a locked exe or an antivirus scan. */
let locked: Set<string>
/** Every filesystem / registry step, in order. */
let events: string[]
/** What `preserve_install_files` does; the default copies the directory. */
let preserveFails: string | null
const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

function exists(path: string): boolean {
  return dirs.has(path) || files.has(path)
}

beforeEach(() => {
  dirs = new Map([['/installs/game', { 'game.exe': 'base', 'save.dat': 'progress' }]])
  files = new Set(['/downloads/game.zip'])
  stored = {
    installs: {
      game: {
        archive_path: '/downloads/game.zip',
        extract_path: '/installs/game',
        exe_path: '/installs/game/game.exe',
      },
    },
  }
  locked = new Set()
  events = []
  preserveFails = null
  warn.mockClear()
  vi.mocked(downloadGameArchive).mockReset()
  vi.mocked(invoke)
    .mockReset()
    .mockImplementation(async (command, args: any) => {
      switch (command) {
        case 'load_installs':
          return structuredClone(stored)
        case 'save_installs':
          events.push('save_installs')
          stored = structuredClone(args.installsFile)
          return undefined
        case 'remove_path':
          if (locked.has(args.path)) throw new Error(`locked: ${args.path}`)
          events.push(`remove ${args.path}`)
          dirs.delete(args.path)
          files.delete(args.path)
          return undefined
        case 'preserve_install_files':
          events.push('preserve_install_files')
          if (preserveFails) throw new Error(preserveFails)
          dirs.set(args.backupPath, { ...dirs.get(args.path) })
          return args.backupPath
        case 'restore_install_snapshot':
          dirs.set(args.to, { ...dirs.get(args.from) })
          return { extract_path: args.to, exe_path: `${args.to}/game.exe` }
        case 'extract_zip_archive':
          dirs.set(args.destDir, { 'patch.dat': 'patch' })
          return { extract_path: args.destDir, exe_path: null }
        case 'retain_install_files':
          dirs.set(args.to, { ...dirs.get(args.from), ...dirs.get(args.to) })
          return undefined
        default:
          return undefined
      }
    })
})

function installedRegistry(state: 'installed' | 'downloaded' | 'update_available' = 'installed') {
  return createLifecycleRegistry({ initial: [{ gameUuid: 'game', state }] })
}

describe('default uninstall (nothing is kept)', () => {
  it('makes no snapshot: no extra copy of the game, and no way for a copy to fail it', async () => {
    const registry = installedRegistry()
    expect(await kickoffUninstall(registry, 'game')).toBe('not_downloaded')

    expect(invoke).not.toHaveBeenCalledWith('preserve_install_files', expect.anything())
    expect(dirs.size).toBe(0)
    expect(files.size).toBe(0)
    expect(stored.installs.game).toBeUndefined()
  })

  it('still uninstalls an install the snapshot copy would refuse (symlinks, locked or full disk)', async () => {
    preserveFails = 'Linked install files cannot be copied'
    const registry = installedRegistry()
    await expect(kickoffUninstall(registry, 'game')).resolves.toBe('not_downloaded')
    expect(exists('/installs/game')).toBe(false)
  })

  it('removes files first and forgets the record last', async () => {
    const registry = installedRegistry()
    await kickoffUninstall(registry, 'game')
    expect(events).toEqual([
      'remove /installs/game.staging',
      'remove /installs/game',
      'remove /downloads/game.zip',
      'save_installs',
    ])
  })

  it('keeps the record, the archive and the registry when removing the install fails, so a retry works', async () => {
    locked.add('/installs/game')
    const registry = installedRegistry()
    await expect(kickoffUninstall(registry, 'game')).rejects.toThrow(/locked/)

    // Nothing was forgotten: the record, the archive and the state all still
    // describe an installed game.
    expect(stored.installs.game.extract_path).toBe('/installs/game')
    expect(exists('/downloads/game.zip')).toBe(true)
    expect(registry.get('game')).toBe('installed')

    locked.clear()
    await expect(kickoffUninstall(registry, 'game')).resolves.toBe('not_downloaded')
    expect(exists('/installs/game')).toBe(false)
    expect(exists('/downloads/game.zip')).toBe(false)
    expect(stored.installs.game).toBeUndefined()
  })

  it('keeps the record when removing the archive fails after the install is gone', async () => {
    locked.add('/downloads/game.zip')
    const registry = installedRegistry()
    await expect(kickoffUninstall(registry, 'game')).rejects.toThrow(/locked/)
    expect(stored.installs.game).toBeDefined()
    expect(registry.get('game')).toBe('installed')

    locked.clear()
    await expect(kickoffUninstall(registry, 'game')).resolves.toBe('not_downloaded')
    expect(files.size).toBe(0)
    expect(stored.installs.game).toBeUndefined()
  })

  it('also removes a snapshot left by an earlier archive-retaining uninstall', async () => {
    const registry = installedRegistry()
    await kickoffUninstall(registry, 'game', { removeArchive: false })
    expect(registry.get('game')).toBe('downloaded')
    const snapshot = stored.installs.game.retained_path as string
    expect(dirs.has(snapshot)).toBe(true)

    await kickoffUninstall(registry, 'game')
    expect(dirs.has(snapshot)).toBe(false)
    expect(files.size).toBe(0)
    expect(dirs.size).toBe(0)
    expect(stored.installs.game).toBeUndefined()
    expect(registry.get('game')).toBe('not_downloaded')
  })
})

describe('archive-retaining uninstall', () => {
  it('leaves the install in place when the snapshot cannot be made', async () => {
    preserveFails = 'Linked install files cannot be copied'
    const registry = installedRegistry()
    await expect(kickoffUninstall(registry, 'game', { removeArchive: false })).rejects.toThrow(
      /Linked install files/,
    )
    expect(dirs.get('/installs/game')?.['save.dat']).toBe('progress')
    expect(stored.installs.game.pending_uninstall).toBeUndefined()
    expect(registry.get('game')).toBe('installed')
  })

  it('records the snapshot before the working files are removed', async () => {
    const registry = installedRegistry()
    await kickoffUninstall(registry, 'game', { removeArchive: false })
    const save = events.indexOf('save_installs')
    const removeInstall = events.indexOf('remove /installs/game')
    expect(save).toBeGreaterThan(events.indexOf('preserve_install_files'))
    expect(removeInstall).toBeGreaterThan(save)
    expect(exists('/downloads/game.zip')).toBe(true)
  })
})

describe('update generations', () => {
  const generation = (n: number) => ({
    archivePath: `/downloads/game-update-${n}.zip`,
    extractPath: `/installs/game-update-${n}`,
  })
  async function update(registry: ReturnType<typeof installedRegistry>, n: number) {
    files.add(generation(n).archivePath)
    vi.mocked(downloadGameArchive).mockResolvedValueOnce(generation(n))
    registry.signalUpdateAvailable('game')
    return kickoffUpdate({} as never, {} as never, registry, 'game', { kind: 'extra' })
  }

  it('keeps exactly one superseded generation however many updates there are', async () => {
    const registry = installedRegistry()

    await update(registry, 1)
    // The base install is the superseded generation: kept for recovery.
    expect(exists('/installs/game')).toBe(true)
    expect(stored.installs.game.extract_path).toBe('/installs/game-update-1')
    expect(stored.installs.game.superseded).toEqual({
      archive_path: '/downloads/game.zip',
      extract_path: '/installs/game',
    })

    await update(registry, 2)
    // Generation 1 is the one superseded now; the base is gone for good.
    expect(exists('/installs/game')).toBe(false)
    expect(exists('/downloads/game.zip')).toBe(false)
    expect(exists('/installs/game-update-1')).toBe(true)
    expect(exists('/downloads/game-update-1.zip')).toBe(true)
    expect(stored.installs.game.extract_path).toBe('/installs/game-update-2')
    expect(stored.installs.game.superseded.extract_path).toBe('/installs/game-update-1')

    await update(registry, 3)
    expect(exists('/installs/game-update-1')).toBe(false)
    expect(exists('/downloads/game-update-1.zip')).toBe(false)
    expect([...dirs.keys()].sort()).toEqual(['/installs/game-update-2', '/installs/game-update-3'])
    // Saves are carried through every generation.
    expect(dirs.get('/installs/game-update-3')?.['save.dat']).toBe('progress')
  })

  it('uninstall removes the current generation and the superseded one: nothing is orphaned', async () => {
    const registry = installedRegistry()
    await update(registry, 1)
    await update(registry, 2)

    await kickoffUninstall(registry, 'game')

    expect(dirs.size).toBe(0)
    expect(files.size).toBe(0)
    expect(stored.installs.game).toBeUndefined()
  })

  it('a locked superseded generation stops the uninstall with the record intact, and a retry finishes it', async () => {
    const registry = installedRegistry()
    await update(registry, 1)
    locked.add('/installs/game') // the superseded base

    await expect(kickoffUninstall(registry, 'game')).rejects.toThrow(/locked/)
    // The record still points at the superseded copy, so nothing is orphaned.
    expect(stored.installs.game.superseded.extract_path).toBe('/installs/game')
    expect(registry.get('game')).toBe('installed')

    locked.clear()
    await expect(kickoffUninstall(registry, 'game')).resolves.toBe('not_downloaded')
    expect(dirs.size).toBe(0)
    expect(files.size).toBe(0)
    expect(stored.installs.game).toBeUndefined()
  })

  it('an archive-retaining uninstall drops the superseded generation but keeps the snapshot', async () => {
    const registry = installedRegistry()
    await update(registry, 1)

    await kickoffUninstall(registry, 'game', { removeArchive: false })

    expect(exists('/installs/game')).toBe(false) // the superseded base
    expect(exists('/installs/game-update-1')).toBe(false) // the working install
    const snapshot = stored.installs.game.retained_path as string
    expect(dirs.get(snapshot)?.['save.dat']).toBe('progress')
    expect(stored.installs.game.superseded).toBeUndefined()
    expect(exists('/downloads/game-update-1.zip')).toBe(true) // retained archive

    // And the snapshot still reinstalls the complete game.
    await kickoffInstall(registry, 'game')
    expect(dirs.get(stored.installs.game.extract_path)?.['save.dat']).toBe('progress')
  })

  it('does not remove anything when the new generation cannot be committed', async () => {
    const registry = installedRegistry()
    await update(registry, 1)
    const before = structuredClone(stored)
    const implementation = vi.mocked(invoke).getMockImplementation()!
    vi.mocked(invoke).mockImplementation(async (command, args) => {
      if (command === 'save_installs') throw new Error('disk full')
      return implementation(command, args)
    })

    await expect(update(registry, 2)).rejects.toThrow('disk full')

    expect(stored).toEqual(before)
    expect(exists('/installs/game')).toBe(true)
    expect(exists('/installs/game-update-1')).toBe(true)
  })

  it('a failure removing the old generation never fails the update that replaced it', async () => {
    const registry = installedRegistry()
    await update(registry, 1)
    locked.add('/installs/game')

    await expect(update(registry, 2)).resolves.toBe('installed')

    expect(stored.installs.game.extract_path).toBe('/installs/game-update-2')
    expect(exists('/installs/game')).toBe(true) // stuck, but only a leftover
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('could not remove superseded'))
  })
})
