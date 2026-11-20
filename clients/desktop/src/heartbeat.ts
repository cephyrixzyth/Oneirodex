import { type DeviceKind, type RawCompanionCommand } from '@oneirodex/api-client'

import { createAuthStore, type AuthStore } from './auth.js'
import { createDesktopApi } from './api.js'
import { isConnectionUnavailable } from './connect.js'
import type { LifecycleAction } from './lifecycle.js'
import { sha256Fingerprint } from './offline-shelf.js'
import { CLIENT_VERSION } from './version.js'

const DEVICE_ID_STORAGE_KEY = 'oneirodex-device-id'

export type { DeviceKind }

function deviceApi(auth: AuthStore, fetchImpl?: typeof fetch) {
  return createDesktopApi(auth, fetchImpl).device
}

export function getOrCreateDeviceId(): string {
  if (typeof localStorage === 'undefined') {
    return crypto.randomUUID()
  }

  const existing = localStorage.getItem(DEVICE_ID_STORAGE_KEY)
  if (existing) {
    return existing
  }

  const created = crypto.randomUUID()
  localStorage.setItem(DEVICE_ID_STORAGE_KEY, created)
  return created
}

export interface HeartbeatOptions {
  renewLease?: string

  deviceName?: string
  clientVersion?: string
  deviceId?: string
  /**
   * Seat kind reported to the server. The server defaults an omitted kind to
   * `companion`, so a thin seat that leaves this unset is indistinguishable
   * from a companion in the Ops device list — always pass it explicitly.
   */
  deviceKind?: DeviceKind
  fetchImpl?: typeof fetch
  /** Consecutive failed heartbeats before onUnreachable (default 2). */
  unreachableAfterFailures?: number
  /** Fires once when a heartbeat succeeds after connect / after being unreachable. */
  onReachable?: () => void | Promise<void>
  /** Fires once after unreachableAfterFailures consecutive failures. */
  onUnreachable?: (error: unknown) => void
  /** Denial, refused redirect, invalid response or other non-outage failure. */
  onFailure?: (error: unknown) => void
}

export type CompanionCommandAction =
  LifecycleAction | 'apply_patch' | 'apply_mod_pack' | 'open_path'

export interface CompanionCommand {
  lease_id?: string
  id: string
  /** Present for install lifecycle commands; may be empty for unmatched open_path. */
  game_uuid: string
  action: CompanionCommandAction
  created_at?: string
  kind?: 'base' | 'update' | 'extra'
  version_uuid?: string
  /** Absolute OS path for open_path (library folder / unmatched / local install). */
  path?: string
  /** When true (default), select the item in its parent folder if it is a file. */
  select?: boolean
}

export type CompanionCommandResult = 'ok' | 'busy' | 'error'

export type CompanionCommandHandler = (
  command: CompanionCommand,
) => CompanionCommandResult | Promise<CompanionCommandResult | void>

function isCompanionCommandAction(value: string): value is CompanionCommandAction {
  return (
    value === 'download' ||
    value === 'install' ||
    value === 'update' ||
    value === 'uninstall' ||
    value === 'apply_patch' ||
    value === 'apply_mod_pack' ||
    value === 'open_path'
  )
}

async function postCommandResult(
  auth: AuthStore,
  command: CompanionCommand,
  result: CompanionCommandResult,
  deviceId: string,
  fetchImpl?: typeof fetch,
): Promise<void> {
  const device = deviceApi(auth, fetchImpl)
  const lease = command.lease_id ? { device_id: deviceId, lease_id: command.lease_id } : undefined
  const response =
    result === 'ok'
      ? await device.ackCommands([command.id], lease)
      : await device.nackCommands([command.id], lease ? { ...lease, result } : undefined)
  if (
    lease &&
    response &&
    typeof response === 'object' &&
    (('removed' in response && response.removed === 0) ||
      ('released' in response && response.released === 0))
  ) {
    throw new Error('Command lease changed before acknowledgement')
  }
}

export async function postClientHeartbeat(
  auth: AuthStore,
  options: HeartbeatOptions = {},
): Promise<CompanionCommand[]> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return []
  }

  const data = await deviceApi(auth, options.fetchImpl).heartbeat({
    device_id: options.deviceId ?? getOrCreateDeviceId(),
    command_protocol: 2,
    ...(options.renewLease ? { renew_lease: options.renewLease } : {}),
    device_kind: options.deviceKind ?? 'companion',
    device_name: options.deviceName ?? 'Oneirodex Desktop',
    client_version: options.clientVersion ?? CLIENT_VERSION,
  })

  const raw: RawCompanionCommand[] = Array.isArray(data?.commands) ? data.commands : []
  const parsed: CompanionCommand[] = []
  for (const row of raw) {
    if (!row || typeof row !== 'object') {
      continue
    }
    const record = row as Record<string, unknown>
    const action = String(record.action || '')
    const gameUuid = String(record.game_uuid || '').trim()
    const path = record.path != null ? String(record.path).trim() : ''
    if (!isCompanionCommandAction(action)) {
      continue
    }
    // Lifecycle commands need a game uuid; open_path needs an absolute path.
    if (action === 'open_path') {
      if (!path) {
        continue
      }
      parsed.push({
        id: String(record.id || crypto.randomUUID()),
        ...(typeof record.lease_id === 'string' ? { lease_id: record.lease_id } : {}),
        game_uuid: gameUuid,
        action,
        path,
        select: record.select === false ? false : true,
        created_at: record.created_at ? String(record.created_at) : undefined,
      })
      continue
    }
    if (!gameUuid) {
      continue
    }
    parsed.push({
      id: String(record.id || crypto.randomUUID()),
      ...(typeof record.lease_id === 'string' ? { lease_id: record.lease_id } : {}),
      game_uuid: gameUuid,
      action,
      created_at: record.created_at ? String(record.created_at) : undefined,
      kind:
        record.kind === 'base' || record.kind === 'update' || record.kind === 'extra'
          ? record.kind
          : undefined,
      version_uuid: record.version_uuid ? String(record.version_uuid) : undefined,
    })
  }
  return parsed
}

export interface HeartbeatScheduler {
  stop(): void
}

export function startClientHeartbeat(
  auth: AuthStore,
  options: HeartbeatOptions & {
    intervalMs?: number
    onCommands?: CompanionCommandHandler
  } = {},
): HeartbeatScheduler {
  const intervalMs = options.intervalMs ?? 60_000
  const unreachableAfter = Math.max(1, options.unreachableAfterFailures ?? 2)
  let timer: ReturnType<typeof setInterval> | undefined
  let inFlight = false
  let failureStreak = 0
  let reportedUnreachable = false
  let reachableAnnounced = false
  let stopped = false
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  const revision = auth.getRevision()
  const requestAuth = createAuthStore({ baseUrl, token })
  const deviceId = options.deviceId ?? getOrCreateDeviceId()
  let runningLease = ''
  let renewalInFlight = false
  const outcomes = new Map<string, CompanionCommandResult>()
  let receiptKey: Promise<string | null> | undefined
  function receiptStore(): Promise<string | null> {
    receiptKey ??= sha256Fingerprint(JSON.stringify([baseUrl, token, deviceId]))
      .then((id) => 'oneirodex-companion-results-v1:' + id)
      .catch(() => null)
    return receiptKey
  }
  function receipts(key: string | null): Record<string, 'ok' | 'error'> {
    try {
      return key ? JSON.parse(localStorage.getItem(key) || '{}') || {} : {}
    } catch {
      return {}
    }
  }
  function writeReceipt(key: string | null, id: string, result?: 'ok' | 'error') {
    if (!key) return
    try {
      const rows = receipts(key)
      if (result) rows[id] = result
      else delete rows[id]
      localStorage.setItem(key, JSON.stringify(Object.fromEntries(Object.entries(rows).slice(-64))))
    } catch {
      /* An unavailable local store still leaves this session's receipt. */
    }
  }
  const isCurrent = () =>
    !stopped &&
    auth.getRevision() === revision &&
    auth.getBaseUrl() === baseUrl &&
    auth.getToken() === token

  const tick = (): void => {
    if (!isCurrent()) return
    if (inFlight) {
      if (runningLease && !renewalInFlight) {
        renewalInFlight = true
        void postClientHeartbeat(requestAuth, { ...options, deviceId, renewLease: runningLease })
          .catch(() => undefined)
          .finally(() => {
            renewalInFlight = false
          })
      }
      return
    }
    inFlight = true
    const fetchImpl = options.fetchImpl
    void postClientHeartbeat(requestAuth, { ...options, deviceId })
      .then(async (commands) => {
        if (!isCurrent()) return
        failureStreak = 0
        if (!reachableAnnounced || reportedUnreachable) {
          await options.onReachable?.()
          if (!isCurrent()) return
          reportedUnreachable = false
          reachableAnnounced = true
        }
        if (!options.onCommands || commands.length === 0) {
          return
        }
        for (const command of commands) {
          if (!isCurrent()) return
          runningLease = command.lease_id || ''
          const receipt = command.lease_id ? await receiptStore() : null
          if (!isCurrent()) return
          let result: CompanionCommandResult = 'ok'
          try {
            const handlerResult =
              outcomes.get(command.id) ??
              receipts(receipt)[command.id] ??
              (await options.onCommands(command))
            if (handlerResult === 'busy' || handlerResult === 'error' || handlerResult === 'ok') {
              result = handlerResult
            }
          } catch {
            result = 'error'
          }
          if (!isCurrent()) return
          try {
            // A lost acknowledgement may redeliver the same command to this session.
            if (result !== 'busy') {
              outcomes.set(command.id, result)
              writeReceipt(receipt, command.id, result)
            }
            await postCommandResult(requestAuth, command, result, deviceId, fetchImpl)
            outcomes.delete(command.id)
            writeReceipt(receipt, command.id)
          } catch {
            // Retain the completed result until an acknowledgement succeeds.
          } finally {
            runningLease = ''
          }
        }
      })
      .catch((error) => {
        if (!isCurrent()) return
        if (!isConnectionUnavailable(error)) {
          failureStreak = 0
          reachableAnnounced = false
          options.onFailure?.(error)
          return
        }
        failureStreak += 1
        if (!reportedUnreachable && failureStreak >= unreachableAfter) {
          reportedUnreachable = true
          reachableAnnounced = false
          options.onUnreachable?.(error)
        }
      })
      .finally(() => {
        inFlight = false
      })
  }

  tick()
  timer = setInterval(tick, intervalMs)

  return {
    stop() {
      stopped = true
      if (timer !== undefined) {
        clearInterval(timer)
        timer = undefined
      }
    },
  }
}
