import { useEffect, useRef, useState } from 'react'
import { Button } from '@oneirodex/ui'

/**
 * A clamped prose block with a Show more / Show less toggle. Used for both the
 * Summary and the longer About (storyline) text, so neither can push the page
 * down by more than a few lines until the reader asks for it.
 */
export function DetailsSummarySection({
  summary,
  heading = 'Summary',
  variant = 'summary',
}: {
  summary: string
  heading?: string
  variant?: 'summary' | 'about'
}) {
  const [summaryExpanded, setSummaryExpanded] = useState(false)
  // Whether the summary is actually clipped by the line clamp. Measured rather
  // than guessed from character count: a character threshold disagrees with the
  // clamp at both ends — short-but-wrapped text got no toggle, and long text that
  // happened to fit still offered one.
  const summaryRef = useRef<HTMLParagraphElement | null>(null)
  const [summaryOverflows, setSummaryOverflows] = useState(false)

  // Re-measure on mount, on summary change, and on resize — a summary that fits
  // on a wide screen can clip on a narrow one.
  useEffect(() => {
    const node = summaryRef.current
    if (!node) {
      return undefined
    }
    if (summaryExpanded) {
      // Expanded, nothing is clipped; keep the toggle so "Show less" survives.
      return undefined
    }
    const measure = () => {
      setSummaryOverflows(node.scrollHeight > node.clientHeight + 1)
    }
    measure()
    if (typeof ResizeObserver === 'undefined') {
      return undefined
    }
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [summaryExpanded, summary])

  return (
    <section className={`od-details-page__section od-details-page__section--${variant}`}>
      <h2>{heading}</h2>
      <p
        ref={summaryRef}
        className={`od-details-page__summary${variant === 'about' ? ' od-details-page__about' : ''}${summaryExpanded ? ' is-expanded' : ''}`}
      >
        {summary}
      </p>
      {summaryOverflows ? (
        <Button
          type="button"
          className="od-details-page__summary-toggle"
          onClick={() => setSummaryExpanded((open) => !open)}
        >
          {summaryExpanded ? 'Show less' : 'Show more'}
        </Button>
      ) : null}
    </section>
  )
}
