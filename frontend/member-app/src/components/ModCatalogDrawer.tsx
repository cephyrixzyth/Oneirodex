import { useCallback, useEffect, useState } from 'react'
import { Button, Modal, safeExternalUrl } from '@oneirodex/ui'
import { browseModCatalog, MOD_CATALOG_SOURCES, type ModHit } from '../api/mods'
import { PageStatus } from './PageStatus'

/**
 * Browse a community mod registry for this game (INSP-22).
 *
 * Read-only by construction: every row is a name, a version, the loader it
 * needs and the registry page. "Add to list" hands the row to the panel,
 * which files it through the same POST a librarian would type by hand — the
 * source URL is the *registry page*, never an archive. Nothing here downloads.
 */
export function ModCatalogDrawer({
  gameUuid,
  open,
  onClose,
  onAdd,
  onNoteUpdate,
  defaultSource = 'thunderstore',
}: {
  gameUuid: string
  open: boolean
  onClose: () => void
  /** Adds the hit and, when it names dependencies present in the same list, those too (INSP-38). */
  onAdd: (hit: ModHit, dependencies: ModHit[]) => Promise<void> | void
  /** Records a registry's newer version on the tracked row (INSP-39). */
  onNoteUpdate?: (hit: ModHit) => Promise<void> | void
  defaultSource?: string
}) {
  const [source, setSource] = useState(defaultSource)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<ModHit[] | null>(null)
  const [status, setStatus] = useState<'idle' | 'ok' | 'unavailable' | 'unknown_source'>('idle')
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState<string | null>(null)

  const run = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true)
      setError('')
      try {
        const result = await browseModCatalog(gameUuid, source, query.trim(), { signal })
        if (signal?.aborted) return
        setHits(result.hits)
        setStatus(result.status)
        setNote(result.note || '')
      } catch (err) {
        if (signal?.aborted) return
        setError(err instanceof Error ? err.message : 'Could not browse the catalogue')
        setHits(null)
        setStatus('unavailable')
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [gameUuid, source, query],
  )

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    void run(controller.signal)
    return () => controller.abort()
    // Re-run on source change only; the query runs on submit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, source, gameUuid])

  function dependenciesOf(hit: ModHit): ModHit[] {
    const wanted = new Set((hit.dependencies || []).map((d) => d.toLowerCase()))
    if (wanted.size === 0 || !hits) return []
    return hits.filter(
      (other) =>
        other.url !== hit.url &&
        Boolean(safeExternalUrl(other.url)) &&
        !other.tracked_id &&
        wanted.has(other.name.toLowerCase()),
    )
  }

  async function add(hit: ModHit) {
    if (!safeExternalUrl(hit.url)) return
    setAdding(hit.url)
    try {
      await onAdd(hit, dependenciesOf(hit))
    } finally {
      setAdding(null)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      label="Browse mod catalogue"
      panelClassName="od-modcat__panel"
      lockScroll
    >
      <div className="od-modcat">
        <div className="od-modcat__head">
          <h3 className="od-modcat__title">Browse a mod catalogue</h3>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        <p className="od-modcat__lede">
          Names, versions and registry pages from a public community registry. Adding a row records
          the page — the companion only ever stages a URL the librarian chose. Nothing here
          downloads.
        </p>
        <form
          className="od-modcat__controls"
          onSubmit={(event) => {
            event.preventDefault()
            void run()
          }}
        >
          <div className="od-modcat__sources" role="tablist" aria-label="Catalogue source">
            {MOD_CATALOG_SOURCES.map((row) => (
              <Button
                key={row.id}
                type="button"
                size="sm"
                pill
                variant={row.id === source ? 'primary' : 'ghost'}
                role="tab"
                aria-selected={row.id === source}
                onClick={() => setSource(row.id)}
              >
                {row.label}
              </Button>
            ))}
          </div>
          <label className="od-modcat__search">
            <span>Search</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Leave empty for the most popular"
            />
          </label>
          <Button type="submit" size="sm" disabled={loading}>
            {loading ? 'Searching…' : 'Search'}
          </Button>
        </form>

        <PageStatus
          loading={loading}
          error={error}
          loadingMessage="Asking the registry…"
          className="od-modcat__status"
        />

        {!loading && !error && status === 'unavailable' ? (
          <p className="od-modcat__muted">{note || 'The registry had no data for this title.'}</p>
        ) : null}
        {!loading && !error && status === 'ok' && hits && hits.length === 0 ? (
          <p className="od-modcat__muted">
            The registry answered and found nothing for this search.
          </p>
        ) : null}

        {hits && hits.length > 0 ? (
          <ul className="od-modcat__list">
            {hits.map((hit) => {
              const registryUrl = safeExternalUrl(hit.url)
              return (
                <li key={`${hit.source}:${hit.url}`} className="od-modcat__item">
                  <div className="od-modcat__row">
                    <strong className="od-modcat__name">{hit.name}</strong>
                    {hit.version ? <span className="od-modcat__meta">v{hit.version}</span> : null}
                    {hit.loader ? <span className="od-modcat__loader">{hit.loader}</span> : null}
                    {hit.author ? <span className="od-modcat__meta">by {hit.author}</span> : null}
                    {typeof hit.downloads === 'number' ? (
                      <span className="od-modcat__meta">
                        {hit.downloads.toLocaleString()} downloads
                      </span>
                    ) : null}
                    {hit.tracked_id ? <span className="od-modcat__tracked">tracked</span> : null}
                    {hit.update_available ? (
                      <span className="od-modcat__update">update: v{hit.update_available}</span>
                    ) : null}
                  </div>
                  {hit.dependencies && hit.dependencies.length ? (
                    <p className="od-modcat__deps">Needs: {hit.dependencies.join(', ')}</p>
                  ) : null}
                  {hit.summary ? <p className="od-modcat__summary">{hit.summary}</p> : null}
                  <div className="od-modcat__actions">
                    {registryUrl ? (
                      <a
                        className="od-modcat__link"
                        href={registryUrl}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        Registry page
                      </a>
                    ) : (
                      <span className="od-modcat__link">Registry link unavailable</span>
                    )}
                    {hit.tracked_id && hit.update_available && onNoteUpdate ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={!registryUrl || adding === hit.url}
                        onClick={() => void onNoteUpdate(hit)}
                      >
                        Mark updated to v{hit.update_available}
                      </Button>
                    ) : hit.tracked_id ? null : (
                      <Button
                        type="button"
                        size="sm"
                        disabled={!registryUrl || adding === hit.url}
                        onClick={() => void add(hit)}
                      >
                        {adding === hit.url
                          ? 'Adding…'
                          : dependenciesOf(hit).length
                            ? `Add with ${dependenciesOf(hit).length} needed`
                            : 'Add to list'}
                      </Button>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>
    </Modal>
  )
}
