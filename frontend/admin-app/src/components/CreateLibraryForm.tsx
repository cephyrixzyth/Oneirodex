import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import {
  confirmCreateSelected,
  type CandidateRow,
  type LeafCreateResult,
} from '../api/proposeLeafLibrariesApi'
import { errorText } from '../utils/errorText'
import './CreateLibraryForm.css'

interface PlatformOption {
  key: string
  label: string
}

/** A direct, single-library path through the same create + first-scan contract as bulk import. */
export function CreateLibraryForm({ onCreated }: { onCreated?: () => void }) {
  const [platforms, setPlatforms] = useState<PlatformOption[]>([])
  const [platformError, setPlatformError] = useState<unknown>(null)
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [platform, setPlatform] = useState('')
  const [scanMode, setScanMode] = useState<'folders' | 'files'>('folders')
  const [depth, setDepth] = useState<1 | 2>(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<LeafCreateResult | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getJson('/api/admin/library_platforms', { signal: controller.signal })
      .then((data) => {
        const payload = Array.isArray(data) ? data : data?.platforms
        const options = Array.isArray(payload) ? payload : []
        setPlatforms(options)
        setPlatform((current) => current || options[0]?.key || '')
      })
      .catch((err) => {
        if (!controller.signal.aborted) setPlatformError(err)
      })
    return () => controller.abort()
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim() || !path.trim() || !platform) return
    setBusy(true)
    setError('')
    setResult(null)
    const candidate: CandidateRow = {
      id: `manual:${path.trim()}`,
      path: path.trim(),
      suggested_name: name.trim(),
      platform,
      scan_mode: scanMode,
      scan_depth: depth,
      reason: 'Admin-created library',
      source_index: 0,
    }
    try {
      const outcome = await confirmCreateSelected([candidate])
      setResult(outcome.results[0] || null)
      if (outcome.created > 0) {
        setName('')
        setPath('')
        onCreated?.()
      }
      if (outcome.failed) setError(outcome.results[0]?.error || 'Library could not be created.')
    } catch (err) {
      setError(errorText(err) || 'Library could not be created.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="od-admin-panel od-create-library" aria-labelledby="od-create-library-title">
      <div>
        <h2 id="od-create-library-title" className="od-admin-panel-title">Add one library</h2>
        <p className="od-admin-lede">
          Name a game folder, choose its platform, then Oneirodex creates the library and queues its first scan.
        </p>
      </div>
      <PageStatus error={platformError} errorMessage="Unable to load platform choices." />
      <form className="od-create-library__form" onSubmit={(event) => void submit(event)}>
        <label>
          Library name
          <input required value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" />
        </label>
        <label>
          Platform
          <select required value={platform} onChange={(event) => setPlatform(event.target.value)} disabled={!platforms.length}>
            {platforms.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label>
        <label className="od-create-library__path">
          Folder path inside the server
          <input required value={path} onChange={(event) => setPath(event.target.value)} placeholder="/storage/games/nes" autoComplete="off" />
        </label>
        <label>
          Folder layout
          <select value={scanMode} onChange={(event) => setScanMode(event.target.value as 'folders' | 'files')}>
            <option value="folders">Game folders</option>
            <option value="files">Game files directly in this folder</option>
          </select>
        </label>
        <label>
          Scan depth
          <select value={depth} onChange={(event) => setDepth(Number(event.target.value) as 1 | 2)}>
            <option value={1}>One folder deep</option>
            <option value={2}>Two folders deep</option>
          </select>
        </label>
        <div className="od-create-library__actions">
          <Button type="submit" className="od-btn--accent" disabled={busy || !platforms.length || !name.trim() || !path.trim()}>
            {busy ? 'Creating and queueing…' : 'Create library and start scan'}
          </Button>
          <span className="od-admin-lede od-admin-lede--tight">The scan uses the server-visible path; game files stay read-only.</span>
        </div>
      </form>
      {error ? <p className="od-create-library__message od-create-library__message--error" role="alert">{error}</p> : null}
      {result?.note ? <p className="od-create-library__message" role="status">{result.note}</p> : null}
    </section>
  )
}
