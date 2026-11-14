import { confirmAction, errorFromResponse } from '@oneirodex/ui'
import { useRef, useState } from 'react'
import { scanJobsStructureSignature } from '../../../../oneirodex/setup/default_theme/js/scanJobsDom.js'
import { csrfHeaders, getJson } from '../api/adminApi'
import { formatScanJobCounters } from '../components/opsWidgets'
import {
  isScanBusyStatus,
  isScanQueuedStatus,
  isScanRunning,
  normalizeScanJobsList,
  type ScanJobsPayload,
} from '../components/scanQueuePolicy'
import { useLibraryRefreshAll } from '../hooks/useLibraryRefreshAll'
import { useLibraryScan } from '../hooks/useLibraryScan'
import { useVisibilityPoll } from '../hooks/useVisibilityPoll'
import { errorText } from '../utils/errorText'
export function useScans() {
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
  const runningJob =
    jobs.find((job) => String(job.status || '').toLowerCase() === 'running') || null
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
  const visibleJobs = filteredJobs
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
  return {
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
  }
}
