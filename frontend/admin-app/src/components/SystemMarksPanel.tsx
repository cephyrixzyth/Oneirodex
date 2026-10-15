import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { PageStatus, Button } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const CATALOG_URL = '/admin/api/art-studio/system-marks'
const GENERATE_URL = '/admin/api/art-studio/system-marks/generate'
const LAB_URL = '/admin/api/art-studio/system-marks/lab'
const DEFAULT_LAB_PLATFORM = 'nes'

export interface SystemMarksRow {
  theme: string
  era: string
  generated: number
  total: number
  complete: boolean
  platforms: string[]
}

export interface PlatformChoice {
  id: string
  label: string
}

interface LabLogRow {
  id: string
  theme: string
  platform: string
  generated: number
  skipped: number
  error: string
  prompt: string
}

/**
 * Normalize GET /admin/api/art-studio/system-marks → theme progress rows.
 * Item: { theme, era, generated, total, complete, platforms }
 */
export function normalizeSystemMarksCatalog(data: unknown): SystemMarksRow[] {
  if (!data) return []
  const payload = data as Record<string, unknown>
  const raw = Array.isArray(data) ? data : payload.items || payload.catalog || []
  if (!Array.isArray(raw)) return []
  return raw
    .map((rawRow, index): SystemMarksRow | null => {
      if (!rawRow || typeof rawRow !== 'object') return null
      const row = rawRow as Record<string, unknown>
      const theme = String(row.theme || row.slug || `theme-${index}`)
      const generated = Number(row.generated) || 0
      const total = Number(row.total) || 0
      return {
        theme,
        era: String(row.era || ''),
        generated,
        total,
        complete: Boolean(row.complete) || (total > 0 && generated >= total),
        platforms: Array.isArray(row.platforms) ? row.platforms.map(String) : [],
      }
    })
    .filter((row): row is SystemMarksRow => row != null)
}

export function normalizePlatformChoices(data: unknown): PlatformChoice[] {
  const payload = data as Record<string, unknown> | undefined
  const raw = Array.isArray(data) ? data : payload?.all_platforms || []
  if (!Array.isArray(raw)) return []
  return raw
    .map((row): PlatformChoice | null => {
      if (typeof row === 'string') return { id: row, label: row }
      if (!row || typeof row !== 'object') return null
      const r = row as Record<string, unknown>
      const id = String(r.id || r.platform || '').trim()
      if (!id) return null
      return { id, label: String(r.label || id) }
    })
    .filter((row): row is PlatformChoice => row != null)
}

async function fetchCatalog(): Promise<{
  unavailable: boolean
  items: SystemMarksRow[]
  allPlatforms: PlatformChoice[]
}> {
  const response = await fetch(CATALOG_URL, { credentials: 'same-origin' })
  if (response.status === 401) {
    window.location.href = '/login'
    throw new Error('unauthorized')
  }
  if (response.status === 404) {
    return { unavailable: true, items: [], allPlatforms: [] }
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || data.message || `system-marks catalog ${response.status}`)
  }
  return {
    unavailable: false,
    items: normalizeSystemMarksCatalog(data),
    allPlatforms: normalizePlatformChoices(data),
  }
}

/**
 * Per-theme AI Systems hub marks — catalog progress + idempotent generate.
 * Requires ENABLE_AI_ARTWORK on the server.
 */
export function SystemMarksPanel() {
  const [items, setItems] = useState<SystemMarksRow[]>([])
  const [allPlatforms, setAllPlatforms] = useState<PlatformChoice[]>([])
  const [unavailable, setUnavailable] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState('')
  const [selectedTheme, setSelectedTheme] = useState('')
  const [labPlatform, setLabPlatform] = useState(DEFAULT_LAB_PLATFORM)
  const [labPrompt, setLabPrompt] = useState('')
  const [labDefaultPrompt, setLabDefaultPrompt] = useState('')
  const [labExists, setLabExists] = useState(false)
  const [labUrl, setLabUrl] = useState('')
  const [labBust, setLabBust] = useState(0)
  const [labLog, setLabLog] = useState<LabLogRow[]>([])

  const loadCatalog = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchCatalog()
      setUnavailable(Boolean(result.unavailable))
      setItems(result.items)
      setAllPlatforms(result.allPlatforms)
      if (result.unavailable) {
        setStatus('System marks API not available yet.')
      } else if (!result.items.length) {
        setStatus('No theme rows. Check preset theme install.')
      } else {
        const incomplete = result.items.filter((row: SystemMarksRow) => !row.complete).length
        setStatus(
          incomplete
            ? `${result.items.length} themes · ${incomplete} still missing platforms.`
            : `${result.items.length} themes · all platforms present.`,
        )
        setSelectedTheme((current) => current || result.items[0].theme)
      }
    } catch (err) {
      setError(errorText(err) || 'Could not load system marks catalog')
      setItems([])
      setUnavailable(false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCatalog()
  }, [loadCatalog])

  useEffect(() => {
    if (!selectedTheme || !labPlatform) return undefined
    let cancelled = false
    getJson(
      `${LAB_URL}?theme=${encodeURIComponent(selectedTheme)}&platform=${encodeURIComponent(labPlatform)}`,
    )
      .then((spec) => {
        if (cancelled) return
        const prompt = String(spec.prompt || '')
        setLabDefaultPrompt(prompt)
        setLabPrompt(prompt)
        setLabExists(Boolean(spec.exists))
        setLabUrl(String(spec.url || ''))
      })
      .catch((err) => {
        if (cancelled) return
        setLabDefaultPrompt('')
        setLabPrompt('')
        setLabExists(false)
        setLabUrl('')
        setError(errorText(err) || 'Could not load lab spec')
      })
    return () => {
      cancelled = true
    }
  }, [selectedTheme, labPlatform])

  const runGenerate = useCallback(
    async ({
      themes,
      force = false,
      limit = null,
    }: { themes?: string[]; force?: boolean; limit?: number | null } = {}) => {
      setBusy(force ? 'force' : 'generate')
      setError('')
      setStatus('')
      try {
        const body: Record<string, unknown> = { force }
        if (themes?.length) body.themes = themes
        if (limit != null) body.limit = limit
        const result = await postJson(GENERATE_URL, body)
        const generated = Number(result?.generated) || 0
        const skipped = Number(result?.skipped) || 0
        const errCount = Array.isArray(result?.errors) ? result.errors.length : 0
        const label = `Marks: generated ${generated}, skipped ${skipped}${
          errCount ? `, errors ${errCount}` : ''
        }`
        setStatus(label)
        showToast(label, errCount && !generated ? 'error' : 'success')
        await loadCatalog()
      } catch (err) {
        const text = errorText(err) || 'Generate failed'
        setError(text)
        showToast(text, 'error')
      } finally {
        setBusy('')
      }
    },
    [loadCatalog],
  )

  const runLabGenerate = useCallback(async () => {
    if (!selectedTheme || !labPlatform) return
    setBusy('lab')
    setError('')
    try {
      const result = await postJson(GENERATE_URL, {
        themes: [selectedTheme],
        platforms: [labPlatform],
        force: true,
        prompt: labPrompt.trim() || undefined,
      })
      const generated = Number(result?.generated) || 0
      const skipped = Number(result?.skipped) || 0
      const errCount = Array.isArray(result?.errors) ? result.errors.length : 0
      const firstErr = result?.errors?.[0]?.error
      const label = firstErr
        ? `Lab ${selectedTheme}/${labPlatform}: ${firstErr}`
        : `Lab ${selectedTheme}/${labPlatform}: generated ${generated}, skipped ${skipped}`
      setStatus(label)
      showToast(label, errCount && !generated ? 'error' : 'success')
      setLabLog((rows) =>
        [
          {
            id: `${Date.now()}`,
            theme: selectedTheme,
            platform: labPlatform,
            generated,
            skipped,
            error: firstErr || '',
            prompt: labPrompt.trim(),
          },
          ...rows,
        ].slice(0, 12),
      )
      setLabBust(Date.now())
      setLabExists(generated > 0 || skipped > 0)
      await loadCatalog()
    } catch (err) {
      const text = errorText(err) || 'Lab generate failed'
      setError(text)
      showToast(text, 'error')
      setLabLog((rows) =>
        [
          {
            id: `${Date.now()}`,
            theme: selectedTheme,
            platform: labPlatform,
            generated: 0,
            skipped: 0,
            error: text,
            prompt: labPrompt.trim(),
          },
          ...rows,
        ].slice(0, 12),
      )
    } finally {
      setBusy('')
    }
  }, [selectedTheme, labPlatform, labPrompt, loadCatalog])

  const selected = items.find((row) => row.theme === selectedTheme) || null
  const previewSrc =
    labUrl && (labExists || labBust)
      ? `${labUrl}${labUrl.includes('?') ? '&' : '?'}v=${labBust || '1'}`
      : ''

  return (
    <section
      className="od-system-marks"
      aria-label="Systems hub marks"
      data-testid="system-marks-panel"
    >
      <div className="od-stock-picker__head">
        <div>
          <h2 className="od-admin-panel-title">Systems hub marks</h2>
          <p className="od-admin-lede">
            Full-color AI art per library platform × theme (256 WebP). The lab below generates{' '}
            <strong>one</strong> pair so you can judge quality before a batch. Idempotent fills skip
            existing files unless you force. Needs <code>ENABLE_AI_ARTWORK</code> and{' '}
            <code>AI_ARTWORK_URL</code>.
          </p>
        </div>
        <Button type="button" disabled={loading || Boolean(busy)} onClick={loadCatalog}>
          Refresh
        </Button>
      </div>

      <PageStatus error={error} />
      {status ? (
        <PageStatus announcement="status" className="od-admin-lede">
          {status}
        </PageStatus>
      ) : null}

      {loading ? (
        <PageStatus
          loading
          loadingMessage="Loading system marks catalog…"
          className="od-stock-picker__empty"
        />
      ) : unavailable ? (
        <div className="od-stock-picker__empty" data-testid="system-marks-unavailable">
          <p className="od-stock-picker__empty-title">System marks API not available</p>
          <p>
            <code>GET {CATALOG_URL}</code> returned 404.
          </p>
        </div>
      ) : (
        <>
          <div className="od-system-marks__list" role="group" aria-label="Theme mark progress">
            {items.map((row) => {
              const selectedNow = row.theme === selectedTheme
              const pct = row.total ? Math.round((row.generated / row.total) * 100) : 0
              return (
                <button
                  key={row.theme}
                  type="button"
                  className={`od-system-marks__row${selectedNow ? ' is-selected' : ''}${
                    row.complete ? ' is-complete' : ''
                  }`}
                  aria-pressed={selectedNow}
                  aria-label={`${row.theme} ${row.generated} of ${row.total}`}
                  onClick={() => setSelectedTheme(row.theme)}
                >
                  <span className="od-system-marks__theme">{row.theme}</span>
                  <span className="od-system-marks__meta">
                    {row.generated}/{row.total}
                    {row.era ? ` · ${row.era}` : ''}
                  </span>
                  <span
                    className="od-system-marks__bar"
                    aria-hidden="true"
                    style={{ '--od-marks-pct': `${pct}%` } as CSSProperties}
                  />
                </button>
              )
            })}
          </div>

          <section
            className="od-system-marks-lab"
            data-testid="system-marks-lab"
            aria-label="System mark lab"
          >
            <h3 className="od-admin-panel-title">Lab — one mark</h3>
            <p className="od-admin-lede">
              Pick a theme (list above) and a platform, edit the prompt if you want, then generate.
              The attempt log stays on this page so a watching session can see what you tried.
            </p>
            <div className="od-system-marks-lab__grid">
              <label className="od-system-marks-lab__field">
                <span>Platform</span>
                <select
                  value={labPlatform}
                  onChange={(event) => setLabPlatform(event.target.value)}
                  disabled={Boolean(busy)}
                  aria-label="Lab platform"
                >
                  {(allPlatforms.length
                    ? allPlatforms
                    : [{ id: DEFAULT_LAB_PLATFORM, label: 'NES' }]
                  ).map((choice) => (
                    <option key={choice.id} value={choice.id}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="od-system-marks-lab__preview">
                {previewSrc ? (
                  <img src={previewSrc} alt={`${selectedTheme} ${labPlatform} mark`} />
                ) : (
                  <p className="od-admin-lede">No mark file yet for this pair.</p>
                )}
              </div>
              <label className="od-system-marks-lab__prompt">
                <span>Prompt</span>
                <textarea
                  value={labPrompt}
                  onChange={(event) => setLabPrompt(event.target.value)}
                  rows={6}
                  disabled={Boolean(busy)}
                  aria-label="Lab prompt"
                />
                <Button
                  type="button"
                  disabled={Boolean(busy) || labPrompt === labDefaultPrompt}
                  onClick={() => setLabPrompt(labDefaultPrompt)}
                >
                  Reset prompt
                </Button>
              </label>
            </div>
            <div className="od-system-marks__actions">
              <Button
                type="button"
                className="od-btn--accent"
                disabled={Boolean(busy) || !selectedTheme || !labPlatform}
                onClick={() => void runLabGenerate()}
              >
                {busy === 'lab'
                  ? `Generating ${selectedTheme}/${labPlatform}…`
                  : `Generate ${selectedTheme || 'theme'}/${labPlatform}`}
              </Button>
            </div>
            {labLog.length ? (
              <ol className="od-system-marks-lab__log" data-testid="system-marks-lab-log">
                {labLog.map((row) => (
                  <li key={row.id}>
                    <strong>
                      {row.theme}/{row.platform}
                    </strong>
                    {row.error
                      ? ` · error: ${row.error}`
                      : ` · generated ${row.generated}, skipped ${row.skipped}`}
                  </li>
                ))}
              </ol>
            ) : null}
          </section>

          <div className="od-system-marks__actions">
            <Button
              type="button"
              className="od-btn--accent"
              disabled={Boolean(busy) || !items.length}
              onClick={() => runGenerate({ force: false })}
            >
              {busy === 'generate' ? 'Generating…' : 'Generate missing (all themes)'}
            </Button>
            <Button
              type="button"
              disabled={Boolean(busy) || !selected}
              onClick={() =>
                runGenerate({ themes: selected ? [selected.theme] : [], force: false })
              }
            >
              {busy === 'generate' && selected
                ? `Generating ${selected.theme}…`
                : selected
                  ? `Fill gaps · ${selected.theme}`
                  : 'Fill gaps · select a theme'}
            </Button>
            <Button
              type="button"
              disabled={Boolean(busy) || !selected}
              onClick={() =>
                runGenerate({ themes: selected ? [selected.theme] : [], force: true, limit: 8 })
              }
            >
              {busy === 'force' ? 'Forcing…' : 'Force redo 8 · selected theme'}
            </Button>
          </div>
        </>
      )}
    </section>
  )
}
