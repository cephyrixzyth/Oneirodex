import { useEffect, useId, useRef, useState } from 'react'
import { PageStatus, Modal, Button } from '@oneirodex/ui'
import { postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import './OpenPathModal.css'

async function copyPath(path: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(path)
    return
  }
  const input = document.createElement('textarea')
  input.value = path
  input.setAttribute('readonly', '')
  input.style.position = 'fixed'
  input.style.left = '-9999px'
  document.body.appendChild(input)
  input.select()
  document.execCommand('copy')
  document.body.removeChild(input)
}

/**
 * Unmatched open-path popup — never navigates to Auto Scan.
 */
export function OpenPathModal({
  open,
  path = '',
  label = 'Path',
  matchReason = '',
  onClose,
}: {
  open: boolean
  path?: string
  label?: string
  matchReason?: string
  onClose?: () => void
}) {
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    if (open) setStatus(null)
  }, [open])

  if (!open || !path) return null

  async function handleCopy() {
    try {
      await copyPath(path)
      setStatus('Path copied to clipboard')
    } catch {
      setStatus('Unable to copy path')
    }
  }

  async function handleOpenExplorer() {
    setBusy(true)
    setStatus(null)
    try {
      await postJson('/api/client/commands', {
        game_uuid: '',
        action: 'open_path',
        path,
        select: true,
      })
      setStatus('Queued open in file explorer for companion')
    } catch (err) {
      const message = errorText(err)
      try {
        await copyPath(path)
        setStatus(
          message
            ? `${message} — path copied as fallback`
            : 'Open failed — path copied as fallback',
        )
      } catch {
        setStatus(message || 'Unable to open or copy path')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      labelledBy={titleId}
      className="od-open-path"
      panelClassName="od-open-path__panel"
      initialFocusRef={closeRef}
    >
      <div className="od-open-path__toolbar">
        <h2 id={titleId} className="od-open-path__title">
          {label}
        </h2>
        <button
          ref={closeRef}
          type="button"
          className="od-open-path__close"
          onClick={onClose}
          aria-label="Close"
        >
          ×
        </button>
      </div>
      {matchReason ? (
        <p className="od-open-path__reason">
          <strong>Match reason:</strong> {matchReason}
        </p>
      ) : null}
      <p className="od-open-path__path">
        <code>{path}</code>
      </p>
      <div className="od-open-path__actions">
        <Button type="button" variant="primary" onClick={() => void handleCopy()}>
          Copy path
        </Button>
        <Button type="button" disabled={busy} onClick={() => void handleOpenExplorer()}>
          {busy ? 'Opening…' : 'Open in file explorer'}
        </Button>
      </div>
      {status ? (
        <PageStatus announcement="status" className="od-open-path__status">
          {status}
        </PageStatus>
      ) : null}
    </Modal>
  )
}
