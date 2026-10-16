import { invoke } from '@tauri-apps/api/core'

import { formatBearerAuthorization } from '@oneirodex/api-client'

import type { AuthStore } from './auth.js'
import {
  createLifecycleRegistry,
  isGameLifecycleState,
  type GameLifecycleRecord,
  type GameLifecycleState,
  type LifecycleRegistry,
} from './lifecycle.js'
import { isTauriRuntime } from './config-store.js'

interface RawLifecycleRecord {
  game_uuid: string
  state: string
}

interface RawLifecycleRegistryFile {
  records?: RawLifecycleRecord[]
}

function toRawRecords(records: GameLifecycleRecord[]): RawLifecycleRecord[] {
  return records.map((record) => ({
    game_uuid: record.gameUuid,
    state: record.state,
  }))
}

function fromRawRecords(records: RawLifecycleRecord[] | undefined): GameLifecycleRecord[] {
  if (!records) {
    return []
  }

  return records.flatMap((record) => {
    if (!isGameLifecycleState(record.state)) {
      return []
    }
    return [{ gameUuid: record.game_uuid, state: record.state }]
  })
}

export async function loadLifecycleRegistryFromDisk(): Promise<GameLifecycleRecord[]> {
  if (!isTauriRuntime()) {
    return []
  }

  const raw = await invoke<RawLifecycleRegistryFile>('load_lifecycle_registry')
  return fromRawRecords(raw.records)
}

export async function saveLifecycleRegistryToDisk(records: GameLifecycleRecord[]): Promise<void> {
  if (!isTauriRuntime()) {
    return
  }

  await invoke('save_lifecycle_registry', {
    registry: {
      records: toRawRecords(records),
    },
  })
}

/** Push local install states so the web library can show Install/Installed/filter. */
export async function syncLifecycleRegistryToServer(
  auth: AuthStore,
  records: GameLifecycleRecord[],
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return
  }

  try {
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/api/client/lifecycle`, {
      method: 'POST',
      redirect: 'error',
      headers: {
        Authorization: formatBearerAuthorization(token),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ records: toRawRecords(records) }),
    })
    if (!response.ok) {
      console.warn(`[lifecycle] sync failed: ${response.status}`)
    }
  } catch (err) {
    console.warn('[lifecycle] sync error', err)
  }
}

/** Pull server lifecycle and merge into local registry (local wins on conflict). */
export async function pullLifecycleRegistryFromServer(
  auth: AuthStore,
  registry: LifecycleRegistry,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return
  }

  try {
    const response = await fetchImpl(`${baseUrl.replace(/\/$/, '')}/api/client/lifecycle`, {
      method: 'GET',
      redirect: 'error',
      headers: {
        Authorization: formatBearerAuthorization(token),
      },
    })
    if (!response.ok) {
      console.warn(`[lifecycle] pull failed: ${response.status}`)
      return
    }
    const data = (await response.json()) as RawLifecycleRegistryFile
    registry.merge(fromRawRecords(data.records))
  } catch (err) {
    console.warn('[lifecycle] pull error', err)
  }
}

export interface PersistedLifecycleRegistryOptions {
  initial?: GameLifecycleRecord[]
  persist?: (records: GameLifecycleRecord[]) => void | Promise<void>
}

export function createPersistedLifecycleRegistry(
  options: PersistedLifecycleRegistryOptions = {},
): LifecycleRegistry {
  const registry = createLifecycleRegistry({
    initial: options.initial,
    onChange: (records) => {
      void options.persist?.(records)
    },
  })

  return registry
}

export async function hydrateLifecycleRegistry(auth?: AuthStore): Promise<LifecycleRegistry> {
  const initial = await loadLifecycleRegistryFromDisk()
  return createPersistedLifecycleRegistry({
    initial,
    persist: async (records) => {
      await saveLifecycleRegistryToDisk(records)
      if (auth) {
        await syncLifecycleRegistryToServer(auth, records)
      }
    },
  })
}

export type { GameLifecycleRecord, GameLifecycleState, LifecycleRegistry }
