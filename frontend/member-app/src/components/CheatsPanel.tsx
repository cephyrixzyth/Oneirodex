import { useEffect, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { CHEAT_DIALECTS, createCheat, deleteCheat, listCheats, uploadCheat } from '../api/cheats'
import { showsRetroarchCheats } from '../utils/detailsMedia'
import { Button } from '@oneirodex/ui'
import { showToast } from '../utils/toast'
import { PageStatus } from './PageStatus'
import './CheatsPanel.css'

function emptyCodeRow() {
  return { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, desc: '', code: '' }
}

function formatSize(bytes: any) {
  const n = Number(bytes) || 0
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Game details Cheats panel - create / upload / list / delete `.cht` files.
 * Only mounts when Backend `cheat_surface === 'retroarch'` (Wave 19 GM lock).
 */
export function CheatsPanel({ gameUuid, playHref = null, cheatSurface = 'retroarch' }: LooseProps) {
  const formId = useId()
  const [cheats, setCheats] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [dialect, setDialect] = useState(CHEAT_DIALECTS[0].value)
  const [codeRows, setCodeRows] = useState(() => [emptyCodeRow()])
  const [uploadFile, setUploadFile] = useState<any>(null)
  const [reloadTick, setReloadTick] = useState(0)

  const allowed = showsRetroarchCheats({ cheat_surface: cheatSurface })

  useEffect(() => {
    if (!gameUuid || !allowed) {
      return undefined
    }
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)
    listCheats(gameUuid, { signal: controller.signal })
      .then((data) => {
        if (!active) return
        setCheats(data.cheats)
        setLoading(false)
      })
      .catch((err: any) => {
        if (!active || err.name === 'AbortError') return
        setError(err)
        setCheats([])
        setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [gameUuid, reloadTick, allowed])

  if (!allowed) {
    return null
  }

  function refresh(message: any) {
    if (message) {
      setStatus(message)
      showToast(message, 'success')
    }
    setReloadTick((n) => n + 1)
  }

  async function handleCreate(event: any) {
    event.preventDefault()
    if (busy) return
    const trimmedName = name.trim()
    const codes = codeRows
      .map((row) => ({
        desc: String(row.desc || '').trim(),
        code: String(row.code || '').trim(),
      }))
      .filter((row) => row.code)
    if (!trimmedName) {
      setStatus('Name is required')
      return
    }
    if (!codes.length) {
      setStatus('Add at least one code row')
      return
    }
    setBusy(true)
    setStatus(null)
    try {
      const row = await createCheat(gameUuid, {
        name: trimmedName,
        codes,
        dialect,
      })
      setName('')
      setDialect(CHEAT_DIALECTS[0].value)
      setCodeRows([emptyCodeRow()])
      refresh(row?.name ? `Saved ${row.name}` : 'Cheat saved')
    } catch (err: any) {
      setStatus(err?.message || 'Could not save cheat')
      if (err?.code !== 'create_unavailable') {
        showToast(err?.message || 'Could not save cheat', 'error')
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleUpload(event: any) {
    event.preventDefault()
    if (busy || !uploadFile) return
    setBusy(true)
    setStatus(null)
    try {
      const row = await uploadCheat(gameUuid, uploadFile)
      setUploadFile(null)
      const input = event.currentTarget?.querySelector?.('input[type="file"]')
      if (input) input.value = ''
      refresh(row?.name ? `Uploaded ${row.name}` : 'Cheat uploaded')
    } catch (err: any) {
      setStatus(err?.message || 'Upload failed')
      showToast(err?.message || 'Upload failed', 'error')
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(filename: any) {
    if (busy || !filename) return
    setBusy(true)
    setStatus(null)
    try {
      await deleteCheat(gameUuid, filename)
      refresh(`Deleted ${filename}`)
    } catch (err: any) {
      setStatus(err?.message || 'Delete failed')
      showToast(err?.message || 'Delete failed', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="od-details-page__section od-cheats-panel"
      id="cheats"
      aria-labelledby={`${formId}-heading`}
    >
      <h2 id={`${formId}-heading`}>Cheats</h2>
      <p className="od-cheats-panel__lede">
        Household RetroArch <code>.cht</code> files for this title. Browser play loads them from the
        play bar cheat list; companion stages the same files before RetroArch. Quick Menu may still
        be required to enable codes. See <Link to="/help#cheats">Help → Cheats</Link>.
      </p>

      {loading ? (
        <PageStatus
          loading
          inline
          loadingMessage="Loading cheats…"
          className="od-cheats-panel__status"
        />
      ) : null}
      {error ? <PageStatus error={error} className="od-cheats-panel__status" /> : null}
      {status ? (
        <p
          className="od-cheats-panel__status"
          role={/not available|failed|required|Add at least/i.test(status) ? 'alert' : 'status'}
        >
          {status}
        </p>
      ) : null}

      {!loading && !error && cheats.length === 0 ? (
        <PageStatus
          emptyMessage="No .cht files yet - create one or upload."
          className="od-cheats-panel__status"
        />
      ) : null}

      {cheats.length > 0 ? (
        <ul className="od-cheats-panel__list">
          {cheats.map((row) => (
            <li key={row.name} className="od-cheats-panel__row">
              <div className="od-cheats-panel__row-meta">
                <strong>{row.name}</strong>
                <span className="od-details-page__muted">{formatSize(row.size)}</span>
              </div>
              <div className="od-cheats-panel__row-actions">
                {row.url ? (
                  <a className="od-btn" href={row.url} download={row.name}>
                    Download
                  </a>
                ) : null}
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    void handleDelete(row.name)
                  }}
                >
                  Delete
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      {playHref ? (
        <p className="od-cheats-panel__lede">
          After saving, open{' '}
          <a className="od-btn" href={playHref}>
            Play in browser
          </a>{' '}
          and pick the file from the cheat dropdown (same library list).
        </p>
      ) : null}

      <form className="od-cheats-panel__form" onSubmit={handleCreate} aria-label="New cheat">
        <h3>New cheat</h3>
        <div className="od-cheats-panel__grid">
          <label className="od-cheats-panel__field">
            <span>Name</span>
            <input
              type="text"
              name="cheat-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Infinite lives"
              autoComplete="off"
              required
            />
          </label>
          <label className="od-cheats-panel__field">
            <span>Dialect hint</span>
            <select
              name="cheat-dialect"
              value={dialect}
              onChange={(event) => setDialect(event.target.value)}
            >
              {CHEAT_DIALECTS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="od-cheats-panel__codes" role="group" aria-label="Code rows">
          {codeRows.map((row, index) => (
            <div key={row.id} className="od-cheats-panel__code-row">
              <label className="od-cheats-panel__field">
                <span>Description {index === 0 ? '(optional)' : ''}</span>
                <input
                  type="text"
                  value={row.desc}
                  onChange={(event) => {
                    const value = event.target.value
                    setCodeRows((rows) =>
                      rows.map((item) => (item.id === row.id ? { ...item, desc: value } : item)),
                    )
                  }}
                  placeholder="Lives"
                  autoComplete="off"
                />
              </label>
              <label className="od-cheats-panel__field">
                <span>Code</span>
                <input
                  type="text"
                  value={row.code}
                  onChange={(event) => {
                    const value = event.target.value
                    setCodeRows((rows) =>
                      rows.map((item) => (item.id === row.id ? { ...item, code: value } : item)),
                    )
                  }}
                  placeholder="01FF-… or raw bytes"
                  autoComplete="off"
                  required={index === 0}
                />
              </label>
              <Button
                type="button"
                disabled={codeRows.length <= 1 || busy}
                aria-label={`Remove code row ${index + 1}`}
                onClick={() => {
                  setCodeRows((rows) => rows.filter((item) => item.id !== row.id))
                }}
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
        <div className="od-cheats-panel__actions">
          <Button
            type="button"
            disabled={busy}
            onClick={() => setCodeRows((rows) => [...rows, emptyCodeRow()])}
          >
            Add code row
          </Button>
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save cheat'}
          </Button>
        </div>
      </form>

      <form
        className="od-cheats-panel__upload"
        onSubmit={handleUpload}
        aria-label="Upload cheat file"
      >
        <h3>
          Upload <code>.cht</code>
        </h3>
        <label className="od-cheats-panel__field">
          <span>File</span>
          <input
            className="od-cheats-panel__file"
            type="file"
            accept=".cht,text/plain"
            disabled={busy}
            onChange={(event) => {
              setUploadFile(event.target.files?.[0] || null)
            }}
          />
        </label>
        <div className="od-cheats-panel__actions">
          <Button type="submit" disabled={busy || !uploadFile}>
            {busy ? 'Uploading…' : 'Upload'}
          </Button>
        </div>
      </form>
    </section>
  )
}
