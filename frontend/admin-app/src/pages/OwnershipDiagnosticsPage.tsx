import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from '../components/DataTable'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import './OwnershipDiagnosticsPage.css'

/**
 * Store connection diagnostics and repair (LIB-04 / LIB-02).
 *
 * Reads `/api/admin/ownership/connections`: each member's connection state,
 * the redacted reason of the last sync, record counts and which kind of
 * sign-in a sync would use. Never a credential, an external account ID or a
 * member's title list. Retry runs a sync with the member's own saved sign-in;
 * cancel is offered only where the server says a sync can stop.
 */

const STATE_LABEL: Record<string, string> = {
  unavailable: 'Not available',
  disabled: 'Turned off',
  import_only: 'Import only',
  not_configured: 'Needs server setup',
  not_connected: 'Not linked',
  needs_credential: 'Needs a sign-in',
  connected: 'Linked',
  syncing: 'Syncing',
  partial: 'Partly synced',
  reauth_required: 'Reconnect needed',
  failed: 'Sync failed',
  cancelled: 'Sync cancelled',
}
const STATE_TONE: Record<string, string> = {
  connected: 'good',
  syncing: 'info',
  partial: 'warn',
  needs_credential: 'warn',
  not_configured: 'warn',
  reauth_required: 'bad',
  failed: 'bad',
  cancelled: 'warn',
}
const SOURCE_LABEL: Record<string, string> = {
  member: 'Member sign-in',
  household: 'Household sign-in',
  unknown: 'Unknown (saved before upgrade)',
  none: 'None',
  not_required: 'Not needed',
}

type Outcome = { reason: string; message: string; audience: string }
type StoreDiag = {
  provider: string
  name: string
  state: string
  credential: { source: string }
  records: { owned: number; matched: number; needs_review: number }
  last_sync: { outcome: Outcome | null } | null
  previous_failure: { outcome: Outcome | null } | null
  admin_actions?: string[]
}
type MemberDiag = { user_id: number; name: string; stores: StoreDiag[] }
type Diagnostics = {
  household?: {
    sync_enabled?: boolean
    steam_server_key?: boolean
    unofficial_opt_in?: string[]
    household_tokens?: Record<string, boolean>
  }
  members?: MemberDiag[]
  next_after_id: number | null
  stale_running_jobs?: number
}

type Row = {
  key: string
  user_id: number
  member: string
  store: string
  storeName: string
  state: string
  reason: string
  audience: string
  owned: number
  matched: number
  review: number
  source: string
  actions: string[]
}

function fetchPage(after: number): Promise<Diagnostics> {
  return getJson(`/api/admin/ownership/connections?after_id=${after}`)
}

function rowsFrom(members: MemberDiag[]): Row[] {
  return members.flatMap((member) =>
    (member.stores || []).map((s) => {
      const outcome = s.last_sync?.outcome || s.previous_failure?.outcome || null
      return {
        key: `${member.user_id}:${s.provider}`,
        user_id: member.user_id,
        member: member.name,
        store: s.provider,
        storeName: s.name,
        state: s.state,
        reason: outcome ? outcome.message : '',
        audience: outcome ? outcome.audience : '',
        owned: s.records.owned,
        matched: s.records.matched,
        review: s.records.needs_review,
        source: s.credential.source,
        actions: s.admin_actions || [],
      }
    }),
  )
}

export function OwnershipDiagnosticsPage() {
  const [data, setData] = useState<Diagnostics | null>(null)
  const [members, setMembers] = useState<MemberDiag[]>([])
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  // Pages of members on screen, so a repair re-reads all of them and the
  // member just repaired (perhaps on page 2) stays in view.
  const pagesShown = useRef(1)

  const load = useCallback(async (after = 0, append = false) => {
    try {
      const next = await fetchPage(after)
      pagesShown.current = append ? pagesShown.current + 1 : 1
      // Stale jobs are counted per page; the notice covers every page shown.
      setData((current) => ({
        ...next,
        stale_running_jobs:
          (append ? current?.stale_running_jobs || 0 : 0) + (next.stale_running_jobs || 0),
      }))
      setMembers((current) => (append ? [...current, ...(next.members || [])] : next.members || []))
      setError(null)
    } catch (err) {
      // The page already shows data: say so, instead of an error nobody sees.
      if (append) showToast(errorText(err) || 'Unable to load more members.', 'error')
      else setError(err)
    }
  }, [])

  const reloadShown = useCallback(async () => {
    try {
      let after = 0
      let stale = 0
      let shown = 0
      let page: Diagnostics | null = null
      const all: MemberDiag[] = []
      while (shown < pagesShown.current) {
        page = await fetchPage(after)
        shown += 1
        all.push(...(page.members || []))
        stale += page.stale_running_jobs || 0
        if (page.next_after_id == null) break
        after = page.next_after_id
      }
      if (page) {
        pagesShown.current = shown
        setData({ ...page, stale_running_jobs: stale })
        setMembers(all)
      }
      setError(null)
    } catch (err) {
      showToast(errorText(err) || 'Unable to refresh the list; it may be out of date.', 'error')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function act(row: Row, action: 'sync' | 'cancel') {
    setBusy(row.key)
    try {
      const result = await postJson(
        `/api/admin/ownership/connections/${row.user_id}/${row.store}/${action}`,
      )
      const status = result?.job?.status
      showToast(
        action === 'cancel'
          ? `Asked ${row.member}'s ${row.storeName} sync to stop.`
          : `${row.member}'s ${row.storeName} sync ${status === 'partial' ? 'finished with a partial list' : 'finished'}.`,
        'success',
      )
    } catch (err) {
      // The server sends catalogue sentences only; no provider text.
      showToast(errorText(err) || 'The repair action failed.', 'error')
    } finally {
      setBusy(null)
      reloadShown()
    }
  }

  /** One page at a time: a double click must not list a page twice. */
  async function showMore() {
    if (loadingMore || !data?.next_after_id) return
    setLoadingMore(true)
    try {
      await load(data.next_after_id, true)
    } finally {
      setLoadingMore(false)
    }
  }

  if (error && !data) {
    return (
      <div className="od-admin-page">
        <h1>Store connections</h1>
        <PageStatus
          error
          errorMessage="Unable to load store connection diagnostics."
          onRetry={() => load()}
        />
      </div>
    )
  }
  if (!data) {
    return (
      <div className="od-admin-page">
        <PageStatus loading loadingMessage="Loading store connections" />
      </div>
    )
  }

  const household = data.household || {}
  const nextAfter = data.next_after_id
  const rows = rowsFrom(members)
  const columns: DataTableColumn[] = [
    { key: 'member', label: 'Member', sortable: true, filterable: true },
    { key: 'storeName', label: 'Store', sortable: true, filterable: true },
    {
      key: 'state',
      label: 'State',
      sortable: true,
      value: (r) => STATE_LABEL[r.state] || r.state,
      render: (r) => (
        <span className="od-own-diag__badge" data-tone={STATE_TONE[r.state] || 'muted'}>
          {STATE_LABEL[r.state] || r.state}
        </span>
      ),
    },
    {
      key: 'reason',
      label: 'Last result',
      render: (r) =>
        r.reason ? (
          <span>
            {r.reason}
            {r.audience === 'admin' ? (
              <strong className="od-own-diag__fix"> · Admin can fix</strong>
            ) : null}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'owned',
      label: 'Titles',
      align: 'right',
      sortable: true,
      render: (r) =>
        `${r.owned} · ${r.matched} matched${r.review ? ` · ${r.review} to review` : ''}`,
    },
    {
      key: 'source',
      label: 'Sign-in',
      value: (r) => SOURCE_LABEL[r.source] || r.source,
      render: (r) => SOURCE_LABEL[r.source] || r.source,
    },
    {
      key: 'actions',
      label: 'Repair',
      render: (r) =>
        r.actions.includes('cancel') ? (
          <Button
            size="sm"
            variant="danger"
            disabled={busy === r.key}
            onClick={() => act(r, 'cancel')}
          >
            Stop sync
          </Button>
        ) : r.actions.includes('sync') ? (
          <Button size="sm" disabled={busy !== null} onClick={() => act(r, 'sync')}>
            {busy === r.key ? 'Syncing…' : 'Retry sync'}
          </Button>
        ) : (
          '—'
        ),
    },
  ]

  const tokens = Object.entries(household.household_tokens || {})
    .filter(([, present]) => present)
    .map(([store]) => store)
  return (
    <div className="od-admin-page od-own-diag">
      <h1>Store connections</h1>
      <p className="od-admin-lede">
        Each member’s store links, the last sync result and which sign-in it uses. Credentials,
        store account IDs and title lists are never shown here. Retry uses the member’s own saved
        sign-in.
      </p>
      <dl className="od-own-diag__household">
        <div>
          <dt>Store ownership</dt>
          <dd>{household.sync_enabled ? 'On' : 'Off'}</dd>
        </div>
        <div>
          <dt>Steam server key</dt>
          <dd>{household.steam_server_key ? 'Configured' : 'Not configured'}</dd>
        </div>
        <div>
          <dt>Unofficial live sync</dt>
          <dd>{(household.unofficial_opt_in || []).join(', ') || 'Off'}</dd>
        </div>
        <div>
          <dt>Household sign-ins</dt>
          <dd>{tokens.length ? tokens.join(', ') : 'None'}</dd>
        </div>
      </dl>
      {tokens.length ? (
        <p className="od-own-diag__warn">
          A household sign-in fills the register of every member who links that store without their
          own sign-in with the household account’s library. Rows marked “Household sign-in” below
          are using it.
        </p>
      ) : null}
      {data.stale_running_jobs ? (
        <p className="od-own-diag__warn">
          {data.stale_running_jobs} sync(s) stopped without finishing and show as interrupted.
        </p>
      ) : null}
      <DataTable
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.key}
        emptyMessage="No member has linked or imported a store yet."
        initialSort={{ key: 'member', dir: 'asc' }}
      />
      {nextAfter ? (
        <Button size="sm" disabled={loadingMore} onClick={showMore}>
          {loadingMore ? 'Loading…' : 'Show more members'}
        </Button>
      ) : null}
    </div>
  )
}
