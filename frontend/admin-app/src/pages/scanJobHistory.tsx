import { Link } from 'react-router-dom'

/** One unmatched-folder reason for a scan run, as /api/scan_jobs_status sends it. */
export interface ScanFailureReason {
  reason: string
  label: string
  count: number
}

const whenFormat = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

function parseWhen(value: unknown): Date | null {
  if (typeof value !== 'string' || !value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** "Nov 19, 8:11 PM → Nov 20, 2:38 AM", or "Started Nov 19, 8:11 PM" while it runs. */
export function scanJobWhenLabel(job: Record<string, unknown>): string {
  const started = parseWhen(job.started_at)
  const finished = parseWhen(job.finished_at)
  if (!started) return '—'
  if (!finished) return `Started ${whenFormat.format(started)}`
  return `${whenFormat.format(started)} → ${whenFormat.format(finished)}`
}

/** Sort key: when the run started (epoch ms), 0 when it never ran. */
export function scanJobStartedValue(job: Record<string, unknown>): number {
  return parseWhen(job.started_at)?.getTime() ?? 0
}

export function scanJobReasons(job: Record<string, unknown>): ScanFailureReason[] {
  const raw = job.failure_reasons
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (item): item is ScanFailureReason =>
      Boolean(item) &&
      typeof (item as ScanFailureReason).label === 'string' &&
      Number((item as ScanFailureReason).count) > 0,
  )
}

/** Why folders in this run were not added: counts per reason, linking to the review list. */
export function ScanFailureReasons({ job }: { job: Record<string, unknown> }) {
  const reasons = scanJobReasons(job)
  if (!reasons.length) return null
  const total = reasons.reduce((sum, item) => sum + Number(item.count), 0)
  return (
    <span className="od-scan-detail od-scan-detail--reasons">
      <Link to="/scan_management?active_tab=unmatched">{total} not added</Link>
      {': '}
      {reasons.map((item) => `${item.count} ${item.label.toLowerCase()}`).join(' · ')}
    </span>
  )
}
