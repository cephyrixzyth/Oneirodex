import { PREVIEW_VARIANTS, TITLE_SCALE_MAX, TITLE_SCALE_MIN } from './artStudioModel'
import { ART_STUDIO_SYSTEMS } from '../../components/platformSkins'
import { Button } from '@oneirodex/ui'

/** The form column: title / system / headline / scale, generate, apply, fallback, download. */
export function ArtStudioControls({
  composition,
  setComposition,
  applyFallback,
  applyToGame,
  busy,
  downloadZip,
  gameUuid,
  hasTitle,
  headline,
  packId,
  previewBusy,
  runGenerate,
  runPreview,
  setGameUuid,
  setHeadline,
  setSubtitle,
  setSystem,
  setTitle,
  setTitleScale,
  setVariantKey,
  subtitle,
  system,
  title,
  titleScale,
  variantKey,
}: {
  composition: string
  setComposition: (value: string) => void
  applyFallback: () => Promise<void>
  applyToGame: () => Promise<void>
  busy: string
  downloadZip: string | null
  gameUuid: string
  hasTitle: boolean
  headline: string
  packId: string
  previewBusy: boolean
  runGenerate: () => Promise<void>
  runPreview: () => Promise<void>
  setGameUuid: (value: string) => void
  setHeadline: (value: string) => void
  setSubtitle: (value: string) => void
  setSystem: (value: string) => void
  setTitle: (value: string) => void
  setTitleScale: (value: number) => void
  setVariantKey: (key: string) => void
  subtitle: string
  system: string
  title: string
  titleScale: number
  variantKey: string
}) {
  return (
    <div className="od-art-studio__controls">
      <label className="od-art-studio__title-field">
        <span className="od-art-studio__label">Composition</span>
        <select
          aria-label="Composition"
          value={composition}
          onChange={(event) => setComposition(event.target.value)}
        >
          {Object.entries({
            auto: 'From title',
            workbench: 'Archivist’s workbench',
            cartridge: 'Cartridge',
            marquee: 'Arcade marquee',
            crt: 'CRT screen',
            pixel: 'Pixel landscape',
            boxart: 'Box art',
            neon: 'Neon city',
          }).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label className="od-art-studio__title-field">
        <span className="od-art-studio__label">Title</span>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Chrono Trigger"
          maxLength={120}
          autoComplete="off"
          aria-describedby="od-art-title-hint"
        />
      </label>
      <p id="od-art-title-hint" className="od-art-studio__hint">
        Typing refreshes the live artistic preview. Generate writes the full size pack with the same
        renderer.
      </p>

      <label>
        <span className="od-art-studio__label">System / platform</span>
        <select
          value={system}
          onChange={(e) => setSystem(e.target.value)}
          aria-label="System for art template"
        >
          {ART_STUDIO_SYSTEMS.map((s) => (
            <option key={s.id || 'generic'} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>

      {/* FEAT-D4 text overrides (UID-011). The renderer has always
          accepted these; there was simply no way to reach them, so the
          only answer to "the text is too small" was to change a default
          for every cover at once. */}
      <fieldset className="od-art-studio__text">
        <legend className="od-art-studio__label">Cover text</legend>

        <label>
          <span className="od-art-studio__label">Headline</span>
          <input
            type="text"
            value={headline}
            onChange={(e) => setHeadline(e.target.value)}
            placeholder="Derived from the title"
            maxLength={120}
            autoComplete="off"
          />
        </label>

        <label>
          <span className="od-art-studio__label">Subtitle</span>
          <input
            type="text"
            value={subtitle}
            onChange={(e) => setSubtitle(e.target.value)}
            placeholder="Derived from the title"
            maxLength={120}
            autoComplete="off"
          />
        </label>

        <label>
          <span className="od-art-studio__label">Title size — {titleScale.toFixed(2)}×</span>
          <input
            type="range"
            min={TITLE_SCALE_MIN}
            max={TITLE_SCALE_MAX}
            step="0.05"
            value={titleScale}
            onChange={(e) => setTitleScale(Number(e.target.value))}
            aria-describedby="od-art-scale-hint"
          />
        </label>
        <p id="od-art-scale-hint" className="od-art-studio__hint">
          Clamped {TITLE_SCALE_MIN}×–{TITLE_SCALE_MAX}× by the renderer, which also refuses to
          overflow the canvas — the slider asks for a size, it does not override the fit. Leave the
          fields empty to keep the text derived from the title; an empty subtitle is kept as “no
          subtitle”.
        </p>
      </fieldset>

      <fieldset className="od-art-studio__variants">
        <legend className="od-art-studio__label">Preview size</legend>
        <div className="od-art-studio__variant-row" role="group" aria-label="Preview size">
          {PREVIEW_VARIANTS.map((v) => (
            <button
              key={v.key}
              type="button"
              className={`od-art-studio__variant${variantKey === v.key ? ' is-active' : ''}`}
              aria-pressed={variantKey === v.key}
              onClick={() => setVariantKey(v.key)}
            >
              {v.label}
              <span className="od-art-studio__variant-kind">{v.kind}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <div className="od-admin-actions-row od-art-studio__primary-actions">
        <Button type="button" disabled={!hasTitle || previewBusy} onClick={runPreview}>
          {previewBusy ? 'Previewing…' : 'Preview'}
        </Button>
        <Button
          type="button"
          variant="primary"
          disabled={!hasTitle || busy === 'generate'}
          onClick={runGenerate}
        >
          {busy === 'generate' ? 'Generating…' : 'Generate pack'}
        </Button>
      </div>

      <div className="od-art-studio__pack-actions">
        {downloadZip ? (
          <a className="od-btn" href={downloadZip}>
            Download ZIP
          </a>
        ) : (
          <Button disabled>Download ZIP</Button>
        )}
        <Button disabled={!packId || busy === 'apply-fallback'} onClick={applyFallback}>
          Set as fallback
        </Button>
      </div>

      <label className="od-art-studio__uuid-field">
        <span className="od-art-studio__label">Apply to game UUID</span>
        <input
          type="text"
          value={gameUuid}
          onChange={(e) => setGameUuid(e.target.value)}
          placeholder="game uuid"
          disabled={!packId}
        />
      </label>
      <Button
        type="button"
        variant="primary"
        disabled={!packId || !gameUuid.trim() || busy === 'apply-game'}
        onClick={applyToGame}
      >
        Apply cover to game
      </Button>

      {packId ? (
        <p className="od-art-studio__pack-meta">
          Pack <code className="od-mono">{packId}</code> · tiles, wides, squares, hero under{' '}
          <code>static/library/generated/</code>
        </p>
      ) : null}
    </div>
  )
}
