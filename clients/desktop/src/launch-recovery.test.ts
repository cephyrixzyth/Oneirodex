import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { OneirodexClient } from './api.js'
import { createLaunchRecovery } from './launch-recovery.js'

const native = vi.hoisted(() => ({ invoke: vi.fn() }))
vi.mock('@tauri-apps/api/core', () => native)
const profile = 'a'.repeat(64)
const clientId = '5d283155-6b33-45c9-b9cf-a8e872dd0559'
const claimId = '5d283155-6b33-45c9-b9cf-a8e872dd0560'
const record = { game_uuid: 'game-a', pid: 1234, launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0561' }
let launches: (typeof record)[]
let unverified: number
let owns: boolean
function api() {
  return {
    playtime: {
      startSession: vi.fn().mockResolvedValue({ id: 77 }),
      heartbeatSession: vi.fn().mockResolvedValue({}),
      stopSession: vi.fn().mockResolvedValue({}),
    },
  } as unknown as OneirodexClient
}
async function settle() {
  for (let i = 0; i < 20; i++) await Promise.resolve()
}
beforeEach(() => {
  vi.useFakeTimers()
  launches = [record]
  unverified = 0
  owns = true
  native.invoke
    .mockReset()
    .mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      switch (command) {
        case 'begin_launch_reporting':
          return clientId
        case 'list_launches':
          return { supported: true, launches, unverified }
        case 'acquire_launch_reporting':
          return claimId
        case 'owns_launch_reporting':
          return owns && args?.clientId === clientId && args?.claimId === claimId
        case 'release_launch_reporting':
          return undefined
        case 'forget_launch_bindings':
          return undefined
        default:
          throw new Error(`Unexpected native command ${command}`)
      }
    })
})
afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})
describe('verified native launch recovery', () => {
  it('starts a fresh interval for a verified live account-bound family', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    expect(await reporter.resume(server, profile, () => true)).toEqual({
      resumed: 1,
      unverified: 0,
    })
    expect(server.playtime.startSession).toHaveBeenCalledExactlyOnceWith({
      game_uuid: 'game-a',
      client: 'desktop',
    })
    expect(native.invoke).toHaveBeenCalledWith('list_launches', { profileBinding: profile })
    reporter.stopAll()
    await settle()
  })
  it('aggregates two game instances until both have exited', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    launches = [record, { ...record, pid: 1235, launch_id: '5d283155-6b33-45c9-b9cf-a8e872dd0562' }]
    expect((await reporter.begin(server, profile, 'game-a')).sessionId).toBe(77)
    expect((await reporter.begin(server, profile, 'game-a')).sessionId).toBe(77)
    expect(server.playtime.startSession).toHaveBeenCalledTimes(1)
    launches = [launches[1]!]
    await vi.advanceTimersByTimeAsync(30_000)
    expect(server.playtime.heartbeatSession).toHaveBeenCalledExactlyOnceWith(77)
    expect(server.playtime.stopSession).not.toHaveBeenCalled()
    launches = []
    await vi.advanceTimersByTimeAsync(60_000)
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    expect(native.invoke).toHaveBeenCalledWith('release_launch_reporting', { claimId })
    reporter.stopAll()
  })
  it('does not infer a live family from unverified metadata or another reporter', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    launches = []
    unverified = 1
    expect(await reporter.resume(server, profile, () => true)).toEqual({
      resumed: 0,
      unverified: 1,
    })
    expect(server.playtime.startSession).not.toHaveBeenCalled()
    launches = [record]
    unverified = 0
    native.invoke.mockImplementation(async (command: string) =>
      command === 'list_launches'
        ? { supported: true, launches, unverified: 0 }
        : command === 'begin_launch_reporting'
          ? clientId
          : null,
    )
    expect((await reporter.begin(server, profile, 'game-a')).state).toBe('owned_elsewhere')
    expect(server.playtime.startSession).not.toHaveBeenCalled()
    reporter.stopAll()
  })
  it('does not automatically retry an ambiguous API start on refresh', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    vi.mocked(server.playtime.startSession).mockRejectedValue(new Error('reply lost'))
    await reporter.resume(server, profile, () => true)
    await reporter.resume(server, profile, () => true)
    expect(server.playtime.startSession).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    expect(native.invoke).toHaveBeenCalledWith('release_launch_reporting', { claimId })
    reporter.stopAll()
  })
  it('retires a late old-profile reply without installing a new watcher', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    let current = true
    let resolve!: (value: { id: number }) => void
    vi.mocked(server.playtime.startSession).mockReturnValue(
      new Promise((done) => {
        resolve = done
      }),
    )
    const pending = reporter.begin(server, profile, 'game-a', () => current)
    await settle()
    expect(server.playtime.startSession).toHaveBeenCalledTimes(1)
    current = false
    reporter.stopAll()
    resolve({ id: 77 })
    expect((await pending).sessionId).toBeNull()
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(server.playtime.heartbeatSession).not.toHaveBeenCalled()
  })
  it('stops reporting if the native UI generation no longer owns its claim', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    await reporter.resume(server, profile, () => true)
    owns = false
    await vi.advanceTimersByTimeAsync(60_000)
    expect(server.playtime.heartbeatSession).not.toHaveBeenCalled()
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    reporter.stopAll()
  })
  it('rechecks the profile after a delayed native ownership reply', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    let current = true
    let confirm!: (value: boolean) => void
    let checks = 0
    const previous = native.invoke.getMockImplementation()!
    native.invoke.mockImplementation(async (command: string, args?: Record<string, unknown>) => {
      if (command === 'owns_launch_reporting' && ++checks === 2)
        return new Promise<boolean>((resolve) => {
          confirm = resolve
        })
      return previous(command, args)
    })
    const pending = reporter.begin(server, profile, 'game-a', () => current)
    await settle()
    expect(confirm).toBeTypeOf('function')
    current = false
    reporter.stopAll()
    confirm(true)
    expect((await pending).sessionId).toBeNull()
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('Forget clears recovery bindings while retiring reporting only', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    await reporter.resume(server, profile, () => true)
    await reporter.forget()
    expect(native.invoke).toHaveBeenCalledWith('forget_launch_bindings')
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('reports a heartbeat failure as unavailable without claiming the local game ended', async () => {
    const reporter = createLaunchRecovery()
    const server = api()
    const notice = vi.fn()
    reporter.onUnavailable(notice)
    vi.mocked(server.playtime.heartbeatSession).mockRejectedValue(new Error('server unavailable'))
    await reporter.resume(server, profile, () => true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(notice).toHaveBeenCalledExactlyOnceWith('game-a')
    expect(server.playtime.stopSession).toHaveBeenCalledExactlyOnceWith(77)
    reporter.stopAll()
  })
})
