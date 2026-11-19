import { useEffect, useState } from 'react'
import './LoadingOverlay.css'
import { LoadingMotif } from './LoadingMotif'
import { useLoadingMotifId } from './loadingMotifApi'

/**
 * Non-displacing busy indicator (UX-B6).
 *
 * Inline spinners next to buttons reflow the page every time the server does
 * something, so controls move under the pointer mid-click. This floats above
 * the layout instead and takes up no space in flow.
 *
 * `delayMs` avoids the other failure mode: a flash of overlay on requests that
 * finish in 80ms is more distracting than no indicator at all.
 */
export function LoadingOverlay({
  active = false,
  label = 'Working…',
  delayMs = 250,
  blocking = false,
}: LooseProps) {
  const motifId = useLoadingMotifId()
  // delayMs <= 0 means "show now": an initial page load has nothing on screen
  // yet, so waiting even a tick leaves a blank panel with no explanation. The
  // delay is for action spinners, where a flash is the worse outcome.
  const [visible, setVisible] = useState(() => active && delayMs <= 0)

  useEffect(() => {
    if (!active) {
      setVisible(false)
      return undefined
    }
    if (delayMs <= 0) {
      setVisible(true)
      return undefined
    }
    const timer = setTimeout(() => setVisible(true), delayMs)
    return () => clearTimeout(timer)
  }, [active, delayMs])

  if (!active || !visible) {
    return null
  }

  return (
    <div
      className={`od-loading-overlay${blocking ? ' od-loading-overlay--blocking' : ''}`}
      role="status"
      aria-live="polite"
    >
      <div className="od-loading-overlay__card">
        <LoadingMotif motifId={motifId} />
        <span className="od-loading-overlay__label">{label}</span>
      </div>
    </div>
  )
}
