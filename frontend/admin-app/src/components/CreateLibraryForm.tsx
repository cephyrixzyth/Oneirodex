import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Button, Modal, PageStatus } from '@oneirodex/ui'
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

interface BrowseRoot {
  id: string
  label: string
  path: string
  default?: boolean
}

interface BrowseItem {
  name: string
  isDir: boolean
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
  const [browseOpen, setBrowseOpen] = useState(false)
  const [browseRoots, setBrowseRoots] = useState<BrowseRoot[]>([])
  const [browseRoot, setBrowseRoot] = useState('')
  const [browsePath, setBrowsePath] = useState('')
  const [browseItems, setBrowseItems] = useState<BrowseItem[]>([])
  const [browseBusy, setBrowseBusy] = useState(false)
  const [browseError, setBrowseError] = useState('')
  const browseTitleId = useId()
  const closeBrowseRef = useRef<HTMLButtonElement | null>(null)
  const closeBrowser = useCallback(() => setBrowseOpen(false), [])

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

  async function openBrowser() {
    setBrowseOpen(true)
    setBrowseBusy(true)
    setBrowseError('')
    try {
      const data = await getJson('/api/library_roots')
      const roots: BrowseRoot[] = Array.isArray(data.roots) ? data.roots : []
      setBrowseRoots(roots)
      const selected = roots.find((root) => root.default) || roots[0]
      if (selected) {
        setBrowseRoot(selected.id)
        setBrowsePath('')
        const items = await getJson(
          `/api/browse_folders_ss?${new URLSearchParams({ root: selected.id })}`,
        )
        setBrowseItems(Array.isArray(items) ? items.filter((item) => item.isDir) : [])
      } else {
        setBrowseItems([])
        setBrowseError('No server scan locations are configured.')
      }
    } catch (err) {
      setBrowseError(errorText(err) || 'Unable to browse server folders.')
    } finally {
      setBrowseBusy(false)
    }
  }

  async function openBrowseFolder(rootId: string, relativePath: string) {
    setBrowseBusy(true)
    setBrowseError('')
    try {
      const query = new URLSearchParams({ root: rootId, path: relativePath })
      const items = await getJson(`/api/browse_folders_ss?${query}`)
      setBrowseRoot(rootId)
      setBrowsePath(relativePath)
      setBrowseItems(Array.isArray(items) ? items.filter((item) => item.isDir) : [])
    } catch (err) {
      setBrowseError(errorText(err) || 'Unable to read this server folder.')
    } finally {
      setBrowseBusy(false)
    }
  }

  return (
    <section className="od-admin-panel od-create-library" aria-labelledby="od-create-library-title">
      <div>
        <h2 id="od-create-library-title" className="od-admin-panel-title">
          Add one library
        </h2>
        <p className="od-admin-lede">
          Name a game folder, choose its platform, then Oneirodex creates the library and queues its
          first scan.
        </p>
      </div>
      <PageStatus
        error={platformError || error || null}
        errorMessage={platformError ? 'Unable to load platform choices.' : error || null}
        className="od-create-library__message od-create-library__message--error"
      />
      <form className="od-create-library__form" onSubmit={(event) => void submit(event)}>
        <label>
          Library name
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="off"
          />
        </label>
        <label>
          Platform
          <select
            required
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            disabled={!platforms.length}
          >
            {platforms.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="od-create-library__path">
          Folder path inside the server
          <span className="od-create-library__path-row">
            <input
              required
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="/storage/games/nes"
              autoComplete="off"
            />
            <Button type="button" className="od-btn--ghost" onClick={() => void openBrowser()}>
              Browse server
            </Button>
          </span>
        </label>
        <label>
          Folder layout
          <select
            value={scanMode}
            onChange={(event) => setScanMode(event.target.value as 'folders' | 'files')}
          >
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
          <Button
            type="submit"
            className="od-btn--accent"
            disabled={busy || !platforms.length || !name.trim() || !path.trim()}
          >
            {busy ? 'Creating and queueing…' : 'Create library and start scan'}
          </Button>
          <span className="od-admin-lede od-admin-lede--tight">
            The scan uses the server-visible path; game files stay read-only.
          </span>
        </div>
      </form>
      {result?.note ? (
        <PageStatus emptyMessage={result.note} className="od-create-library__message" />
      ) : null}
      {browseOpen ? (
        <Modal
          open
          onClose={closeBrowser}
          labelledBy={browseTitleId}
          className="od-library-browser__backdrop"
          panelClassName="od-library-browser"
          initialFocusRef={closeBrowseRef}
          lockScroll
        >
          <>
            <header className="od-library-browser__header">
              <div>
                <h2 id={browseTitleId}>Choose a server folder</h2>
                <p className="od-admin-lede">Browse folders mounted inside Oneirodex.</p>
              </div>
              <Button
                ref={closeBrowseRef}
                type="button"
                className="od-btn--ghost"
                onClick={closeBrowser}
              >
                Close
              </Button>
            </header>
            {browseRoots.length > 1 ? (
              <label className="od-admin-field">
                Scan location
                <select
                  value={browseRoot}
                  onChange={(event) => void openBrowseFolder(event.target.value, '')}
                >
                  {browseRoots.map((root) => (
                    <option key={root.id} value={root.id}>
                      {root.label} · {root.path}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {(() => {
              const root = browseRoots.find((item) => item.id === browseRoot)
              const parts = browsePath.split('/').filter(Boolean)
              return root ? (
                <nav className="od-library-browser__crumbs" aria-label="Folder path">
                  <Button
                    type="button"
                    className="od-btn--ghost"
                    onClick={() => void openBrowseFolder(root.id, '')}
                  >
                    {root.path}
                  </Button>
                  {parts.map((part, index) => (
                    <Button
                      key={`${part}-${index}`}
                      type="button"
                      className="od-btn--ghost"
                      onClick={() =>
                        void openBrowseFolder(root.id, parts.slice(0, index + 1).join('/'))
                      }
                    >
                      {part}
                    </Button>
                  ))}
                </nav>
              ) : null
            })()}
            {browseError ? (
              <PageStatus
                error={browseError}
                className="od-create-library__message od-create-library__message--error"
                errorMessage="Unable to browse server folders."
              />
            ) : null}
            <div className="od-library-browser__list" aria-busy={browseBusy}>
              {browseBusy ? (
                <p className="od-admin-lede">Loading folders…</p>
              ) : browseItems.length ? (
                browseItems.map((item) => (
                  <Button
                    key={item.name}
                    type="button"
                    className="od-library-browser__folder"
                    onClick={() =>
                      void openBrowseFolder(
                        browseRoot,
                        [...browsePath.split('/').filter(Boolean), item.name].join('/'),
                      )
                    }
                  >
                    <span aria-hidden="true">📁</span>
                    {item.name}
                  </Button>
                ))
              ) : !browseError ? (
                <p className="od-admin-lede">No folders here.</p>
              ) : null}
            </div>
            <footer className="od-library-browser__footer">
              <span className="od-admin-lede">
                {browseRoots.find((root) => root.id === browseRoot)?.path}
                {browsePath ? `/${browsePath}` : ''}
              </span>
              <Button
                type="button"
                className="od-btn--accent"
                disabled={!browseRoot}
                onClick={() => {
                  const root = browseRoots.find((item) => item.id === browseRoot)
                  if (root)
                    setPath(
                      [root.path.replace(/[\\/]+$/, ''), browsePath].filter(Boolean).join('/'),
                    )
                  setBrowseOpen(false)
                }}
              >
                Use this folder
              </Button>
            </footer>
          </>
        </Modal>
      ) : null}
    </section>
  )
}
