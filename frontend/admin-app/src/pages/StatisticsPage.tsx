import { useEffect, useState } from 'react'
import { Button, DataTable, PageStatus, type DataTableColumn } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'
import './StatisticsPage.css'

type Series = { labels: string[]; data: number[] }
type Stats = {
  totals: Record<string, number>
  top_games_table: { name: string; downloads: number }[]
  downloads_per_user: Series
  top_games: Series
  download_trends: Series
  users_with_invites: Series
  top_downloaders: Series
  top_collectors: Series
}
const SERIES: { key: keyof Stats; title: string }[] = [
  { key: 'downloads_per_user', title: 'Downloads per user' },
  { key: 'top_games', title: 'Most downloaded titles' },
  { key: 'download_trends', title: 'Download trends (30 days)' },
  { key: 'users_with_invites', title: 'Invite tokens generated' },
  { key: 'top_downloaders', title: 'Top downloaders' },
  { key: 'top_collectors', title: 'Top game collectors' },
]
const columns: DataTableColumn[] = [
  { key: 'rank', label: '#', align: 'right' },
  { key: 'name', label: 'Title' },
  { key: 'downloads', label: 'Downloads', align: 'right' },
]
function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return 'n/a'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${unit ? size.toFixed(1) : size} ${units[unit]}`
}
function isSeries(value: unknown): value is Series {
  return Boolean(
    value &&
    typeof value === 'object' &&
    Array.isArray((value as Series).labels) &&
    Array.isArray((value as Series).data),
  )
}
export function StatisticsPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setFailed(false)
    setError('')
    getJson('/api/admin/statistics')
      .then((data) => {
        if (
          !data?.totals ||
          !Array.isArray(data.top_games_table) ||
          !SERIES.every(({ key }) => isSeries(data[key]))
        ) {
          throw new Error('Statistics response was incomplete.')
        }
        if (!cancelled) setStats(data as Stats)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  const totals = stats?.totals
  const metrics = [
    ['Games', totals?.games],
    ['Libraries', totals?.libraries],
    ['Members', totals?.users],
    ['Downloads', totals?.downloads],
    ['Favourites', totals?.favorites],
    ['Library size', totals?.library_bytes == null ? 'n/a' : formatBytes(totals.library_bytes)],
  ] as const
  return (
    <Page title="Statistics" lede="Downloads, top titles, and library activity.">
      <PageStatus
        loading={loading && !stats}
        loadingMessage="Loading statistics…"
        error={error || null}
      />
      {failed ? (
        <Button disabled={loading} onClick={() => setReload((value) => value + 1)}>
          Retry loading statistics
        </Button>
      ) : null}
      {stats ? (
        <>
          <section className="od-stats-metrics" aria-label="Library totals">
            {metrics.map(([label, value]) => (
              <div className="od-stats-metric" key={label}>
                <span>{label}</span>
                <strong>
                  {typeof value === 'number' ? value.toLocaleString() : (value ?? 'n/a')}
                </strong>
              </div>
            ))}
          </section>
          <div className="od-stats-charts">
            {SERIES.map(({ key, title }) => {
              const series = stats[key] as Series
              const values = series.data.map((value) => Number(value) || 0)
              const max = Math.max(1, ...values)
              return (
                <section className="od-admin-panel od-stats-chart" key={key} aria-label={title}>
                  <h2>{title}</h2>
                  {series.labels.length ? (
                    <ol>
                      {series.labels.map((label, index) => (
                        <li key={`${label}-${index}`}>
                          <span className="od-stats-chart__label">{label}</span>
                          <span className="od-stats-chart__track" aria-hidden="true">
                            <span
                              style={{
                                width: `${Math.max(0, Math.min(100, (values[index] / max) * 100))}%`,
                              }}
                            />
                          </span>
                          <strong>{(values[index] ?? 0).toLocaleString()}</strong>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="od-stats-empty">No activity recorded yet.</p>
                  )}
                </section>
              )
            })}
          </div>
          <section className="od-admin-panel od-stats-top-games">
            <h2>Most downloaded titles</h2>
            <DataTable
              columns={columns}
              rows={stats.top_games_table.map((row, index) => ({ ...row, rank: index + 1 }))}
              getRowKey={(row, index) => `${row.name}-${index}`}
              caption="Most downloaded titles"
              emptyMessage="No downloads recorded yet."
            />
          </section>
        </>
      ) : null}
    </Page>
  )
}
