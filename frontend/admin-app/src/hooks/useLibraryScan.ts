import { useCallback, useRef, useState } from 'react'
import { postJsonResult } from '../api/adminApi'
import {
  buildScanQueueRequestFields,
  hasActiveScan,
  isAlreadyRunningReject,
  normalizeScanJobsList,
  toastForScanStartResponse,
  toastToneForScanVariant,
} from '../components/scanQueuePolicy'
import type { ScanQueuePolicy } from '../components/scanQueuePolicy'
import { showToast } from '../utils/toast'
import { errorText } from '../utils/errorText'

/** One library to (re)scan. `folder` omitted falls back to the library's `last_scan_folder`. */
export interface ScanTarget {
  libraryUuid: string
  folder?: string
  label?: string
  /** Row key for `busyKey`; defaults to `libraryUuid`. */
  key?: string
  /** Extra scan fields merged into the POST body (e.g. a restarted job's settings). */
  settings?: Record<string, unknown>
}

const SCAN_URL = '/api/admin/libraries/scan'
const SCAN_STATUS_URL = '/api/scan_jobs_status'

/**
 * Start (or queue) a scan for **one** library, with the same Queue / Force
 * conflict modal `useLibraryRefreshAll` puts on the all-libraries button.
 *
 * The SPA had only "Refresh all libraries". `/api/admin/libraries/scan` has
 * always accepted a single `library_uuid`, and the Jinja pages have always
 * offered per-library Auto Scan and a restart on a finished job — but neither
 * control existed in the React admin, so scanning one library and re-running a
 * failed job were only reachable by leaving the SPA.
 *
 * `target` is `{ libraryUuid, folder?, label?, settings? }`. `folder` is
 * optional: the route falls back to the library's `last_scan_folder`, which is
 * what makes a bare "Scan" button on the libraries table work at all. A restart
 * passes the finished job's own folder and settings so "Scan again" repeats
 * *that* scan rather than whatever the library was last pointed at.
 */
export function useLibraryScan({ persistentErrors = false }: { persistentErrors?: boolean } = {}) {
  const [conflictOpen, setConflictOpen] = useState(false)
  const [busyKey, setBusyKey] = useState('')
  const [scanError, setScanError] = useState('')
  // Held across the conflict modal: the operator picks a policy after the POST
  // has already been rejected, so the retry needs the target that was refused.
  const pendingTarget = useRef<ScanTarget | null>(null)
  const clearScanError = useCallback(() => setScanError(''), [])

  const postScan = useCallback(
    async (target: ScanTarget, policy: ScanQueuePolicy | null) => {
      const body = {
        library_uuid: target.libraryUuid,
        ...(target.folder ? { folder: target.folder } : {}),
        ...(target.settings || {}),
        // null = operator has not chosen yet (idle path) → default queue fields.
        ...buildScanQueueRequestFields(policy == null ? undefined : policy),
      }
      setScanError('')
      setBusyKey(target.key || target.libraryUuid || 'scan')
      try {
        const { ok, status, data } = await postJsonResult(SCAN_URL, body)
        if (isAlreadyRunningReject(status, data) && policy == null) {
          pendingTarget.current = target
          setConflictOpen(true)
          return { deferred: true }
        }
        const toast = toastForScanStartResponse(data, ok)
        const label = target.label ? `${target.label}: ` : ''
        if (toast.variant === 'error' && persistentErrors) {
          setScanError(`${label}${toast.text}`)
        } else {
          showToast(`${label}${toast.text}`, toastToneForScanVariant(toast.variant))
        }
        setConflictOpen(false)
        pendingTarget.current = null
        return { ok, status, data, deferred: false }
      } catch (err) {
        const message = errorText(err) || 'Scan failed to start.'
        if (persistentErrors) setScanError(message)
        else showToast(message, 'error')
        setConflictOpen(false)
        pendingTarget.current = null
        return { ok: false, deferred: false, error: err }
      } finally {
        setBusyKey('')
      }
    },
    [persistentErrors],
  )

  const startScan = useCallback(
    async (target: ScanTarget | null | undefined) => {
      if (!target?.libraryUuid) {
        showToast('That job has no library attached, so it cannot be re-run.', 'error')
        return
      }
      try {
        // Check for a busy scan before posting rather than only reacting to a
        // 409: not every rejection comes back as one, and a job queued by
        // accident is still a job someone has to go and cancel.
        const response = await fetch(SCAN_STATUS_URL, {
          credentials: 'same-origin',
          cache: 'no-store',
        })
        if (response.status === 401) {
          window.location.href = '/login'
          throw new Error('unauthorized')
        }
        const payload = response.ok ? await response.json().catch(() => []) : []
        if (hasActiveScan(normalizeScanJobsList(payload))) {
          pendingTarget.current = target
          setConflictOpen(true)
          return
        }
        await postScan(target, null)
      } catch (err) {
        const message = errorText(err) || 'Could not check scan status.'
        if (persistentErrors) setScanError(message)
        else showToast(message, 'error')
      }
    },
    [persistentErrors, postScan],
  )

  const onConflictChoose = useCallback(
    (policy: ScanQueuePolicy) => {
      const target = pendingTarget.current
      if (!target) {
        setConflictOpen(false)
        return
      }
      void postScan(target, policy)
    },
    [postScan],
  )

  const onConflictClose = useCallback(() => {
    if (busyKey) return
    pendingTarget.current = null
    setConflictOpen(false)
  }, [busyKey])

  return {
    conflictOpen,
    /** Key of the row currently posting, '' when idle. */
    busyKey,
    scanning: Boolean(busyKey),
    scanError,
    clearScanError,
    startScan,
    onConflictChoose,
    onConflictClose,
  }
}
