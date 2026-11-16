/**
 * Local install lifecycle aligned with web GameActionBar states.
 *
 * not_downloaded → downloaded → installed → update_available
 * uninstall from installed/update_available → downloaded (or cleared)
 */

export type GameLifecycleState = 'not_downloaded' | 'downloaded' | 'installed' | 'update_available'

export type LifecycleAction = 'download' | 'install' | 'update' | 'uninstall'

const VALID_STATES: readonly GameLifecycleState[] = [
  'not_downloaded',
  'downloaded',
  'installed',
  'update_available',
]

export function isGameLifecycleState(value: string): value is GameLifecycleState {
  return (VALID_STATES as readonly string[]).includes(value)
}

export function canPerformAction(state: GameLifecycleState, action: LifecycleAction): boolean {
  switch (action) {
    case 'download':
      return state === 'not_downloaded'
    case 'install':
      return state === 'downloaded'
    case 'update':
      return state === 'update_available'
    case 'uninstall':
      return state === 'downloaded' || state === 'installed' || state === 'update_available'
    default: {
      const _exhaustive: never = action
      return _exhaustive
    }
  }
}

export function transitionLifecycle(
  state: GameLifecycleState,
  action: LifecycleAction,
): GameLifecycleState {
  if (!canPerformAction(state, action)) {
    throw new Error(`Cannot ${action} from state ${state}`)
  }

  switch (state) {
    case 'not_downloaded':
      if (action === 'download') {
        return 'downloaded'
      }
      break
    case 'downloaded':
      if (action === 'install') {
        return 'installed'
      }
      if (action === 'uninstall') {
        return 'not_downloaded'
      }
      break
    case 'installed':
      if (action === 'uninstall') {
        return 'downloaded'
      }
      break
    case 'update_available':
      if (action === 'update') {
        return 'installed'
      }
      if (action === 'uninstall') {
        return 'downloaded'
      }
      break
    default: {
      const _exhaustive: never = state
      return _exhaustive
    }
  }

  throw new Error(`Unhandled transition: ${action} from ${state}`)
}

/** External signal when server freshness inbox marks a game behind. */
export function markUpdateAvailable(state: GameLifecycleState): GameLifecycleState {
  if (state === 'installed') {
    return 'update_available'
  }
  return state
}

export interface GameLifecycleRecord {
  gameUuid: string
  state: GameLifecycleState
}

export interface LifecycleRegistryOptions {
  initial?: GameLifecycleRecord[]
  onChange?: (records: GameLifecycleRecord[]) => void | Promise<void>
  onPersistenceError?: (error: unknown) => void
}

export function createLifecycleRegistry(options: LifecycleRegistryOptions = {}) {
  const byUuid = new Map<string, GameLifecycleState>()

  for (const record of options.initial ?? []) {
    byUuid.set(record.gameUuid, record.state)
  }

  const notify = (): void => {
    const pending = options.onChange?.(
      [...byUuid.entries()].map(([gameUuid, state]) => ({ gameUuid, state })),
    )
    if (pending && typeof pending.then === 'function') {
      void pending.catch((error: unknown) => {
        try {
          options.onPersistenceError?.(error)
        } catch (reportError) {
          console.error('[lifecycle] persistence error reporter failed', reportError)
        }
      })
    }
  }

  return {
    get(gameUuid: string): GameLifecycleState {
      return byUuid.get(gameUuid) ?? 'not_downloaded'
    },

    apply(gameUuid: string, action: LifecycleAction): GameLifecycleState {
      const next = transitionLifecycle(this.get(gameUuid), action)
      byUuid.set(gameUuid, next)
      notify()
      return next
    },

    signalUpdateAvailable(gameUuid: string): GameLifecycleState {
      const next = markUpdateAvailable(this.get(gameUuid))
      byUuid.set(gameUuid, next)
      notify()
      return next
    },

    hydrate(records: GameLifecycleRecord[]): void {
      byUuid.clear()
      for (const record of records) {
        byUuid.set(record.gameUuid, record.state)
      }
      notify()
    },

    /** Add server records without wiping local entries (local wins on conflict). */
    merge(records: GameLifecycleRecord[]): void {
      for (const record of records) {
        if (!byUuid.has(record.gameUuid)) {
          byUuid.set(record.gameUuid, record.state)
        }
      }
      notify()
    },

    snapshot(): GameLifecycleRecord[] {
      return [...byUuid.entries()].map(([gameUuid, state]) => ({ gameUuid, state }))
    },
  }
}

export type LifecycleRegistry = ReturnType<typeof createLifecycleRegistry>
