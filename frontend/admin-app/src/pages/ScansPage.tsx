import { useRef, useState, type ReactNode } from 'react'
import { PageStatus, Button, confirmAction, errorFromResponse } from '@oneirodex/ui'
import { csrfHeaders, getJson } from '../api/adminApi'
import { DataTable } from '../components/DataTable'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import {
  isScanBusyStatus,
  isScanQueuedStatus,
  isScanRunning,
  normalizeScanJobsList,
  type ScanJobsPayload,
} from '../components/scanQueuePolicy'
import { formatScanJobCounters } from '../components/opsWidgets'
import { scanJobsStructureSignature } from '../../../../oneirodex/setup/default_theme/js/scanJobsDom.js'
import { useLibraryRefreshAll } from '../hooks/useLibraryRefreshAll'
import { useLibraryScan } from '../hooks/useLibraryScan'
import { useVisibilityPoll } from '../hooks/useVisibilityPoll'
import { errorText } from '../utils/errorText'
import './ScansPage.css'

export function ScansPage() {
  const [status, setStatus] = useState<ScanJobsPayload>(null)
  const [error, setError] = useState<unknown>(null)
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [busyJobKey, setBusyJobKey] = useState('')
  const [statusFilter, setStatusFilter] = useState('All')
  const [jobQuery, setJobQuery] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const { conflictOpen, refreshing, startRefreshAll, onConflictChoose, onConflictClose } =
    useLibraryRefreshAll()
  const {
    conflictOpen: scanConflictOpen,
    busyKey: scanBusyKey,
    startScan,
    onConflictChoose: onScanConflictChoose,
    onConflictClose: onScanConflictClose,
  } = useLibraryScan()

  const hasSnapshotRef = useRef(false)
  const jobsSnapshotKeyRef = useRef('')

  useVisibilityPoll(async ({ signal }) => {
    try {
      const data = await getJson('/api/scan_jobs_status', { signal })
      const jobs = normalizeScanJobsList(data)
      const busy = jobs.some((job) => isScanBusyStatus(job?.status))
      // scanJobsProgressSignature folds processed / percentage / elapsed / eta —
      // all of which tick every few seconds while a scan runs. Bucket
      // progress to 5% so a 41%→43% step is a no-op, but a ≥5% step, a stall, a
      // status change or a structure change still lands. When nothing is busy,
      // drop progress entirely — the structure signature already covers
      // status / queue-position / cancellation changes.
      const progressKey = busy
        ? jobs
            .map((job) => {
              const pct = Number(job?.percentage ?? job?.progress ?? 0) || 0
              return `${job?.id}:${Math.round(pct / 5)}:${job?.stalled ? 1 : 0}`
            })
            .join(',')
        : ''
      const key = `${scanJobsStructureSignature(jobs, { busy })}::${progressKey}`
      if (key === jobsSnapshotKeyRef.current && hasSnapshotRef.current) {
        return
      }
      jobsSnapshotKeyRef.current = key
      setStatus(data)
      setError(null)
      setUpdatedAt(new Date())
      hasSnapshotRef.current = true
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (!hasSnapshotRef.current) setError(err)
    }
  }, 4000)

  const jobs = normalizeScanJobsList(status)
  // A bare `running` flag with no jobs behind it is a phantom scan (GT-B13).
  const running = isScanRunning(status)
  const runningJob = jobs.find((job) => String(job.status || '').toLowerCase() === 'running') || null
  const stoppingJob =
    jobs.find((job) => String(job.status || '').toLowerCase() === 'stopping') || null
  const queuedJobs = jobs.filter((job) => isScanQueuedStatus(job?.status))
  const matchesStatus = (job: Record<string, unknown>, filter: string) => {
    const value = String(job.status || '').toLowerCase()
    const cancelledByUser = value === 'failed' && job.error_message === 'Scan cancelled by user'
    if (filter === 'All') return true
    if (filter === 'Running') return value === 'running' || value === 'stopping'
    if (filter === 'Queued') return value === 'queued' || value === 'pending'
    if (filter === 'Scheduled') return value === 'scheduled'
    if (filter === 'Cancelled')
      return value === 'cancelled' || value === 'canceled' || cancelledByUser
    if (filter === 'Failed') return value === 'failed' && !cancelledByUser
    return value === filter.toLowerCase()
  }
  const needle = jobQuery.trim().toLowerCase()
  const filteredJobs = jobs.filter((job) => {
    if (!matchesStatus(job, statusFilter)) return false
    if (!needle) return true
    return [job.library_name, job.library, job.scan_folder, job.status, job.error_message].some(
      (value) =>
        String(value || '')
          .toLowerCase()
          .includes(needle),
    )
  })
  const statusPayload = (status && !Array.isArray(status) ? status : {}) as Record<string, unknown>
  const message =
    statusPayload.message || statusPayload.status_message || statusPayload.phase || null
  const scanMotifActive = running || queuedJobs.length > 0

  /**
   * One sentence answering "is anything happening, and if not, why not".
   *
   * The queued-but-not-running case is the one that matters and the one the old
   * readout hid: it rendered as "Running: no · queued 1", which reads as idle.
   * A queue with work in it and nothing running is either about to promote or
   * is being held by a job that no longer has a worker — and the operator
   * cannot tell those apart from a boolean. The Detail column carries the
   * reclaim reason once the sweep has run; this line at least stops calling it
   * idle.
   */
  let scanSummary
  if (runningJob) {
    const counters = formatScanJobCounters(runningJob)
    const where = runningJob.library_name || runningJob.library || 'a library'
    const eta = runningJob.eta_label ? ` · ~${runningJob.eta_label} left` : ''
    scanSummary = `Scanning ${where} — ${counters}${eta}`
  } else if (stoppingJob) {
    const counters = formatScanJobCounters(stoppingJob)
    const where = stoppingJob.library_name || stoppingJob.library || 'a library'
    scanSummary = `Stopping ${where} — ${counters}`
  } else if (queuedJobs.length) {
    scanSummary =
      `${queuedJobs.length} scan${queuedJobs.length === 1 ? '' : 's'} queued, none running. ` +
      'A queued scan starts when the current one finishes; if nothing is running, ' +
      'the queue is waiting on a job that has not reported a result yet.'
  } else if (jobs.length) {
    scanSummary = 'No scan running.'
  } else {
    scanSummary = 'No scans have run yet.'
  }

  function statusCount(filter: string) {
    if (filter === 'All') return jobs.length
    return jobs.filter((job) => matchesStatus(job, filter)).length
  }

  async function cancelScanJob(job: Record<string, unknown>) {
    if (actionBusy || busyJobKey) return
    const id = String(job.id || '')
    if (!id) return
    const queued = isScanQueuedStatus(job.status)
    setBusyJobKey(id)
    setActionError('')
    setActionMessage('')
    try {
      const response = await fetch(`/cancel_scan_job/${encodeURIComponent(id)}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
      })
      if (!response.ok) throw await errorFromResponse(response, 'Cancel scan job')
      if (response.redirected && new URL(response.url).pathname === '/login') {
        throw new Error('Your admin session expired. Sign in and retry the action.')
      }
      setActionMessage(
        queued
          ? `Queued scan job ${id} cancelled.`
          : 'Scan is stopping. Waiting for threads to complete…',
      )
      try {
        const fresh = await getJson('/api/scan_jobs_status')
        setStatus(fresh)
        setUpdatedAt(new Date())
        jobsSnapshotKeyRef.current = ''
      } catch (err) {
        jobsSnapshotKeyRef.current = ''
        setActionError(errorText(err) || 'Scan action sent; the list will refresh automatically.')
      }
    } catch (err) {
      setActionError(errorText(err) || 'Could not cancel the scan job.')
    } finally {
      setBusyJobKey('')
    }
  }

  async function clearJobs(target: 'Completed' | 'Failed' | 'All') {
    if (actionBusy) return
    const allTerminal = target === 'All'
    const confirmed = await confirmAction({
      title: allTerminal
        ? 'Clear completed scan jobs?'
        : `Clear ${target.toLowerCase()} scan jobs?`,
      body: allTerminal
        ? 'Completed, failed, and cancelled history will be removed. Running, stopping, queued, and scheduled scans will stay.'
        : `All ${target.toLowerCase()} scan history will be removed. Active and scheduled scans will stay.`,
      confirmLabel: allTerminal ? 'Clear all' : `Clear ${target.toLowerCase()}`,
      cancelLabel: 'Keep scan history',
    })
    if (!confirmed) return

    setActionBusy(true)
    setActionError('')
    setActionMessage('')
    try {
      const url = allTerminal
        ? '/clear_all_scan_jobs'
        : `/clear_scan_jobs?status=${encodeURIComponent(target)}`
      const response = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
      })
      if (!response.ok) throw await errorFromResponse(response, 'Clear scan jobs')
      if (response.redirected && new URL(response.url).pathname === '/login') {
        throw new Error('Your admin session expired. Sign in and retry the action.')
      }
      const clearedCount = jobs.filter((job) => {
        const status = String(job.status || '').toLowerCase()
        return allTerminal
          ? status === 'completed' || status === 'failed' || status === 'cancelled'
          : status === target.toLowerCase()
      }).length
      setActionMessage(
        allTerminal
          ? `Cleared ${clearedCount} completed/failed/cancelled scan jobs (Running/Stopping/Queued/Scheduled kept).`
          : `Cleared ${clearedCount} ${target} scan jobs.`,
      )
      try {
        const fresh = await getJson('/api/scan_jobs_status')
        setStatus(fresh)
        setUpdatedAt(new Date())
        jobsSnapshotKeyRef.current = ''
      } catch (err) {
        jobsSnapshotKeyRef.current = ''
        setActionError(
          errorText(err) || 'Scan history cleared; the list will refresh automatically.',
        )
      }
    } catch (err) {
      setActionError(errorText(err) || 'Could not clear scan history.')
    } finally {
      setActionBusy(false)
    }
  }

  function exportCsv() {
    const fields = [
      ['id', 'id'],
      ['when', 'when'],
      ['library_name', 'library'],
      ['scan_folder', 'path'],
      ['status', 'status'],
      ['progress', 'progress'],
      ['error_message', 'error'],
    ] as const
    const escape = (value: unknown) => {
      const text = String(value ?? '')
      return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
    }
    const formatWhen = (job: Record<string, unknown>) => {
      const raw = [job.last_run, job.started_at].find(
        (value): value is string =>
          typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Date.parse(value)),
      )
      if (!raw) return '—'
      const date = new Date(raw)
      const pad = (value: number) => String(value).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    }
    const lines = [
      fields.map(([, label]) => label).join(','),
      ...filteredJobs.map((job) =>
        fields
          .map(([key]) =>
            escape(
              key === 'when'
                ? formatWhen(job)
                : key === 'progress'
                  ? Number(job.total_folders ?? 0) > 0
                    ? `${Number(job.folders_success ?? 0) + Number(job.folders_failed ?? 0)}/${Number(job.total_folders ?? 0)}`
                    : ''
                  : job[key],
            ),
          )
          .join(','),
      ),
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const href = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = href
    link.download = `scan-jobs-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(href)
  }

  return (
    <Page
      title="Scan jobs"
      lede="Review live scan progress, retry completed scans, and inspect unmatched folders."
    >
      <PageStatus error={error} errorMessage="Unable to load scan status." />
      <PageStatus error={actionError} />
      <div className="od-admin-panel">
        <div className="od-admin-panel__toolbar od-admin-panel__toolbar--row">
          <Button
            type="button"
            className="od-btn--accent"
            onClick={() => void startRefreshAll()}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing…' : 'Refresh all libraries'}
          </Button>
          {scanMotifActive ? (
            <PageStatus
              announcement="status"
              inline
              className={'od-admin-scan-live'}
              dataState={running ? 'running' : 'queued'}
            >
              <span className="od-spinner od-spinner--sm" aria-hidden="true" />
              {runningJob
                ? 'Scanning…'
                : stoppingJob
                  ? 'Stopping…'
                  : `Queued… (${queuedJobs.length})`}
            </PageStatus>
          ) : null}
        </div>
        {!status ? (
          <PageStatus loading loadingMessage="Loading scan status…" />
        ) : (
          <>
            {/* Was a developer readout — "Running: no · queued 1 · job 3f2a…
                · progress 45". Every value in it was true and none of it
                answered the operator's question, which is "is anything
                happening, and if not, why not". That mattered: a queue held up
                by an orphaned job rendered as "Running: no · queued 1", which
                reads as idle rather than stuck. */}
            <p className="od-scan-summary">{scanSummary}</p>
            {message ? <p className="od-admin-lede">{message as ReactNode}</p> : null}
            {actionMessage ? (
              <PageStatus announcement="status" inline>
                {actionMessage}
              </PageStatus>
            ) : null}
            <div className="od-admin-panel__toolbar od-admin-panel__toolbar--row">
              <div
                className="od-scan-status-filters"
                role="group"
                aria-label="Filter scan jobs by status"
              >
                {['All', 'Running', 'Queued', 'Completed', 'Failed', 'Cancelled', 'Scheduled'].map(
                  (filter) => (
                    <Button
                      key={filter}
                      type="button"
                      size="sm"
                      className={statusFilter === filter ? 'od-btn--accent' : 'od-btn--secondary'}
                      aria-pressed={statusFilter === filter}
                      onClick={() => setStatusFilter(filter)}
                    >
                      {filter} ({statusCount(filter)})
                    </Button>
                  ),
                )}
              </div>
              <Button type="button" className="od-btn--secondary" onClick={exportCsv}>
                Export CSV
              </Button>
              <Button
                type="button"
                className="od-btn--secondary"
                disabled={actionBusy || statusCount('Completed') === 0}
                onClick={() => void clearJobs('Completed')}
              >
                Clear completed
              </Button>
              <Button
                type="button"
                className="od-btn--secondary"
                disabled={actionBusy || statusCount('Failed') === 0}
                onClick={() => void clearJobs('Failed')}
              >
                Clear failed
              </Button>
              <Button
                type="button"
                className="od-btn--secondary"
                disabled={
                  actionBusy ||
                  statusCount('Completed') + statusCount('Failed') + statusCount('Cancelled') === 0
                }
                onClick={() => void clearJobs('All')}
              >
                Clear all
              </Button>
            </div>
            <div className="od-table-toolbar">
              <label className="od-table-filter">
                <span className="od-table-filter__label">Filter scan jobs</span>
                <input
                  type="search"
                  value={jobQuery}
                  onChange={(event) => setJobQuery(event.target.value)}
                  placeholder="Library, path, status, or error…"
                  aria-label="Filter scan jobs"
                  autoComplete="off"
                />
              </label>
              <span className="od-table-count" aria-live="polite">
                {filteredJobs.length === jobs.length
                  ? `${jobs.length} scan job${jobs.length === 1 ? '' : 's'}`
                  : `${filteredJobs.length} of ${jobs.length} scan jobs`}
              </span>
            </div>
            {/* Scan jobs sort and filter like every other table now (W27-C2).
                Each column declares `value` where what it renders is not what
                it should sort on: Job renders a truncated code element, and
                Status renders a queue position alongside the word — sorting on
                the rendered markup would order by the wrong thing entirely. */}
            <DataTable
              rows={filteredJobs}
              getRowKey={(job) => job.id}
              caption="Scan jobs"
              scrollLabel="Scan jobs table"
              emptyMessage={
                jobs.length === 0
                  ? 'No scan jobs yet.'
                  : `No ${statusFilter.toLowerCase()} scan jobs match this filter.`
              }
              toolbar={false}
              initialSort={{ key: 'status', dir: 'asc' }}
              dense
              columns={[
                {
                  key: 'id',
                  label: 'Job',
                  value: (job) => String(job.id),
                  render: (job) => (
                    <code className="od-scan-job-id">{String(job.id).slice(0, 8)}</code>
                  ),
                },
                {
                  key: 'library',
                  label: 'Library',
                  value: (job) => job.library_name || job.library || '',
                  render: (job) => job.library_name || job.library || '—',
                },
                {
                  key: 'status',
                  label: 'Status',
                  value: (job) => job.status,
                  render: (job) =>
                    `${job.status}${
                      job.queue_position != null && isScanQueuedStatus(job.status)
                        ? ` (#${job.queue_position})`
                        : ''
                    }`,
                },
                {
                  // Progress and reason were on the Ops dashboard and not here
                  // (GT-B34), so the page you watch a scan on told you less
                  // than the glance did. Both come straight off
                  // /api/scan_jobs_status and were simply never rendered.
                  key: 'progress',
                  label: 'Progress',
                  // Queue state is the Status column's job, not this one's.
                  // formatScanJobCounters answers "Queued #1" for a queued job
                  // because on the Ops dashboard it is the only column there
                  // is; here that put the same fact in two adjacent cells.
                  render: (job) =>
                    isScanQueuedStatus(job.status) ? '—' : formatScanJobCounters(job),
                  // Sorts on folders done, not on the rendered "3/25", which
                  // would compare as text and put 10 before 9.
                  value: (job) =>
                    Number(job.folders_success ?? 0) + Number(job.folders_failed ?? 0),
                },
                {
                  key: 'detail',
                  label: 'Detail',
                  sortable: false,
                  render: (job) => {
                    // A failed job's reason outranks everything: it is the only
                    // thing that explains a queue that stopped moving. This is
                    // where a reclaimed job now says the owner process is gone,
                    // instead of the operator seeing an idle-looking queue.
                    if (job.error_message) {
                      return (
                        <span className="od-scan-detail od-scan-detail--error">
                          {job.error_message}
                        </span>
                      )
                    }
                    if (job.stalled) {
                      return (
                        <span className="od-scan-detail od-scan-detail--warn">
                          No progress reported
                        </span>
                      )
                    }
                    if (job.current_processing) {
                      return <span className="od-scan-detail">{job.current_processing}</span>
                    }
                    if (job.elapsed_label || job.eta_label) {
                      return (
                        <span className="od-scan-detail od-scan-detail--muted">
                          {job.elapsed_label || '—'}
                          {job.eta_label ? ` · ~${job.eta_label} left` : ''}
                        </span>
                      )
                    }
                    return <span className="od-scan-detail od-scan-detail--muted">—</span>
                  },
                },
                {
                  key: 'scan_folder',
                  label: 'Path',
                  value: (job) => job.scan_folder || '',
                  render: (job) => job.scan_folder || '—',
                },
                {
                  // "Scan again" on a finished job (W28). The Jinja scan
                  // manager has always had this and the SPA table never did,
                  // so a Failed job could only be re-run by leaving the SPA.
                  //
                  // It repeats *that* job — its folder and its three scan
                  // settings — rather than re-scanning whatever the library
                  // was last pointed at, which is the difference between a
                  // retry and a new scan.
                  key: 'retry',
                  label: 'Retry',
                  sortable: false,
                  render: (job) => {
                    const active = isScanBusyStatus(job.status) || isScanQueuedStatus(job.status)
                    if (active) return <span className="od-admin-lede">—</span>
                    return (
                      <Button
                        type="button"
                        size="sm"
                        disabled={scanBusyKey === job.id || !job.library_uuid}
                        title={
                          job.library_uuid
                            ? `Re-run this scan of ${job.scan_folder || 'the library folder'}`
                            : 'This job has no library attached, so it cannot be re-run.'
                        }
                        onClick={() =>
                          void startScan({
                            key: job.id,
                            libraryUuid: job.library_uuid,
                            folder: job.scan_folder || '',
                            label: job.library_name || job.library || 'Scan',
                            settings: {
                              scan_mode: job.setting_filefolder ? 'files' : 'folders',
                              remove_missing: Boolean(job.setting_remove),
                              download_missing_images: Boolean(job.setting_download_missing_images),
                            },
                          })
                        }
                      >
                        {scanBusyKey === job.id ? 'Starting…' : 'Scan again'}
                      </Button>
                    )
                  },
                },
                {
                  key: 'action',
                  label: 'Action',
                  sortable: false,
                  render: (job) => {
                    const jobStatus = String(job.status || '').toLowerCase()
                    if (jobStatus === 'stopping') {
                      return <span className="od-admin-lede">Stopping…</span>
                    }
                    if (jobStatus !== 'running' && !isScanQueuedStatus(job.status)) {
                      return <span className="od-admin-lede">—</span>
                    }
                    const queued = isScanQueuedStatus(job.status)
                    return (
                      <Button
                        type="button"
                        size="sm"
                        className="od-btn--secondary"
                        disabled={Boolean(busyJobKey) || actionBusy}
                        title={queued ? 'Cancel queued scan before it starts' : 'Stop this scan'}
                        onClick={() => void cancelScanJob(job)}
                      >
                        {busyJobKey === job.id
                          ? queued
                            ? 'Cancelling…'
                            : 'Stopping…'
                          : queued
                            ? 'Cancel queue'
                            : 'Stop'}
                      </Button>
                    )
                  },
                },
              ]}
            />
            {updatedAt ? (
              <p className="od-admin-lede">
                Live status · last refresh {updatedAt.toLocaleTimeString()}
              </p>
            ) : null}
            <p className="od-admin-lede">
              When a scan is already running, the scan controls and Refresh all offer{' '}
              <strong>Queue</strong> (default) or <strong>Force parallel</strong> with an Unraid/NAS
              load warning.
            </p>
          </>
        )}
      </div>
      <ScanConflictModal
        open={conflictOpen}
        busy={refreshing}
        onChoose={onConflictChoose}
        onClose={onConflictClose}
      />
      <ScanConflictModal
        open={scanConflictOpen}
        busy={Boolean(scanBusyKey)}
        onChoose={onScanConflictChoose}
        onClose={onScanConflictClose}
      />
    </Page>
  )
}
