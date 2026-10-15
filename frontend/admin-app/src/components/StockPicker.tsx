import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageStatus, Button } from '@oneirodex/ui'
import { postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const STOCK_CATALOG_URL = '/admin/api/art-studio/stock'
const STOCK_GENERATE_URL = '/admin/api/art-studio/stock/generate'
const APPLY_URL = '/admin/api/art-studio/apply'

export interface StockItem {
  id: string
  label: string
  kind: 'platform' | 'era' | 'stock'
  platform: string
  packId: string
  thumb: string
  preview: string
  generated: boolean
  hint: string
}

/**
 * Normalize Backend catalog payloads.
 * Contract: GET /admin/api/art-studio/stock → { items, count }
 * Item: { id, label, kind, platform?, pack_id, path, urls{tile,wide,hero}, generated }
 */
export function normalizeStockCatalog(data: unknown): StockItem[] {
  if (!data) return []
  const payload = data as Record<string, unknown>
  const raw = Array.isArray(data)
    ? data
    : payload.items || payload.catalog || payload.stock || payload.packs || []
  if (!Array.isArray(raw)) return []
  return raw
    .map((rawRow, index): StockItem | null => {
      if (!rawRow || typeof rawRow !== 'object') return null
      const row = rawRow as Record<string, unknown>
      const id = String(row.id || row.pack_id || row.key || `item-${index}`)
      const urls = (row.urls && typeof row.urls === 'object' ? row.urls : {}) as Record<
        string,
        unknown
      >
      const generated = Boolean(row.generated)
      const thumb = generated
        ? String(urls.tile || urls.thumb || urls.wide || row.thumb_url || row.preview_url || '')
        : ''
      const preview = generated
        ? String(urls.wide || urls.hero || urls.tile || row.preview_url || thumb || '')
        : ''
      return {
        id,
        label: String(row.label || row.name || row.title || id),
        kind: row.kind === 'platform' ? 'platform' : row.kind === 'era' ? 'era' : 'stock',
        platform: row.platform ? String(row.platform) : '',
        packId: String(row.pack_id || row.packId || id),
        thumb,
        preview,
        generated,
        hint: String(row.hint || row.description || ''),
      }
    })
    .filter((item): item is StockItem => item != null)
}

async function fetchStockCatalog(): Promise<{ unavailable: boolean; items: StockItem[] }> {
  const response = await fetch(STOCK_CATALOG_URL, { credentials: 'same-origin' })
  if (response.status === 401) {
    window.location.href = '/login'
    throw new Error('unauthorized')
  }
  if (response.status === 404) {
    return { unavailable: true, items: [] }
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || data.message || `stock catalog ${response.status}`)
  }
  return { unavailable: false, items: normalizeStockCatalog(data) }
}

/**
 * Platform + stock motif grid for Art Studio Backup & stock tab.
 * Soft-empty when catalog API returns 404.
 */
export function StockPicker({
  onApplied,
  heading = 'Platform & stock art',
  lede = 'Original Oneirodex packs — pick a decade room, platform look, or stock motif, then set as library default / fallback.',
  showLibraryUuid = false,
}: {
  onApplied?: (v?: unknown) => void
  heading?: string
  lede?: string
  showLibraryUuid?: boolean
} = {}) {
  const [items, setItems] = useState<StockItem[]>([])
  const [unavailable, setUnavailable] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState('')
  const [libraryUuid, setLibraryUuid] = useState('')
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState('')

  const loadCatalog = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchStockCatalog()
      setUnavailable(Boolean(result.unavailable))
      setItems(result.items)
      if (result.unavailable) {
        setStatus('Stock catalog API not available yet — use Studio generate + Set as fallback.')
      } else if (!result.items.length) {
        setStatus('Catalog is empty. Generate platform packs on the server, then refresh.')
      } else {
        const pending = result.items.filter((i) => !i.generated).length
        setStatus(
          pending
            ? `${result.items.length} packs · ${pending} need generate before preview files exist.`
            : '',
        )
      }
    } catch (err) {
      setError(errorText(err) || 'Could not load stock catalog')
      setItems([])
      setUnavailable(false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCatalog()
  }, [loadCatalog])

  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) || null,
    [items, selectedId],
  )

  const visible = useMemo(() => {
    if (filter === 'platform') return items.filter((i) => i.kind === 'platform')
    if (filter === 'stock') return items.filter((i) => i.kind === 'stock')
    if (filter === 'era') return items.filter((i) => i.kind === 'era')
    return items
  }, [items, filter])

  const ensureGenerated = useCallback(async (item: StockItem): Promise<StockItem> => {
    if (item.generated) return item
    await postJson(STOCK_GENERATE_URL, { ids: [item.packId || item.id] })
    const refreshed = await fetchStockCatalog()
    if (!refreshed.unavailable) {
      setItems(refreshed.items)
      const next = refreshed.items.find((row) => row.id === item.id)
      if (next) return next
    }
    return { ...item, generated: true }
  }, [])

  const applySelected = useCallback(
    async (mode: string) => {
      if (!selected) {
        setError('Select an image first.')
        return
      }
      if (mode === 'library' && !libraryUuid.trim()) {
        setError('Enter a library UUID to apply.')
        return
      }
      setBusy(mode)
      setError('')
      setStatus('')
      try {
        const ready = await ensureGenerated(selected)
        const packId = ready.packId || ready.id
        const body: Record<string, unknown> = { pack_id: packId, id: packId, mode }
        if (mode === 'library') body.library_uuid = libraryUuid.trim()
        await postJson(APPLY_URL, body)
        const label =
          mode === 'library'
            ? `Applied “${ready.label}” to library`
            : `Set “${ready.label}” as library default / fallback`
        setStatus(label)
        showToast(label, 'success')
        onApplied?.({ item: ready, mode })
        await loadCatalog()
      } catch (err) {
        const text = errorText(err) || 'Apply failed'
        setError(text)
        showToast(text, 'error')
      } finally {
        setBusy('')
      }
    },
    [selected, libraryUuid, onApplied, ensureGenerated, loadCatalog],
  )

  const generateSelected = useCallback(async () => {
    if (!selected) {
      setError('Select an image first.')
      return
    }
    setBusy('generate')
    setError('')
    try {
      await postJson(STOCK_GENERATE_URL, { ids: [selected.packId || selected.id] })
      showToast(`Generated “${selected.label}”`, 'success')
      await loadCatalog()
      setStatus(`Pack “${selected.label}” ready.`)
    } catch (err) {
      const text = errorText(err) || 'Generate failed'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy('')
    }
  }, [selected, loadCatalog])

  return (
    <section className="od-stock-picker" aria-label={heading} data-testid="stock-picker">
      <div className="od-stock-picker__head">
        <div>
          <h2 className="od-admin-panel-title">{heading}</h2>
          <p className="od-admin-lede">{lede}</p>
        </div>
        <Button type="button" disabled={loading || Boolean(busy)} onClick={loadCatalog}>
          Refresh
        </Button>
      </div>

      {/* The `status` line below is progress text for one action, not a page
          state, so it stays as it is. */}
      <PageStatus error={error} />
      {status ? (
        <PageStatus announcement="status" className="od-admin-lede">
          {status}
        </PageStatus>
      ) : null}

      <div className="od-stock-picker__filters" role="group" aria-label="Catalog filter">
        {[
          { id: 'all', label: 'All' },
          { id: 'era', label: 'Decade rooms' },
          { id: 'platform', label: 'Platforms' },
          { id: 'stock', label: 'Stock motifs' },
        ].map((f) => (
          <button
            key={f.id}
            type="button"
            className={`od-stock-picker__filter${filter === f.id ? ' is-active' : ''}`}
            aria-pressed={filter === f.id}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <PageStatus loading loadingMessage="Loading catalog…" className="od-stock-picker__empty" />
      ) : unavailable ? (
        <div className="od-stock-picker__empty" data-testid="stock-picker-unavailable">
          <p className="od-stock-picker__empty-title">Stock catalog coming online</p>
          <p>
            <code>GET {STOCK_CATALOG_URL}</code> is not available yet. Use Studio generate + Set as
            fallback until the pack list ships.
          </p>
        </div>
      ) : visible.length === 0 ? (
        <div className="od-stock-picker__empty" data-testid="stock-picker-empty">
          <p className="od-stock-picker__empty-title">No packs in this filter</p>
          <p>Try All, or regenerate stock packs on the server.</p>
        </div>
      ) : (
        <div className="od-stock-picker__grid" data-testid="stock-picker-grid">
          {visible.map((item) => {
            const selectedNow = item.id === selectedId
            return (
              <button
                key={item.id}
                type="button"
                className={`od-stock-picker__card${selectedNow ? ' is-selected' : ''}${
                  item.generated ? '' : ' is-pending'
                }`}
                aria-label={item.label}
                aria-pressed={selectedNow}
                onClick={() => setSelectedId(item.id)}
              >
                <span className="od-stock-picker__thumb">
                  {item.thumb ? (
                    <img
                      src={item.thumb}
                      alt=""
                      loading="lazy"
                      onError={(e) => {
                        e.currentTarget.style.display = 'none'
                      }}
                    />
                  ) : (
                    <span className="od-stock-picker__thumb-ph" aria-hidden="true">
                      {item.kind === 'platform' ? '◆' : item.kind === 'era' ? '▣' : '◇'}
                    </span>
                  )}
                </span>
                <span className="od-stock-picker__meta">
                  <strong>{item.label}</strong>
                  <span className="od-stock-picker__kind">
                    {item.kind === 'platform'
                      ? item.platform
                        ? `Platform · ${item.platform}`
                        : 'Platform'
                      : item.kind === 'era'
                        ? 'Decade room'
                        : 'Stock motif'}
                    {item.generated ? '' : ' · needs generate'}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {selected ? (
        <div className="od-stock-picker__preview" data-testid="stock-picker-preview">
          <figure>
            {selected.preview ? (
              <img src={selected.preview} alt={`Preview of ${selected.label}`} />
            ) : (
              <div className="od-stock-picker__thumb-ph od-stock-picker__thumb-ph--lg">
                {selected.generated
                  ? selected.label
                  : `${selected.label} — generate to paint files`}
              </div>
            )}
            <figcaption>
              <strong>{selected.label}</strong>
              <span>
                {selected.kind === 'platform' ? 'Platform pack' : 'Stock motif'}
                {selected.platform ? ` · ${selected.platform}` : ''}
              </span>
              {selected.hint ? <span>{selected.hint}</span> : null}
            </figcaption>
          </figure>
          <div className="od-stock-picker__actions">
            {!selected.generated ? (
              <Button type="button" disabled={Boolean(busy)} onClick={generateSelected}>
                {busy === 'generate' ? 'Generating…' : 'Generate pack'}
              </Button>
            ) : null}
            <Button
              type="button"
              variant="primary"
              disabled={Boolean(busy)}
              onClick={() => applySelected('fallback')}
            >
              {busy === 'fallback' ? 'Applying…' : 'Use as library default'}
            </Button>
            <Button
              type="button"
              disabled={Boolean(busy)}
              onClick={() => applySelected('fallback')}
            >
              {busy === 'fallback' ? 'Applying…' : 'Set fallback'}
            </Button>
            {showLibraryUuid ? (
              <>
                <label className="od-stock-picker__uuid">
                  <span>Library UUID</span>
                  <input
                    type="text"
                    value={libraryUuid}
                    onChange={(e) => setLibraryUuid(e.target.value)}
                    placeholder="library uuid"
                    autoComplete="off"
                  />
                </label>
                <Button
                  type="button"
                  disabled={Boolean(busy) || !libraryUuid.trim()}
                  onClick={() => applySelected('library')}
                >
                  {busy === 'library' ? 'Applying…' : 'Apply to library'}
                </Button>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
