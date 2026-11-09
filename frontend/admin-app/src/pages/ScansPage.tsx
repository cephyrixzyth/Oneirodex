import { Button, PageStatus } from '@oneirodex/ui'
import { type ReactNode } from 'react'
import { DataTable } from '../components/DataTable'
import { formatScanJobCounters } from '../components/opsWidgets'
import { Page } from '../components/Page'
import { ScanConflictModal } from '../components/ScanConflictModal'
import { isScanBusyStatus, isScanQueuedStatus } from '../components/scanQueuePolicy'
import './ScansPage.css'
import { useScans } from './useScans'

export function ScansPage() {
  const {
    status,
    error,
    actionError,
    actionMessage,
    actionBusy,
    busyJobKey,
    statusFilter,
    setStatusFilter,
    jobQuery,
    setJobQuery,
    updatedAt,
    conflictOpen,
    refreshing,
    startRefreshAll,
    onConflictChoose,
    onConflictClose,
    scanConflictOpen,
    scanBusyKey,
    startScan,
    onScanConflictChoose,
    onScanConflictClose,
    jobs,
    running,
    runningJob,
    stoppingJob,
    queuedJobs,
    filteredJobs,
    visibleJobs,
    message,
    scanMotifActive,
    scanSummary,
    statusCount,
    cancelScanJob,
    clearJobs,
    exportCsv,
  } = useScans()

  const conflictDialogs = (
    <>
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
    </>
  )

  const content = (
    <>
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
              rows={visibleJobs}
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
      {conflictDialogs}
    </>
  )
  return (
    <Page
      title="Scan jobs"
      documentTitle="Scan Jobs"
      lede="Review live scan progress, retry completed scans, and inspect unmatched folders."
    >
      {content}
    </Page>
  )
}
