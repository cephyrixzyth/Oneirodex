import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Button, Modal, PageStatus } from '@oneirodex/ui'
import { getJson, postJsonResult } from '../api/adminApi'
import { BATCH_EDIT_URL } from './libraries/librariesModel'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import './BatchLibraryEditModal.css'

export type LibraryEditTarget = { uuid: string; name: string }
type PlatformOption = { key: string; label: string }

export function BatchLibraryEditModal({
  targets,
  onClose,
  onApplied,
}: {
  targets: LibraryEditTarget[] | null
  onClose: () => void
  onApplied: () => void
}) {
  const titleId = useId()
  const scanDepthRef = useRef<HTMLSelectElement | null>(null)
  const [platforms, setPlatforms] = useState<PlatformOption[]>([])
  const [platformError, setPlatformError] = useState('')
  const [scanDepth, setScanDepth] = useState('')
  const [watch, setWatch] = useState('')
  const [platform, setPlatform] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!targets) return
    let cancelled = false
    setScanDepth('')
    setWatch('')
    setPlatform('')
    setPlatformError('')
    getJson('/api/admin/library_platforms')
      .then((data) => {
        const options = Array.isArray(data?.platforms) ? data.platforms : []
        if (!cancelled) setPlatforms(options)
      })
      .catch((error) => {
        if (!cancelled) setPlatformError(errorText(error) || 'Unable to load platform choices.')
      })
    return () => {
      cancelled = true
    }
  }, [targets])

  async function apply(event: FormEvent) {
    event.preventDefault()
    if (!targets?.length || busy) return
    const patch: Record<string, unknown> = {}
    if (scanDepth) patch.scan_depth = Number(scanDepth)
    if (watch === 'default') patch.watch_enabled = null
    if (watch === 'on') patch.watch_enabled = true
    if (watch === 'off') patch.watch_enabled = false
    if (platform) patch.platform = platform
    if (!Object.keys(patch).length) {
      showToast('Choose at least one field to change.', 'info')
      return
    }
    setBusy(true)
    try {
      const result = await postJsonResult(BATCH_EDIT_URL, {
        library_uuids: targets.map((target) => target.uuid),
        ...patch,
      })
      if (!result.ok) {
        showToast(result.data?.error || result.data?.message || 'Batch edit failed.', 'error')
        return
      }
      const updated = Number(result.data?.updated) || 0
      const skipped = Number(result.data?.skipped) || 0
      const failed = Number(result.data?.failed) || 0
      const message =
        result.data?.message ||
        (failed
          ? `Edit: ${updated} updated, ${skipped} unchanged, ${failed} failed.`
          : updated
            ? `Updated ${updated} libraries${skipped ? ` (${skipped} unchanged)` : ''}.`
            : skipped
              ? 'No changes — selected libraries already match.'
              : 'Edit applied.')
      showToast(message, failed ? 'warn' : 'success')
      onClose()
      if (updated > 0) onApplied()
    } catch (error) {
      showToast(errorText(error) || 'Batch edit failed.', 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!targets?.length) return null
  const single = targets.length === 1
  return (
    <Modal
      open
      onClose={onClose}
      labelledBy={titleId}
      className="od-library-edit-modal"
      panelClassName="od-library-edit-modal__panel"
      initialFocusRef={scanDepthRef}
      closeOnEscape={!busy}
      closeOnBackdrop={!busy}
    >
      <header className="od-library-edit-modal__header">
        <div>
          <h2 id={titleId}>{single ? 'Edit library' : `Edit ${targets.length} libraries`}</h2>
          <p className="od-admin-lede">
            Apply shared fields
            {single
              ? ', or open the full editor for name and image.'
              : '. Leave each field unchanged to skip it.'}
          </p>
        </div>
        <Button
          type="button"
          className="od-btn--ghost"
          disabled={busy}
          onClick={onClose}
          aria-label="Close edit libraries dialog"
        >
          Close
        </Button>
      </header>
      {!single ? (
        <ul className="od-library-edit-modal__targets">
          {targets.map((target) => (
            <li key={target.uuid}>{target.name}</li>
          ))}
        </ul>
      ) : null}
      {platformError ? (
        <PageStatus error={platformError} errorMessage="Unable to load platform choices." />
      ) : null}
      <form className="od-library-edit-modal__form" onSubmit={(event) => void apply(event)}>
        <label className="od-admin-field">
          Scan depth
          <select
            ref={scanDepthRef}
            className="od-admin-input"
            value={scanDepth}
            onChange={(event) => setScanDepth(event.target.value)}
            disabled={busy}
          >
            <option value="">Leave unchanged</option>
            <option value="1">1 — game folders directly in the scan root</option>
            <option value="2">2 — unwrap letter buckets (_a … _z, _#) then games</option>
          </select>
        </label>
        <label className="od-admin-field">
          Update library when folders change
          <select
            className="od-admin-input"
            value={watch}
            onChange={(event) => setWatch(event.target.value)}
            disabled={busy}
          >
            <option value="">Leave unchanged</option>
            <option value="default">Follow global setting</option>
            <option value="on">Prefer watch when the global switch is on</option>
            <option value="off">Opt out</option>
          </select>
        </label>
        <label className="od-admin-field">
          Platform
          <select
            className="od-admin-input"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            disabled={busy || Boolean(platformError)}
          >
            <option value="">Leave unchanged</option>
            {platforms.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {single ? (
          <a
            className="od-cbtn od-library-edit-modal__full"
            href={`/admin/library/edit/${encodeURIComponent(targets[0].uuid)}`}
          >
            Open full editor
          </a>
        ) : (
          <p className="od-admin-hint">Rename and library image stay on each full editor.</p>
        )}
        <footer className="od-library-edit-modal__actions">
          <Button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || Boolean(platformError)}>
            {busy ? 'Applying…' : 'Apply changes'}
          </Button>
        </footer>
      </form>
    </Modal>
  )
}
