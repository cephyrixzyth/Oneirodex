import { invoke } from '@tauri-apps/api/core'
import type { OneirodexClient } from './api.js'
import { hasNativeLaunchIdentity } from './process-status.js'
import { watchPlaySession, type PlaySessionWatcher } from './playtime-session.js'

interface LaunchRecord {
  game_uuid: string
  pid: number
  launch_id: string
}
interface Inventory {
  supported: boolean
  launches: LaunchRecord[]
  unverified: number
}
export interface RecoveryResult {
  resumed: number
  unverified: number
}
export interface ReportingResult {
  sessionId: number | null
  state: 'active' | 'unavailable' | 'owned_elsewhere' | 'unsupported'
  started?: boolean
}
interface Reporter {
  game: string
  sessionId: number
  watcher: PlaySessionWatcher
}
const unavailable: ReportingResult = { sessionId: null, state: 'unavailable' }

async function inventory(profile: string): Promise<Inventory> {
  if (!/^[a-f0-9]{64}$/.test(profile)) throw new Error('Verified launch profile is incomplete')
  const result = await invoke<Inventory>('list_launches', { profileBinding: profile })
  if (
    !result ||
    typeof result.supported !== 'boolean' ||
    !Array.isArray(result.launches) ||
    !Number.isSafeInteger(result.unverified) ||
    result.unverified < 0 ||
    result.launches.some(
      (record) =>
        typeof record?.game_uuid !== 'string' ||
        !record.game_uuid ||
        record.game_uuid.length > 128 ||
        !hasNativeLaunchIdentity(record.pid, record.launch_id),
    )
  ) {
    throw new Error('Native launch recovery could not be verified')
  }
  return result
}

export function createLaunchRecovery() {
  let stoppedNotice: ((game: string) => void) | undefined
  const active = new Map<string, Reporter>()
  const pending = new Map<string, Promise<ReportingResult>>()
  const attempted = new Set<string>()
  let generation = 0
  let clientPromise: Promise<string> | null = null

  function client(): Promise<string> {
    if (!clientPromise) {
      clientPromise = invoke<string>('begin_launch_reporting').then((value) => {
        if (!hasNativeLaunchIdentity(1, value))
          throw new Error('Native reporting client is unavailable')
        return value
      })
    }
    return clientPromise
  }
  function release(claimId: string): void {
    void invoke('release_launch_reporting', { claimId }).catch(() => undefined)
  }
  async function retire(api: OneirodexClient, sessionId: number): Promise<void> {
    try {
      await api.playtime.stopSession(sessionId)
    } catch {
      /* Heartbeat TTL caps the old interval. */
    }
  }
  async function begin(
    api: OneirodexClient,
    profile: string,
    game: string,
    current: () => boolean = () => true,
    newLaunch = false,
  ): Promise<ReportingResult> {
    const key = `${profile}:${game}`
    if (!current()) return unavailable
    const existing = active.get(key)
    if (existing) return { sessionId: existing.sessionId, state: 'active' }
    const starting = pending.get(key)
    if (starting) return starting
    if (newLaunch) attempted.delete(key)
    if (attempted.has(key)) return unavailable
    const epoch = generation
    const valid = () => epoch === generation && current()
    const operation = (async (): Promise<ReportingResult> => {
      let claimId: string | null = null
      try {
        const initial = await inventory(profile)
        if (!valid()) return unavailable
        if (!initial.supported) return { sessionId: null, state: 'unsupported' }
        if (!initial.launches.some((record) => record.game_uuid === game)) return unavailable
        const clientId = await client()
        if (!valid()) return unavailable
        claimId = await invoke<string | null>('acquire_launch_reporting', {
          profileBinding: profile,
          gameUuid: game,
          clientId,
        })
        if (claimId === null) return { sessionId: null, state: 'owned_elsewhere' }
        if (!hasNativeLaunchIdentity(1, claimId))
          throw new Error('Native reporter ownership is invalid')
        const retainedClaim = claimId
        const owned = async () => {
          if (!valid()) return false
          const stillOwned = await invoke<boolean>('owns_launch_reporting', {
            clientId,
            claimId: retainedClaim,
          })
          return valid() && stillOwned === true
        }
        const confirmed = await inventory(profile)
        if (!(await owned()) || !confirmed.launches.some((record) => record.game_uuid === game))
          return unavailable
        attempted.add(key)
        const session = await api.playtime.startSession({ game_uuid: game, client: 'desktop' })
        const sessionId = session.id
        if (typeof sessionId !== 'number' || !Number.isSafeInteger(sessionId) || sessionId <= 0)
          return unavailable
        if (!(await owned())) {
          await retire(api, sessionId)
          return unavailable
        }
        const anchor = confirmed.launches.find((record) => record.game_uuid === game)!
        const watcher = watchPlaySession(api, anchor.pid, sessionId, {
          launchId: anchor.launch_id,
          isProcessRunning: async () => {
            if (!(await owned())) throw new Error('Playtime reporter was replaced')
            const live = await inventory(profile)
            if (!valid()) throw new Error('Account profile changed')
            if (live.launches.some((record) => record.game_uuid === game)) return true
            if (live.unverified) throw new Error('Native game state is unverified')
            return false
          },
          onStopped: (reason) => {
            if (active.get(key) === reporter) active.delete(key)
            attempted.delete(key)
            release(retainedClaim)
            if (reason === 'unavailable' && valid()) stoppedNotice?.(game)
          },
        })
        const reporter: Reporter = { game, sessionId, watcher }
        active.set(key, reporter)
        claimId = null
        return { sessionId, state: 'active', started: true }
      } catch {
        return unavailable
      } finally {
        if (claimId) release(claimId)
      }
    })()
    pending.set(key, operation)
    try {
      return await operation
    } finally {
      if (pending.get(key) === operation) pending.delete(key)
    }
  }
  function stopAll(): void {
    generation++
    const reporters = [...active.values()]
    active.clear()
    pending.clear()
    attempted.clear()
    for (const reporter of reporters) void reporter.watcher.stop().catch(() => undefined)
    if (clientPromise) {
      clientPromise = clientPromise
        .catch(() => '')
        .then(() => invoke<string>('begin_launch_reporting'))
      void clientPromise.catch(() => undefined)
    }
  }
  return {
    onUnavailable(callback: (game: string) => void): void {
      stoppedNotice = callback
    },
    begin,
    async resume(
      api: OneirodexClient,
      profile: string,
      current: () => boolean,
    ): Promise<RecoveryResult> {
      if (!current()) return { resumed: 0, unverified: 0 }
      try {
        const records = await inventory(profile)
        if (!current() || !records.supported) return { resumed: 0, unverified: 0 }
        await client()
        let resumed = 0
        let unverified = records.unverified
        for (const game of new Set(records.launches.map((record) => record.game_uuid))) {
          if (!current()) break
          const result = await begin(api, profile, game, current)
          if (result.started) resumed++
          else if (result.state === 'unavailable') unverified++
        }
        return { resumed, unverified }
      } catch {
        return { resumed: 0, unverified: 1 }
      }
    },
    stopAll,
    async forget(): Promise<void> {
      stopAll()
      await clientPromise?.catch(() => undefined)
      await invoke('forget_launch_bindings')
      clientPromise = null
    },
    async stopGame(game: string): Promise<void> {
      for (const reporter of [...active.values()])
        if (reporter.game === game) await reporter.watcher.stop()
    },
  }
}

export const launchRecovery = createLaunchRecovery()
