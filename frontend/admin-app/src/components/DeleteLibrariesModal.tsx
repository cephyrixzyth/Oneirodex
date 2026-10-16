import { useEffect, useId, useMemo, useState } from 'react'
import { Button, Modal, PageStatus } from '@oneirodex/ui'
import { getJson, postJsonResult } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import type { LibraryEditTarget } from './BatchLibraryEditModal'
import './DeleteLibrariesModal.css'

type Progress = {
  status?: string
  current?: number
  total?: number
  message?: string
  games_failed?: number
}

export function DeleteLibrariesModal({
  targets,
  onClose,
  onDeleted,
}: {
  targets: LibraryEditTarget[] | null
  onClose: () => void
  onDeleted: () => void
}) {
  const titleId = useId()
  const single = targets?.length === 1
  const expected = useMemo(() => {
    if (!targets?.length) return ''
    return single ? targets[0].name : `DELETE ${targets.length} LIBRARIES`
  }, [single, targets])
  const [typed, setTyped] = useState('')
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState('')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!jobId) return undefined
    let disposed = false
    let source: EventSource | null = null
    let timer: number | undefined
    const finish = (data: Progress) => {
      if (disposed) return
      setProgress(data)
      if (data.status === 'completed') {
        disposed = true
        source?.close()
        if (timer) window.clearTimeout(timer)
        showToast(
          data.message || 'Library deletion completed.',
          Number(data.games_failed) ? 'warn' : 'success',
        )
        onDeleted()
      } else if (data.status === 'error') {
        setError(data.message || 'Library deletion failed.')
        setBusy(false)
        source?.close()
      }
    }
    const poll = async () => {
      try {
        const data = await getJson(`/check_deletion_progress/${encodeURIComponent(jobId)}`)
        if (data?.status !== 'not_found') finish(data)
        if (!disposed && data?.status !== 'completed' && data?.status !== 'error')
          timer = window.setTimeout(() => void poll(), 1000)
      } catch (cause) {
        if (!disposed) {
          setError(errorText(cause) || 'Unable to read deletion progress.')
          setBusy(false)
        }
      }
    }
    try {
      source = new EventSource(`/delete_library_progress/${encodeURIComponent(jobId)}`)
      source.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as Progress
          if (data.status !== 'connected') finish(data)
        } catch {
          setError('Unable to read deletion progress.')
          setBusy(false)
          source?.close()
        }
      }
      source.onerror = () => {
        source?.close()
        source = null
        void poll()
      }
    } catch {
      void poll()
    }
    return () => {
      disposed = true
      source?.close()
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId, onDeleted])

  useEffect(() => {
    if (targets) {
      setTyped('')
      setForce(false)
      setBusy(false)
      setJobId('')
      setProgress(null)
      setError('')
    }
  }, [targets])

  async function confirmDelete() {
    if (!targets?.length || busy) return
    setBusy(true)
    setError('')
    const forceConfirmed = force && !single
    try {
      const result = await postJsonResult('/api/admin/libraries/batch/delete', {
        library_uuids: targets.map((target) => target.uuid),
        force: forceConfirmed || Boolean(single),
        ...(!forceConfirmed && !single
          ? {
              confirm_names: Object.fromEntries(
                targets.map((target) => [target.uuid, target.name]),
              ),
            }
          : {}),
      })
      if (!result.ok)
        throw new Error(result.data?.error || result.data?.message || 'Unable to start deletion.')
      const jobs = Array.isArray(result.data?.jobs)
        ? result.data.jobs
        : Array.isArray(result.data?.results)
          ? result.data.results
          : []
      const first = jobs.find((job: { job_id?: unknown }) => job?.job_id)
      if (first?.job_id) {
        setJobId(String(first.job_id))
        showToast(
          result.data?.message || `Delete started for ${targets.length} libraries.`,
          'success',
        )
      } else {
        showToast(
          result.data?.message || `Delete started for ${targets.length} libraries.`,
          'success',
        )
        onDeleted()
      }
    } catch (cause) {
      setError(errorText(cause) || 'Unable to start deletion.')
      setBusy(false)
    }
  }

  if (!targets?.length) return null
  const valid = force && !single ? true : typed === expected
  return (
    <Modal
      open
      onClose={busy ? undefined : onClose}
      labelledBy={titleId}
      className="od-delete-libraries"
      panelClassName="od-delete-libraries__panel"
      closeOnEscape={!busy}
      closeOnBackdrop={!busy}
      lockScroll
    >
      <header className="od-delete-libraries__header">
        <div>
          <h2 id={titleId}>{single ? 'Delete library' : `Delete ${targets.length} libraries`}</h2>
          <p className="od-admin-lede">
            This removes the selected library records and cannot be undone.
          </p>
        </div>
        <Button
          type="button"
          disabled={busy}
          onClick={onClose}
          aria-label="Close delete libraries dialog"
        >
          Close
        </Button>
      </header>
      {!single ? (
        <ul className="od-delete-libraries__targets">
          {targets.map((target) => (
            <li key={target.uuid}>{target.name}</li>
          ))}
        </ul>
      ) : (
        <p className="od-delete-libraries__single">Delete library “{targets[0].name}”?</p>
      )}
      {!single ? (
        <label className="od-delete-libraries__force">
          <input
            type="checkbox"
            checked={force}
            onChange={(event) => setForce(event.target.checked)}
            disabled={busy}
          />{' '}
          Skip typing the confirmation phrase
        </label>
      ) : null}
      {!(force && !single) ? (
        <label className="od-admin-field">
          Type <strong>{expected}</strong> to confirm
          <input
            className="od-admin-input"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            disabled={busy}
            autoComplete="off"
          />
        </label>
      ) : null}
      {error ? <PageStatus error={error} errorMessage="Deletion failed." /> : null}
      {jobId ? (
        <PageStatus announcement="status" className={'od-delete-libraries__progress'}>
          <p>{progress?.message || 'Deleting libraries…'}</p>
          {Number(progress?.total) > 0 ? (
            <progress value={Number(progress?.current) || 0} max={Number(progress?.total)} />
          ) : null}
        </PageStatus>
      ) : null}
      <footer className="od-delete-libraries__actions">
        <Button type="button" disabled={busy} onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="button"
          variant="danger"
          disabled={busy || !valid}
          onClick={() => void confirmDelete()}
        >
          {jobId ? 'Deleting…' : busy ? 'Starting…' : 'Confirm delete'}
        </Button>
      </footer>
    </Modal>
  )
}
