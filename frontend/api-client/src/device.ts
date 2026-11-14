import type { Requester } from './client.js'

/**
 * Client seat kinds the server recognises on `/api/client/*`.
 *
 * Mirrors `DEVICE_KINDS` in `oneirodex/utils/client_capabilities.py`. The server
 * defaults an omitted kind to `companion` for back-compat, which is why every
 * client must send its own kind explicitly — a thin seat that says nothing is
 * indistinguishable from a companion in the Ops device list.
 */
export type DeviceKind = 'companion' | 'thin' | 'browser'

/** Capability advertisement — what this seat may and may not do. */
export interface ClientCapabilities {
  device_kind: DeviceKind
  allows: string[]
  denies: string[]
}

export interface HeartbeatRequest {
  device_id: string
  device_kind?: DeviceKind
  device_name?: string
  client_version?: string
}

/** Queued companion command as delivered on the heartbeat response. */
export interface RawCompanionCommand {
  id?: string
  game_uuid?: string
  action?: string
  created_at?: string
  kind?: string
  version_uuid?: string
  path?: string
  select?: boolean
}

export interface HeartbeatResponse extends Partial<ClientCapabilities> {
  device_id: string
  device_name: string | null
  client_version: string | null
  last_seen_at: string | null
  /** Empty for any seat the server will not deliver install commands to. */
  commands?: RawCompanionCommand[]
}

export interface ClientAccountIdentity {
  account_id: string
}

export function createDeviceApi(request: Requester) {
  return {
    /** Stable account ID for binding a local companion cache to this server identity. */
    identity(): Promise<ClientAccountIdentity> {
      return request<ClientAccountIdentity>('/api/client/identity')
    },

    /** Presence ping. Companion seats also collect queued install commands here. */
    heartbeat(body: HeartbeatRequest): Promise<HeartbeatResponse> {
      return request<HeartbeatResponse>('/api/client/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    },

    /** Allows/denies for a seat, without registering presence. */
    capabilities(deviceKind?: DeviceKind): Promise<ClientCapabilities> {
      const query = deviceKind ? `?device_kind=${encodeURIComponent(deviceKind)}` : ''
      return request<ClientCapabilities>(`/api/client/capabilities${query}`)
    },

    /** Report a batch of commands as handled. */
    ackCommands(ids: string[]): Promise<unknown> {
      return request('/api/client/commands/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
    },

    /** Return a batch of commands to `pending` (busy / failed / offline). */
    nackCommands(ids: string[]): Promise<unknown> {
      return request('/api/client/commands/nack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      })
    },
  }
}

export type DeviceApi = ReturnType<typeof createDeviceApi>
