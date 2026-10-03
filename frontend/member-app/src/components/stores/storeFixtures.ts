import type { StoreConnection, StoreSyncJob } from '../../api/ownership'

/** Test builders for the `/api/ownership/connections` contract. */
export function job(overrides: Partial<StoreSyncJob> = {}): StoreSyncJob {
  return {
    id: 1,
    store: 'gog',
    trigger: 'member',
    status: 'succeeded',
    outcome: null,
    cancellable: true,
    cancel_requested: false,
    progress: { pages: 0, items_seen: 0 },
    synced: 3,
    matched: 1,
    started_at: '2026-09-28T10:00:00Z',
    heartbeat_at: '2026-09-28T10:00:05Z',
    finished_at: '2026-09-28T10:00:05Z',
    ...overrides,
  }
}

export function connection(
  provider: string,
  overrides: Partial<StoreConnection> = {},
): StoreConnection {
  return {
    provider,
    name:
      {
        steam: 'Steam',
        gog: 'GOG',
        epic: 'Epic Games',
        meta_quest: 'Meta Quest',
        playnite: 'Playnite',
        heroic: 'Heroic',
        humble: 'Humble Bundle',
      }[provider] || provider,
    authority: 'unofficial',
    state: 'not_connected',
    live: true,
    cancellable: ['gog', 'epic', 'amazon'].includes(provider),
    setup: { ready: true, missing: null },
    credential: { source: 'none', household_available: false },
    account: { connected: false, linked_at: null, updated_at: null, external_account_id: null },
    records: { owned: 0, matched: 0, needs_review: 0, last_recorded_at: null },
    last_sync: null,
    previous_failure: null,
    actions: ['connect', 'import_csv'],
    ...overrides,
  }
}

export function connectionsBody(connections: StoreConnection[], syncEnabled = true) {
  return {
    ok: true,
    error: null,
    error_code: null,
    schema_version: 1,
    sync_enabled: syncEnabled,
    connections,
  }
}
