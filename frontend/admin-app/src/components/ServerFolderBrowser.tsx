import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Button, Modal, PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import './ServerFolderBrowser.css'

export interface ServerFolderRoot {
  id: string
  label: string
  path: string
  default?: boolean
  exists?: boolean
  read?: boolean
}

interface BrowseItem {
  name: string
  isDir: boolean
}

export interface ServerFolderSelection {
  root: ServerFolderRoot
  /** Path below the root, `''` for the root itself. */
  relativePath: string
  /** Root path joined with `relativePath`. */
  absolutePath: string
}

const usable = (root: ServerFolderRoot) => root.exists !== false && root.read !== false

/**
 * The server folder picker popup, shared by "Add one library" and the Scan
 * page so both open the same dialog: a location switcher, breadcrumbs, a folder
 * list and "Use this folder". It loads `/api/library_roots` itself and opens on
 * `initialRootId` / `initialPath` when given.
 */
export function ServerFolderBrowser({
  open,
  onClose,
  onSelect,
  title = 'Choose a server folder',
  initialRootId,
  initialPath = '',
}: {
  open: boolean
  onClose: () => void
  onSelect: (selection: ServerFolderSelection) => void
  title?: string
  initialRootId?: string
  initialPath?: string
}) {
  const [roots, setRoots] = useState<ServerFolderRoot[]>([])
  const [rootId, setRootId] = useState('')
  const [path, setPath] = useState('')
  const [items, setItems] = useState<BrowseItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const titleId = useId()
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const requestRef = useRef(0)

  const openFolder = useCallback(async (nextRoot: string, relativePath: string) => {
    const request = ++requestRef.current
    setBusy(true)
    setError('')
    try {
      const query = new URLSearchParams({ root: nextRoot, path: relativePath })
      const payload = await getJson(`/api/browse_folders_ss?${query}`)
      if (request !== requestRef.current) return false
      if (!Array.isArray(payload)) throw new Error('Folder browser returned an invalid response.')
      setRootId(nextRoot)
      setPath(relativePath)
      setItems((payload as BrowseItem[]).filter((item) => item.isDir))
      return true
    } catch (err) {
      if (request === requestRef.current) {
        setError(errorText(err) || 'Unable to read this server folder.')
      }
      return false
    } finally {
      if (request === requestRef.current) setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setBusy(true)
    setError('')
    setItems([])
    getJson('/api/library_roots')
      .then(async (data) => {
        if (cancelled) return
        const list: ServerFolderRoot[] = Array.isArray(data?.roots) ? data.roots : []
        setRoots(list)
        const start =
          list.find((root) => root.id === initialRootId && usable(root)) ||
          list.find((root) => root.default && usable(root)) ||
          list.find(usable)
        if (!start) {
          setBusy(false)
          setError('No server scan locations are configured.')
          return
        }
        const wanted = initialPath.split('/').filter(Boolean).join('/')
        // Open where the form already points; fall back to the location root
        // when that folder is gone or was typed by hand.
        if (wanted && (await openFolder(start.id, wanted))) return
        if (!cancelled) await openFolder(start.id, '')
      })
      .catch((err) => {
        if (cancelled) return
        setBusy(false)
        setError(errorText(err) || 'Unable to browse server folders.')
      })
    return () => {
      cancelled = true
    }
    // Open once per showing; the initial values are read at that moment only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  if (!open) return null
  const root = roots.find((item) => item.id === rootId)
  const parts = path.split('/').filter(Boolean)
  const absolutePath = root
    ? [root.path.replace(/[\\/]+$/, ''), path].filter(Boolean).join('/')
    : ''

  return (
    <Modal
      open
      onClose={onClose}
      labelledBy={titleId}
      className="od-library-browser__backdrop"
      panelClassName="od-library-browser"
      initialFocusRef={closeRef}
      lockScroll
    >
      <header className="od-library-browser__header">
        <div>
          <h2 id={titleId}>{title}</h2>
          <p className="od-admin-lede">Browse folders mounted inside Oneirodex.</p>
        </div>
        <Button ref={closeRef} type="button" className="od-btn--ghost" onClick={onClose}>
          Close
        </Button>
      </header>
      {roots.length > 1 ? (
        <label className="od-admin-field">
          Scan location
          <select
            className="od-admin-input"
            value={rootId}
            onChange={(event) => void openFolder(event.target.value, '')}
            disabled={busy}
          >
            {roots.map((item) => (
              <option key={item.id} value={item.id} disabled={!usable(item)}>
                {item.label} · {item.path}
                {usable(item) ? '' : ' · unavailable'}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {root ? (
        <nav className="od-library-browser__crumbs" aria-label="Folder path">
          <Button
            type="button"
            className="od-btn--ghost"
            onClick={() => void openFolder(root.id, '')}
          >
            {root.path}
          </Button>
          {parts.map((part, index) => (
            <Button
              key={`${part}-${index}`}
              type="button"
              className="od-btn--ghost"
              onClick={() => void openFolder(root.id, parts.slice(0, index + 1).join('/'))}
            >
              {part}
            </Button>
          ))}
        </nav>
      ) : null}
      {error ? (
        <PageStatus
          error={error}
          className="od-library-browser__message"
          errorMessage="Unable to browse server folders."
        />
      ) : null}
      <div className="od-library-browser__list" aria-busy={busy}>
        {busy ? (
          <p className="od-admin-lede">Loading folders…</p>
        ) : items.length ? (
          items.map((item) => (
            <Button
              key={item.name}
              type="button"
              className="od-library-browser__folder"
              onClick={() => void openFolder(rootId, [...parts, item.name].join('/'))}
            >
              <span aria-hidden="true">📁</span>
              {item.name}
            </Button>
          ))
        ) : !error ? (
          <p className="od-admin-lede">No folders here.</p>
        ) : null}
      </div>
      <footer className="od-library-browser__footer">
        <span className="od-admin-lede">{absolutePath}</span>
        <Button
          type="button"
          className="od-btn--accent"
          disabled={!root || busy}
          onClick={() => {
            if (!root) return
            onSelect({ root, relativePath: path, absolutePath })
            onClose()
          }}
        >
          Use this folder
        </Button>
      </footer>
    </Modal>
  )
}
