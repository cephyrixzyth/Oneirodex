import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { ImagesPage } from './ImagesPage'
import { StockPicker } from '../components/StockPicker'
import { SystemMarksPanel } from '../components/SystemMarksPanel'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { skinForPlatform, systemLabel } from '../components/platformSkins'
import { showToast } from '../utils/toast'
import {
  DEFAULT_TITLE_SCALE,
  FALLBACK_ASSETS,
  PREVIEW_DEBOUNCE_MS,
  PREVIEW_VARIANTS,
  type ArtStudioTab,
  type MissingCoverGame,
  type PreviewVariant,
} from './artStudio/artStudioModel'
import { ArtStudioBatch } from './artStudio/ArtStudioBatch'
import { ArtStudioControls } from './artStudio/ArtStudioControls'
import { ArtStudioFallbacks } from './artStudio/ArtStudioFallbacks'
import { ArtStudioStage } from './artStudio/ArtStudioStage'
import { ArtStudioTabs } from './artStudio/ArtStudioTabs'

function initialTab(): ArtStudioTab {
  if (typeof window === 'undefined') return 'studio'
  const hash = (window.location.hash || '').replace('#', '')
  if (hash === 'images' || hash === 'queue' || hash === 'picker') return 'images'
  if (hash === 'stock' || hash === 'backup') return 'stock'
  if (hash === 'marks' || hash === 'system-marks') return 'marks'
  return 'studio'
}

function tabHash(tab: ArtStudioTab) {
  if (tab === 'images') return '#images'
  if (tab === 'stock') return '#stock'
  if (tab === 'marks') return '#marks'
  return '#studio'
}

export function ArtStudioPage() {
  const [tab, setTab] = useState<ArtStudioTab>(initialTab)
  const [title, setTitle] = useState('')
  const [system, setSystem] = useState('')
  const [variantKey, setVariantKey] = useState('md')
  const [previews, setPreviews] = useState<Record<string, string>>({})
  const [packId, setPackId] = useState('')
  const [previewUrl, setPreviewUrl] = useState('')
  const [gameUuid, setGameUuid] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [missingCovers, setMissingCovers] = useState<MissingCoverGame[]>([])
  const [batchSelected, setBatchSelected] = useState<Set<string>>(() => new Set())
  const [batchLog, setBatchLog] = useState('')
  const [fallbackBust, setFallbackBust] = useState(() => Date.now())
  const [batchOpen, setBatchOpen] = useState(false)
  const [previewArtistic, setPreviewArtistic] = useState(true)
  /* FEAT-D4 overrides. The API has accepted `headline`, `subtitle` and
     `title_scale` since the artwork wave and nothing ever sent them, so
     "the text is still tiny and not legible, it should be editable in the art
     studio" (UID-011) was a frontend gap rather than missing capability.
     Empty headline means "derive it from the title", which is what the route
     already does with an absent key. */
  const [headline, setHeadline] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [titleScale, setTitleScale] = useState(DEFAULT_TITLE_SCALE)
  const previewReqId = useRef(0)

  const skin = useMemo(() => skinForPlatform(system), [system])
  const systemText = systemLabel(system)
  // Short platform id (SNES, PSX, …) matches Backend SYSTEM_TEMPLATES keys.
  const systemForApi = system || undefined
  const activeVariant = PREVIEW_VARIANTS.find((v) => v.key === variantKey) || PREVIEW_VARIANTS[1]
  const heroSrc =
    previews[activeVariant.key] || (activeVariant.key === 'md' ? previewUrl : '') || ''
  const hasTitle = Boolean(title.trim())
  const previewBusy = busy === 'preview' || busy === 'preview-system' || busy === 'preview-live'

  const selectTab = (next: ArtStudioTab) => {
    setTab(next)
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', tabHash(next))
    }
  }

  const onStockApplied = useCallback(() => {
    setFallbackBust(Date.now())
    setMessage('Library default covers updated from stock pack. Hard-refresh member browsers.')
  }, [])

  useEffect(() => {
    const onHash = () => setTab(initialTab())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const fetchPreviews = useCallback(
    async (
      sizes: PreviewVariant[],
      {
        soft = false,
        busyKey = 'preview',
        titleOverride,
      }: { soft?: boolean; busyKey?: string; titleOverride?: string } = {},
    ) => {
      const trimmed = (titleOverride ?? title).trim()
      if (!trimmed) return
      const reqId = ++previewReqId.current
      setBusy(busyKey)
      if (!soft) {
        setError('')
        setMessage('')
      }
      try {
        const next: Record<string, string> = {}
        for (const size of sizes) {
          const data = await postJson('/admin/api/art-studio/preview', {
            title: trimmed,
            system: systemForApi,
            width: size.width,
            height: size.height,
            // Absent keys keep the derived text, so only send what was set.
            // An explicit empty subtitle means "no subtitle" to the renderer,
            // which is a different instruction from leaving it out.
            ...(headline.trim() ? { headline: headline.trim() } : {}),
            ...(subtitle !== '' ? { subtitle } : {}),
            title_scale: titleScale,
          })
          if (reqId !== previewReqId.current) return
          next[size.key] = data.preview
          if (typeof data.artistic === 'boolean') setPreviewArtistic(data.artistic)
        }
        if (reqId !== previewReqId.current) return
        setPreviews((prev) => ({ ...prev, ...next }))
        setPreviewUrl('')
        if (!soft) setMessage('Artistic preview refreshed.')
      } catch (err) {
        if (reqId !== previewReqId.current) return
        const text = errorText(err) || 'Preview failed'
        if (soft) {
          showToast(text, 'warn')
        } else {
          setError(text)
          showToast(text, 'error')
        }
      } finally {
        if (reqId === previewReqId.current) {
          setBusy((b) => (b === busyKey ? '' : b))
        }
      }
    },
    [title, systemForApi, headline, subtitle, titleScale],
  )

  const runPreview = useCallback(async () => {
    const sizes = PREVIEW_VARIANTS.filter((v) => v.kind === 'tile' || v.key === variantKey)
    await fetchPreviews(sizes, { soft: false, busyKey: 'preview' })
  }, [fetchPreviews, variantKey])

  // Live preview: title typing feels like painting a cover (debounced).
  // System changes re-paint the active variant via the same debounce path.
  useEffect(() => {
    const trimmed = title.trim()
    if (!trimmed) {
      previewReqId.current += 1
      setPreviews({})
      setBusy((b) => (b.startsWith('preview') ? '' : b))
      return undefined
    }
    const timer = window.setTimeout(() => {
      fetchPreviews([activeVariant], {
        soft: true,
        busyKey: 'preview-live',
        titleOverride: trimmed,
      })
    }, PREVIEW_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [title, variantKey, system, systemForApi, activeVariant, fetchPreviews])

  const runGenerate = useCallback(async () => {
    setBusy('generate')
    setError('')
    setMessage('')
    try {
      const data = await postJson('/admin/api/art-studio/generate', {
        title: title.trim(),
        system: systemForApi,
        format: 'webp',
        // Must match the preview payload exactly, or Generate writes something
        // other than what was on screen when it was clicked.
        ...(headline.trim() ? { headline: headline.trim() } : {}),
        ...(subtitle !== '' ? { subtitle } : {}),
        title_scale: titleScale,
      })
      setPackId(data.pack_id)
      setPreviewUrl(data.preview_url)
      setPreviews({})
      setMessage(`Generated pack ${data.pack_id} (${data.files?.length || 0} sizes).`)
      showToast('Art pack ready', 'success')
    } catch (err) {
      const text = errorText(err)
      setError(text)
      showToast(text || 'Generate failed', 'error')
    } finally {
      setBusy('')
    }
  }, [title, systemForApi, headline, subtitle, titleScale])

  const applyToGame = useCallback(async () => {
    if (!packId || !gameUuid.trim()) {
      setError('Generate a pack and enter a game UUID first.')
      return
    }
    setBusy('apply-game')
    setError('')
    try {
      const data = await postJson('/admin/api/art-studio/apply', {
        pack_id: packId,
        mode: 'game',
        game_uuid: gameUuid.trim(),
      })
      setMessage(`Cover applied to ${data.game_uuid}.`)
      showToast('Cover applied to game', 'success')
    } catch (err) {
      const text = errorText(err)
      setError(text)
      showToast(text || 'Apply failed', 'error')
    } finally {
      setBusy('')
    }
  }, [packId, gameUuid])

  const applyFallback = useCallback(async () => {
    if (!packId) {
      setError('Generate a pack first.')
      return
    }
    setBusy('apply-fallback')
    setError('')
    try {
      await postJson('/admin/api/art-studio/apply', {
        pack_id: packId,
        mode: 'fallback',
      })
      setFallbackBust(Date.now())
      setMessage('Library default covers updated. Hard-refresh member browsers.')
      showToast('Fallback pack installed', 'success')
    } catch (err) {
      const text = errorText(err)
      setError(text)
      showToast(text || 'Fallback apply failed', 'error')
    } finally {
      setBusy('')
    }
  }, [packId])

  const regenerateDefaults = useCallback(async () => {
    const seed = title.trim() || 'Oneirodex'
    setBusy('regen-fallback')
    setError('')
    try {
      const data = await postJson('/admin/api/art-studio/generate', {
        title: seed,
        system: systemForApi,
        format: 'webp',
      })
      setPackId(data.pack_id)
      setPreviewUrl(data.preview_url)
      await postJson('/admin/api/art-studio/apply', {
        pack_id: data.pack_id,
        mode: 'fallback',
      })
      setFallbackBust(Date.now())
      setMessage(
        `Library defaults regenerated from “${seed}” (pack ${data.pack_id}). Hard-refresh browsers.`,
      )
      showToast('Library defaults refreshed', 'success')
    } catch (err) {
      const text = errorText(err)
      setError(text)
      showToast(text || 'Could not regenerate defaults', 'error')
    } finally {
      setBusy('')
    }
  }, [title, systemForApi])

  const loadMissing = useCallback(async () => {
    setBusy('missing')
    setError('')
    try {
      const data = await getJson('/api/health/library?limit=200')
      const worst: MissingCoverGame[] = Array.isArray(data.worst) ? data.worst : []
      const rows = worst.filter((g) => (g.issues || []).some((i) => i.code === 'missing_cover'))
      setMissingCovers(rows)
      setBatchSelected(new Set(rows.map((r) => r.uuid)))
      setBatchOpen(true)
      setMessage(
        rows.length
          ? `${rows.length} no-cover title(s) in health sample.`
          : 'No missing-cover titles in the health sample.',
      )
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy('')
    }
  }, [])

  const toggleBatch = (uuid: string) => {
    setBatchSelected((prev) => {
      const next = new Set(prev)
      if (next.has(uuid)) next.delete(uuid)
      else next.add(uuid)
      return next
    })
  }

  const batchApplyPlaceholders = useCallback(async () => {
    const targets = missingCovers.filter((g) => batchSelected.has(g.uuid))
    if (!targets.length) {
      setError('Select at least one no-cover title.')
      return
    }
    setBusy('batch')
    setError('')
    setBatchLog('')
    const lines = []
    const uuids = targets.map((t) => t.uuid)
    try {
      try {
        const batch = await postJson('/admin/api/art-studio/batch-generate', {
          game_uuids: uuids,
          missing_cover: true,
          system: systemForApi,
        })
        const applied = batch.applied ?? (Array.isArray(batch.results) ? batch.results.length : 0)
        const failed = batch.failed ?? (Array.isArray(batch.errors) ? batch.errors.length : 0)
        setMessage(`Batch generate finished — applied ${applied}, failed ${failed}.`)
        const failLines = (batch.errors || []).map(
          (r: any) => `✗ ${r.name || r.game_uuid}: ${r.error || 'failed'}`,
        )
        setBatchLog(['Used POST /admin/api/art-studio/batch-generate.', ...failLines].join('\n'))
        if (applied > 0) return
        lines.push(
          'Batch-generate returned zero applies — trying covers/batch/apply generate_only…',
        )
      } catch {
        lines.push('batch-generate unavailable — trying covers/batch/apply policy=generate_only…')
      }

      try {
        const batch = await postJson('/admin/api/covers/batch/apply', {
          policy: 'generate_only',
          game_uuids: uuids,
          missing_cover: true,
        })
        const applied = batch.applied ?? 0
        const failed = batch.failed ?? 0
        setMessage(`Placeholder apply finished — applied ${applied}, failed ${failed}.`)
        const failLines = (batch.results || [])
          .filter((r: any) => r.status === 'failed')
          .map((r: any) => `✗ ${r.name || r.game_uuid}: ${r.error || 'failed'}`)
        setBatchLog(
          [
            ...lines,
            'Used POST /admin/api/covers/batch/apply policy=generate_only.',
            ...failLines,
          ].join('\n'),
        )
        if (applied > 0) return
        lines.push('Batch apply returned zero applies — generating per selected title…')
      } catch {
        lines.push('Batch apply unavailable — generating per title via art-studio APIs…')
      }

      let ok = 0
      for (const game of targets) {
        try {
          const pack = await postJson('/admin/api/art-studio/generate', {
            title: game.name,
            system: systemForApi,
            format: 'webp',
          })
          await postJson('/admin/api/art-studio/apply', {
            pack_id: pack.pack_id,
            mode: 'game',
            game_uuid: game.uuid,
          })
          ok += 1
          lines.push(`✓ ${game.name}`)
        } catch (err) {
          lines.push(`✗ ${game.name}: ${errorText(err)}`)
        }
      }
      setMessage(`Applied placeholders to ${ok}/${targets.length} title(s).`)
      setBatchLog(lines.join('\n'))
    } finally {
      setBusy('')
    }
  }, [missingCovers, batchSelected, systemForApi])

  const downloadZip = packId ? `/admin/api/art-studio/download/${encodeURIComponent(packId)}` : null

  const previewChromeStyle = skin?.accent
    ? {
        borderColor: skin.accent,
        boxShadow: `0 0 0 1px ${skin.accent}66, 0 18px 48px rgba(0,0,0,0.45)`,
      }
    : undefined

  return (
    <div className="od-admin-page">
      <header className="od-art-studio-head">
        <div>
          <p className="od-art-studio-kicker">Admin · Cover atelier</p>
          <h1>Art studio</h1>
          <p className="od-admin-lede od-art-studio-lede">
            Type a title — watch an <strong>artistic</strong> cover form (motifs, bezels, initials).
            Local Pillow renderer, aurora tokens, no cloud AI. Use <strong>Pick &amp; queue</strong>{' '}
            for SteamGridDB / IGDB art.
          </p>
        </div>
        {skin ? (
          <span
            className={`od-art-studio-skin od-art-studio-skin--${skin.family}`}
            style={{ '--od-art-skin': skin.accent } as CSSProperties}
          >
            {skin.label}
            {systemText ? ` · ${systemText}` : ''}
          </span>
        ) : null}
      </header>

      <ArtStudioTabs selectTab={selectTab} tab={tab} />

      {tab === 'images' ? <ImagesPage embedded /> : null}

      {tab === 'marks' ? (
        <div className="od-art-stock-tab">
          <SystemMarksPanel />
        </div>
      ) : null}

      {tab === 'stock' ? (
        <div className="od-art-stock-tab">
          <StockPicker onApplied={onStockApplied} showLibraryUuid />
          <ArtStudioFallbacks fallbackBust={fallbackBust} />
        </div>
      ) : null}

      {tab === 'studio' ? (
        <>
          <PageStatus error={error} />
          {message ? (
            <p className="od-admin-lede" role="status">
              {message}
            </p>
          ) : null}

          <section className="od-art-studio od-art-studio--workspace" aria-label="Cover studio">
            <ArtStudioStage
              activeVariant={activeVariant}
              heroSrc={heroSrc}
              previewArtistic={previewArtistic}
              previewBusy={previewBusy}
              previewChromeStyle={previewChromeStyle}
              previews={previews}
              setVariantKey={setVariantKey}
              skin={skin}
              systemText={systemText}
              title={title}
            />

            <ArtStudioControls
              applyFallback={applyFallback}
              applyToGame={applyToGame}
              busy={busy}
              downloadZip={downloadZip}
              gameUuid={gameUuid}
              hasTitle={hasTitle}
              headline={headline}
              packId={packId}
              previewBusy={previewBusy}
              runGenerate={runGenerate}
              runPreview={runPreview}
              setGameUuid={setGameUuid}
              setHeadline={setHeadline}
              setSubtitle={setSubtitle}
              setSystem={setSystem}
              setTitle={setTitle}
              setTitleScale={setTitleScale}
              setVariantKey={setVariantKey}
              subtitle={subtitle}
              system={system}
              title={title}
              titleScale={titleScale}
              variantKey={variantKey}
            />
          </section>

          <section
            className="od-admin-panel od-art-studio-fallbacks"
            aria-label="Library default covers"
          >
            <div className="od-art-studio-fallbacks__head">
              <div>
                <h2 className="od-admin-panel-title">Library default covers</h2>
                <p className="od-admin-lede">
                  Site-wide fallbacks when a title has no downloaded art. Generate a pack above,
                  then set as fallback — or open{' '}
                  <button
                    type="button"
                    className="od-art-inline-link"
                    onClick={() => selectTab('stock')}
                  >
                    Backup &amp; stock
                  </button>{' '}
                  for platform packs and stock motifs.
                </p>
              </div>
              <Button
                type="button"
                variant="primary"
                disabled={busy === 'regen-fallback'}
                onClick={regenerateDefaults}
              >
                {busy === 'regen-fallback' ? 'Regenerating…' : 'Regenerate defaults'}
              </Button>
            </div>
            <div className="od-art-studio-fallbacks__grid">
              {FALLBACK_ASSETS.map((asset) => (
                <figure key={asset.key} className="od-art-studio-fallbacks__card">
                  <img
                    src={`${asset.path}?v=${fallbackBust}`}
                    alt={asset.label}
                    onError={(e) => {
                      e.currentTarget.style.visibility = 'hidden'
                    }}
                  />
                  <figcaption>
                    <strong>{asset.label}</strong>
                    <span>{asset.hint}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>

          <ArtStudioBatch
            batchApplyPlaceholders={batchApplyPlaceholders}
            batchLog={batchLog}
            batchOpen={batchOpen}
            batchSelected={batchSelected}
            busy={busy}
            loadMissing={loadMissing}
            missingCovers={missingCovers}
            setBatchOpen={setBatchOpen}
            toggleBatch={toggleBatch}
          />
        </>
      ) : null}
    </div>
  )
}
