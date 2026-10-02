import { useCallback, useEffect, useRef, useState } from 'react'
import { confirmAction } from '@oneirodex/ui'
import {
  cancelStoreSync,
  connectStore,
  disconnectStore,
  fetchOwnershipConnections,
  importCsv,
  importPlayniteFile,
  syncStore,
  type StoreConnection,
  type StoreConnectionsResponse,
  type StoreImportResponse,
} from '../../api/ownership'
import { useListFocusNavigation } from '../../hooks/useListFocusNavigation'
import { PageStatus } from '../PageStatus'
import { StoreConnectionCard, type CardMessage } from './StoreConnectionCard'
import { apiErrorInfo } from './apiErrorInfo'
import './StoreConnections.css'

/** While a sync runs, how often the list re-reads its status for progress. */
export const SYNC_POLL_MS = 2000

const LIVE_STATES = new Set([
  'not_connected',
  'needs_credential',
  'connected',
  'syncing',
  'partial',
  'reauth_required',
  'failed',
  'cancelled',
])

type Props = {
  /** first-run shows the same list with a lighter frame; the contract is identical. */
  variant?: 'settings' | 'first-run'
  /** Called with every fresh status read (first-run uses it to enable "Continue"). */
  onStatus?: (status: StoreConnectionsResponse) => void
  /** Progress re-read interval while a sync runs. */
  pollMs?: number
}

/**
 * The one store-connection list (LIB-02). First-run (`/welcome`) and Settings
 * (`/ownership`) both render this, reading `/api/ownership/connections`, so a
 * state, a sentence or an action can never differ between the two.
 */
export function StoreConnections({ variant = 'settings', onStatus, pollMs = SYNC_POLL_MS }: Props) {
  const [status, setStatus] = useState<StoreConnectionsResponse | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [busy, setBusy] = useState<Record<string, string>>({})
  const [messages, setMessages] = useState<Record<string, CardMessage>>({})
  const rootRef = useRef<HTMLDivElement | null>(null)
  const onStatusRef = useRef(onStatus)
  onStatusRef.current = onStatus
  // The list root only exists once status has loaded and sync is on.
  useListFocusNavigation(rootRef, Boolean(status?.sync_enabled))

  const refresh = useCallback(
    async (signal?: AbortSignal): Promise<StoreConnectionsResponse | null> => {
      try {
        const next = await fetchOwnershipConnections({ signal })
        setStatus(next)
        setLoadError(null)
        onStatusRef.current?.(next)
        return next
      } catch (error) {
        if (!apiErrorInfo(error).aborted) setLoadError(error)
        return null
      }
    },
    [],
  )

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  const syncing =
    Object.values(busy).includes('sync') ||
    Boolean(status?.connections.some((c) => c.state === 'syncing'))
  useEffect(() => {
    if (!syncing) return undefined
    const timer = window.setInterval(() => refresh(), pollMs)
    return () => window.clearInterval(timer)
  }, [syncing, refresh, pollMs])

  const say = (store: string, message: CardMessage) =>
    setMessages((c) => ({ ...c, [store]: message }))
  const setBusyFor = (store: string, action: string | null) =>
    setBusy((c) => {
      const next = { ...c }
      if (action) next[store] = action
      else delete next[store]
      return next
    })

  async function run(
    connection: StoreConnection,
    action: string,
    work: () => Promise<CardMessage>,
  ) {
    setBusyFor(connection.provider, action)
    say(connection.provider, null)
    let ok = true
    try {
      say(connection.provider, await work())
    } catch (error) {
      ok = false
      // The server sends catalogue sentences only; apiErrorInfo prefers them.
      say(connection.provider, { tone: 'bad', text: apiErrorInfo(error).message })
    } finally {
      setBusyFor(connection.provider, null)
      await refresh()
    }
    return ok
  }

  const handlers = (connection: StoreConnection) => ({
    onSync: () =>
      run(connection, 'sync', async () => {
        const result = await syncStore(connection.provider)
        const job = result?.job
        if (job?.status === 'cancelled')
          return { tone: 'info', text: 'Sync stopped. Nothing was saved.' }
        if (job?.status === 'partial')
          return { tone: 'info', text: job.outcome?.message || 'Synced part of the list.' }
        return {
          tone: 'good',
          text: `Synced ${result?.synced ?? 0} titles (${result?.matched ?? 0} matched to your library).`,
        }
      }),
    onCancel: () =>
      run(connection, 'cancel', async () => {
        await cancelStoreSync(connection.provider)
        return {
          tone: 'info',
          text: 'Stopping at the next page. Nothing from this sync will be saved.',
        }
      }),
    onConnect: (fields: Record<string, string>) =>
      run(connection, 'connect', async () => {
        await connectStore(connection.provider, fields)
        const after = (await refresh())?.connections.find((c) => c.provider === connection.provider)
        if (after?.state === 'reauth_required' || after?.state === 'needs_credential') {
          return {
            tone: 'info',
            text: `${connection.name} link saved, but it still needs a working sign-in before it can sync.`,
          }
        }
        return {
          tone: 'good',
          text:
            `${connection.name} link saved.` +
            (after?.actions.includes('sync') ? ' Sync to read your library.' : ''),
        }
      }),
    onDisconnect: async () => {
      const confirmed = await confirmAction({
        title: connection.account.connected
          ? `Disconnect ${connection.name}?`
          : `Clear imported ${connection.name} titles?`,
        body: 'The link and the titles recorded from it are removed, along with your match decisions for them. Your games stay put.',
        confirmLabel: connection.account.connected ? 'Disconnect' : 'Clear titles',
        cancelLabel: 'Keep it',
      })
      if (!confirmed) return
      await run(connection, 'disconnect', async () => {
        await disconnectStore(connection.provider)
        return { tone: 'good', text: `${connection.name} removed.` }
      })
    },
    onImportCsv: ({ csv, file }: { csv: string; file: File | null }) => {
      if (!file && !csv.trim()) {
        say(connection.provider, { tone: 'bad', text: 'Paste some rows or choose a file first.' })
        return Promise.resolve(false)
      }
      return run(connection, 'import', async () => {
        const result: StoreImportResponse = await importCsv(connection.provider, { csv, file })
        const skipped = result?.skipped ? `, ${result.skipped} skipped` : ''
        return {
          tone: 'good',
          text: `Imported ${result?.imported ?? 0} titles (${result?.matched ?? 0} matched${skipped}).`,
        }
      })
    },
    onImportFile: (file: File) =>
      run(connection, 'import', async () => {
        const result = await importPlayniteFile(file)
        return {
          tone: 'good',
          text: `Imported ${result?.imported ?? 0} titles (${result?.matched ?? 0} matched).`,
        }
      }),
  })

  if (loadError && !status) {
    return (
      <PageStatus
        error={loadError}
        errorMessage="Unable to load your store connections."
        onRetry={() => refresh()}
      />
    )
  }
  if (!status) {
    return <PageStatus loading loadingMessage="Loading your stores" />
  }
  if (!status.sync_enabled) {
    return (
      <p className="od-store-list__empty">Store ownership is turned off by your administrator.</p>
    )
  }

  // First-run nests this list under its own step headings.
  const GroupTitle = variant === 'first-run' ? 'h3' : 'h2'
  const cardTitle = variant === 'first-run' ? 'h4' : 'h3'
  const live = status.connections.filter((c) => LIVE_STATES.has(c.state))
  const imports = status.connections.filter(
    (c) => c.state === 'import_only' || c.state === 'not_configured',
  )
  const unavailable = status.connections.filter((c) => c.state === 'unavailable')
  const card = (connection: StoreConnection) => (
    <StoreConnectionCard
      key={connection.provider}
      connection={connection}
      busy={busy[connection.provider] ?? null}
      message={messages[connection.provider] ?? null}
      titleTag={cardTitle}
      {...handlers(connection)}
    />
  )

  return (
    <div ref={rootRef} className="od-store-list" data-variant={variant}>
      {live.length ? (
        <section className="od-store-list__group" aria-labelledby="od-store-live">
          <GroupTitle id="od-store-live" className="od-store-list__title">
            Keep in sync
          </GroupTitle>
          <p className="od-store-list__lede">
            Linked stores refresh on their own. Nothing is ever downloaded or installed.
          </p>
          <ul className="od-store-list__cards">{live.map(card)}</ul>
        </section>
      ) : null}
      {imports.length ? (
        <section className="od-store-list__group" aria-labelledby="od-store-import">
          <GroupTitle id="od-store-import" className="od-store-list__title">
            Import a list
          </GroupTitle>
          <p className="od-store-list__lede">
            A one-time snapshot. Import again whenever your list changes.
          </p>
          <ul className="od-store-list__cards">{imports.map(card)}</ul>
        </section>
      ) : null}
      {unavailable.length ? (
        <p className="od-store-list__unavailable">
          Not available yet: {unavailable.map((c) => c.name).join(', ')}. Oneirodex has no way to
          read these stores, so nothing is offered for them.
        </p>
      ) : null}
    </div>
  )
}
