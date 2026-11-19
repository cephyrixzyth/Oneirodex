import type { CSSProperties } from 'react'
import { PREVIEW_VARIANTS, type PreviewVariant } from './artStudioModel'
import type { skinForPlatform } from '../../components/platformSkins'

/** The preview stage: variant picker, hero preview, per-variant thumbnails. */
export function ArtStudioStage({
  activeVariant,
  heroSrc,
  previewArtistic,
  previewBusy,
  previewChromeStyle,
  previews,
  setVariantKey,
  skin,
  systemText,
  title,
}: {
  activeVariant: PreviewVariant
  heroSrc: string
  previewArtistic: boolean
  previewBusy: boolean
  previewChromeStyle: CSSProperties | undefined
  previews: Record<string, string>
  setVariantKey: (key: string) => void
  skin: ReturnType<typeof skinForPlatform>
  systemText: string
  title: string
}) {
  return (
    <div
      className={`od-art-studio__stage${skin ? ` od-art-studio__stage--${skin.family}` : ''}`}
      style={previewChromeStyle}
      aria-busy={previewBusy}
    >
      {heroSrc ? (
        <figure className="od-art-studio__hero">
          {previewArtistic ? <span className="od-art-studio__mode-badge">Artistic</span> : null}
          <img
            src={heroSrc}
            alt={`${title || 'Cover'} preview ${activeVariant.label}`}
            width={activeVariant.width}
            height={activeVariant.height}
          />
          <figcaption>
            {activeVariant.label}
            {systemText ? ` · ${systemText}` : ''}
            {previewArtistic ? ' · artistic' : ''}
            {previewBusy ? ' · painting…' : ''}
          </figcaption>
        </figure>
      ) : (
        <div className="od-art-studio__empty" data-testid="art-studio-empty">
          <div className="od-art-studio__empty-glow" aria-hidden="true" />
          <p className="od-art-studio__empty-title">
            {previewBusy ? 'Painting cover…' : 'Name a title to paint a cover'}
          </p>
          <p className="od-art-studio__empty-hint">
            Title-first atelier — Backend artistic compositions by default (motifs · bezels ·
            watermark), not gray placeholders.
          </p>
        </div>
      )}

      <div className="od-art-studio__thumbs" role="group" aria-label="Other tile sizes">
        {PREVIEW_VARIANTS.filter((v) => v.key !== activeVariant.key && v.kind === 'tile').map(
          (size) => {
            const src = previews[size.key]
            return (
              <button
                key={size.key}
                type="button"
                className="od-art-studio__thumb"
                onClick={() => setVariantKey(size.key)}
                title={`Show ${size.label}`}
              >
                {src ? (
                  <img src={src} alt="" width={size.width} height={size.height} />
                ) : (
                  <span>{size.label}</span>
                )}
              </button>
            )
          },
        )}
      </div>
    </div>
  )
}
