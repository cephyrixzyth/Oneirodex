import { useRef, useState, type ReactNode } from 'react'
import { PageStatus, Button } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
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
import './ScansPage.css'

export function ScansPage() {
  const [status, setStatus] = useState<ScanJobsPayload>(null)
  const [error, setError] = useState<unknown>(null)
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
  const queuedJobs = jobs.filter((job) => isScanQueuedStatus(job?.status))
  const recentJobs = jobs.slice(0, 12)
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
  const activeJob = jobs.find((job) => isScanBusyStatus(job?.status)) || null
  let scanSummary
  if (running && activeJob) {
    const counters = formatScanJobCounters(activeJob)
    const where = activeJob.library_name || activeJob.library || 'a library'
    const eta = activeJob.eta_label ? ` · ~${activeJob.eta_label} left` : ''
    scanSummary = `Scanning ${where} — ${counters}${eta}`
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

  return (
    <Page
      title="Scan jobs"
      lede="Review live scan progress, retry completed scans, and inspect unmatched folders."
    >
      <PageStatus error={error} errorMessage="Unable to load scan status." />
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
              {running ? 'Scanning…' : `Queued… (${queuedJobs.length})`}
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
            {/* Scan jobs sort and filter like every other table now (W27-C2).
                Each column declares `value` where what it renders is not what
                it should sort on: Job renders a truncated code element, and
                Status renders a queue position alongside the word — sorting on
                the rendered markup would order by the wrong thing entirely. */}
            <DataTable
              rows={recentJobs}
              getRowKey={(job) => job.id}
              caption="Recent scan jobs"
              scrollLabel="Recent scan jobs table"
              emptyMessage="No scan jobs yet."
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
