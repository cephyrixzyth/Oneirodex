import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { Page } from '../components/Page'

/**
 * Install-wide game-details section order and visibility (`/api/layouts/detail`).
 *
 * First H-D.5 port: this body was `templates/admin/detail_layout.html` plus
 * `static/js/od_admin_detail_layout.js` (a list of rows with Up / Down /
 * visible controls and Save / Reset). Same API, same payload — `sections` is
 * an ordered `{ id, visible }` list, and PUT with an empty list resets to the
 * install default. Members arrange their *own* page from the details view;
 * this is the household default only.
 */

export interface DetailSection {
  id: string
  visible: boolean
}

function normalize(raw: unknown): DetailSection[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((s): s is { id: string; visible?: unknown } => Boolean(s) && typeof s.id === 'string')
    .map((s) => ({ id: s.id, visible: s.visible !== false }))
}

function swap(list: DetailSection[], a: number, b: number): DetailSection[] {
  const next = list.slice()
  ;[next[a], next[b]] = [next[b], next[a]]
  return next
}

export function DetailLayoutPage() {
  const [sections, setSections] = useState<DetailSection[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    getJson('/api/layouts/detail')
      .then((data) => {
        if (cancelled) return
        setSections(normalize(data?.sections))
        setStatus('Loaded')
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  async function put(body: { sections: DetailSection[] }, okText: string, failText: string) {
    if (busy) return
    setBusy(true)
    try {
      const saved = await putJson('/api/layouts/detail', body)
      setSections(normalize(saved?.sections) || [])
      setStatus(okText)
    } catch (err) {
      setStatus(errorText(err) || failText)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page
      title="Detail layout"
      lede={<>Reorder and show/hide sections on the game details page.</>}
    >
      <PageStatus loading={loading} error={loadError} onRetry={() => setReloadKey((k) => k + 1)}>
        {/* A polite live region without a status role: a transient "Saved" / "Reset"
            line, the shape QualityProfilesPage uses. PageStatus owns loading / error. */}
        <p className="od-admin-lede od-admin-lede--flush" aria-live="polite">
          {status}
        </p>
        <ul className="list-group mb-3" aria-label="Detail page sections">
          {sections.map((s, i) => (
            <li key={s.id} className="list-group-item d-flex align-items-center gap-2">
              <strong style={{ minWidth: 120 }}>{s.id}</strong>
              <label className="mb-0">
                <input
                  type="checkbox"
                  checked={s.visible}
                  onChange={(e) =>
                    setSections((prev) =>
                      prev.map((row, j) => (j === i ? { ...row, visible: e.target.checked } : row)),
                    )
                  }
                />{' '}
                visible
              </label>
              <Button
                size="sm"
                variant="secondary"
                className="ms-auto"
                disabled={i === 0 || busy}
                aria-label={`Move ${s.id} up`}
                onClick={() => setSections((prev) => swap(prev, i - 1, i))}
              >
                Up
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={i >= sections.length - 1 || busy}
                aria-label={`Move ${s.id} down`}
                onClick={() => setSections((prev) => swap(prev, i, i + 1))}
              >
                Down
              </Button>
            </li>
          ))}
        </ul>
        <div className="d-flex gap-2">
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => put({ sections }, 'Saved', 'Save failed')}
          >
            Save
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => put({ sections: [] }, 'Reset', 'Reset failed')}
          >
            Reset defaults
          </Button>
        </div>
      </PageStatus>
    </Page>
  )
}
