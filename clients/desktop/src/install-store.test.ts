import { beforeEach, expect, it, vi } from 'vitest'

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))

import { loadInstallsFromDisk, saveInstallsToDisk } from './install-store.js'

let stored: { installs: Record<string, any> }

beforeEach(() => {
  stored = { installs: {} }
  invoke.mockReset()
  invoke.mockImplementation(async (command: string, args?: any) => {
    if (command === 'load_installs') return structuredClone(stored)
    if (command === 'save_installs') {
      stored = structuredClone(args.installsFile)
      return undefined
    }
    throw new Error(`unexpected command: ${command}`)
  })
})

it('merges concurrent per-game record changes instead of losing the last writer', async () => {
  const [first, second] = await Promise.all([
    loadInstallsFromDisk(),
    loadInstallsFromDisk(),
  ])
  first['game-a'] = { archivePath: '/downloads/a.zip', extractPath: '/installs/a' }
  second['game-b'] = { archivePath: '/downloads/b.zip', extractPath: '/installs/b' }

  await Promise.all([saveInstallsToDisk(first), saveInstallsToDisk(second)])

  expect(Object.keys(stored.installs).sort()).toEqual(['game-a', 'game-b'])
})

it('preserves another writer while deleting only the selected game record', async () => {
  stored = {
    installs: {
      'game-a': { archive_path: '/a.zip', extract_path: '/a' },
      'game-b': { archive_path: '/b.zip', extract_path: '/b' },
    },
  }
  const [removeA, updateB] = await Promise.all([
    loadInstallsFromDisk(),
    loadInstallsFromDisk(),
  ])
  delete removeA['game-a']
  updateB['game-b'].exePath = '/b/game.exe'

  await Promise.all([saveInstallsToDisk(removeA), saveInstallsToDisk(updateB)])

  expect(stored.installs).toEqual({
    'game-b': {
      archive_path: '/b.zip',
      extract_path: '/b',
      exe_path: '/b/game.exe',
    },
  })
})

it('saves the record snapshot captured when the save was requested', async () => {
  const installs = await loadInstallsFromDisk()
  installs['game-a'] = { archivePath: '/downloads/a.zip', extractPath: '/installs/a' }

  const pendingSave = saveInstallsToDisk(installs)
  installs['game-b'] = { archivePath: '/downloads/b.zip', extractPath: '/installs/b' }
  await pendingSave

  expect(Object.keys(stored.installs)).toEqual(['game-a'])

  await saveInstallsToDisk(installs)
  expect(Object.keys(stored.installs).sort()).toEqual(['game-a', 'game-b'])
})

it('refuses unbased full-map saves that could replace unrelated records', async () => {
  stored = {
    installs: {
      'game-a': { archive_path: '/a.zip', extract_path: '/a' },
    },
  }

  await expect(
    saveInstallsToDisk({
      'game-b': { archivePath: '/b.zip', extractPath: '/b' },
    }),
  ).rejects.toThrow('Install records must be loaded before they can be saved')

  expect(Object.keys(stored.installs)).toEqual(['game-a'])
})
