import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { OneirodexClient } from './api.js'
import { kickoffLaunch } from './launch.js'

const native = vi.hoisted(() => ({ invoke: vi.fn() }))
const recovery = vi.hoisted(() => ({ begin: vi.fn(), stopAll: vi.fn(), stopGame: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => native)
vi.mock('./launch-recovery.js', () => ({ launchRecovery: recovery }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))
vi.mock('./install.js', () => ({
  getInstallRecord: vi.fn(async () => ({
    extractPath: '/synthetic/install',
    exePath: '/synthetic/install/game.exe',
  })),
}))
const profile = 'a'.repeat(64)
const identity = { pid: 9001, launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0559' }
function api() {
  return { playtime: { startSession: vi.fn() } } as unknown as OneirodexClient
}
beforeEach(() => {
  native.invoke.mockReset().mockResolvedValue(identity)
  recovery.begin.mockReset().mockResolvedValue({ state: 'active', sessionId: 77 })
})
describe('native launch account binding handoff', () => {
  it('binds before native creation and delegates reporting to the verified aggregate', async () => {
    const server = api()
    const current = () => true
    const result = await kickoffLaunch(server, 'game-a', { profileBinding: profile, current })
    expect(native.invoke).toHaveBeenCalledWith('launch_game', {
      gameUuid: 'game-a',
      exePath: '/synthetic/install/game.exe',
      extractPath: '/synthetic/install',
      profileBinding: profile,
    })
    expect(recovery.begin).toHaveBeenCalledWith(server, profile, 'game-a', current, true)
    expect(result.sessionId).toBe(77)
    expect(server.playtime.startSession).not.toHaveBeenCalled()
  })
  it('keeps local play without server reporting if the verified profile is incomplete', async () => {
    const server = api()
    expect(
      (await kickoffLaunch(server, 'game-a', { profileBinding: null, current: () => true })).pid,
    ).toBe(9001)
    expect(recovery.begin).not.toHaveBeenCalled()
    expect(server.playtime.startSession).not.toHaveBeenCalled()
  })
  it('rejects an obsolete account action before creating a local process', async () => {
    await expect(
      kickoffLaunch(api(), 'game-a', { profileBinding: profile, current: () => false }),
    ).rejects.toThrow(/profile changed/i)
    expect(native.invoke).not.toHaveBeenCalled()
  })
  it('does not report an unverifiable old native receipt under the new profile', async () => {
    native.invoke.mockResolvedValue({ pid: 9001 })
    const server = api()
    expect(
      (await kickoffLaunch(server, 'game-a', { profileBinding: profile, current: () => true }))
        .sessionId,
    ).toBeNull()
    expect(recovery.begin).not.toHaveBeenCalled()
    expect(server.playtime.startSession).not.toHaveBeenCalled()
  })
})
