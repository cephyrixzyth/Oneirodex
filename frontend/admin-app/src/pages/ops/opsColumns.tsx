import { type DataTableColumn } from '../../components/DataTable'
import { formatScanJobCounters } from '../../components/opsWidgets'

/* Detail-panel registry, column tables and DetailPanel moved out of OpsPage (v11 cycle, H-D.2), unchanged. */

export const DETAIL_PANELS: Record<string, string> = {
  system: 'System',
  database: 'Database',
  logs: 'Logs',
  config: 'Configuration',
  theme_assets: 'Theme assets',
}

export const DETAIL_PANEL_IDS = Object.keys(DETAIL_PANELS)

export const COMPANION_KIND_COLUMNS: DataTableColumn[] = [
  { key: 'kind', label: 'Kind' },
  { key: 'online', label: 'Online', align: 'right' },
  { key: 'registered', label: 'Registered', align: 'right' },
]

/* TC-4 (v11 H-T): the device list under the Companions tile. `online` is the
 * server's verdict on the same window the tile counts with. */
export const DEVICE_COLUMNS: DataTableColumn[] = [
  {
    key: 'online',
    label: 'Status',
    render: (row) => (
      <span className={row.online ? 'od-badge od-badge--good' : 'od-badge od-badge--muted'}>
        {row.online ? 'Online' : 'Offline'}
      </span>
    ),
    value: (row) => (row.online ? 'online' : 'offline'),
  },
  { key: 'device_kind', label: 'Kind' },
  {
    key: 'device_name',
    label: 'Name',
    render: (row) => row.device_name || <span className="od-admin-muted">—</span>,
  },
  { key: 'user_name', label: 'Member' },
  { key: 'client_version', label: 'Version', render: (row) => row.client_version || '—' },
  {
    key: 'last_seen_at',
    label: 'Last seen',
    render: (row) => (row.last_seen_at ? new Date(row.last_seen_at).toLocaleString() : '—'),
    value: (row) => row.last_seen_at || '',
  },
]

export const SCAN_JOB_COLUMNS: DataTableColumn[] = [
  {
    key: 'id',
    label: 'Job',
    render: (job) => <code>#{job.id_short || job.id}</code>,
    value: (job) => job.id_short || job.id,
  },
  { key: 'library', label: 'Library', render: (job) => job.library || '—' },
  { key: 'status', label: 'Status' },
  {
    key: 'progress',
    label: 'Progress',
    render: (job) => formatScanJobCounters(job),
    value: (job) => Number(job.folders_success ?? 0) + Number(job.folders_failed ?? 0),
  },
  {
    key: 'detail',
    label: 'Detail',
    render: (job) => {
      if (job.error_message) {
        return <span className="od-ops-table__error">{job.error_message}</span>
      }
      if (job.stalled) {
        return <span className="od-ops-table__muted">No progress reported</span>
      }
      return <span className="od-ops-table__muted">{job.current_processing || '—'}</span>
    },
  },
]

export const RECENT_ERROR_COLUMNS: DataTableColumn[] = [
  { key: 'event_type', label: 'Type', render: (event) => <code>{event.event_type}</code> },
  { key: 'text', label: 'Message' },
]

/**
 * A key/value block in the Ops console. Board drag replaces ↑↓ reorder.
 */
export function DetailPanel({
  title,
  values,
}: {
  title: string
  values?: Record<string, unknown>
}) {
  const entries = Object.entries(values || {})
  if (entries.length === 0) return null

  return (
    <section className="od-ops-panel od-ops-panel--embedded">
      <div className="od-ops-panel__head">
        <h2>{title}</h2>
      </div>
      <table className="od-ops-table">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <td>{key}</td>
              <td>{formatDetailValue(key, value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** Render known Ops structures deliberately; never leak an arbitrary object or secret field. */
export function formatDetailValue(key: string, value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value !== 'object' || Array.isArray(value)) return 'Details available'

  const row = value as Record<string, unknown>
  if (
    typeof row.path === 'string' &&
    typeof row.exists === 'boolean' &&
    typeof row.read === 'boolean' &&
    typeof row.write === 'boolean'
  ) {
    return `${row.path} · ${row.exists ? 'exists' : 'missing'} · ${row.read ? 'readable' : 'not readable'} · ${row.write ? 'writable' : 'read-only'}`
  }
  if (
    key === 'latest' &&
    typeof row.text === 'string' &&
    typeof row.level === 'string' &&
    typeof row.type === 'string'
  ) {
    return [row.timestamp, row.level, row.type, row.text]
      .filter(
        (part): part is string | number => typeof part === 'string' || typeof part === 'number',
      )
      .join(' · ')
  }
  return 'Details available'
}
