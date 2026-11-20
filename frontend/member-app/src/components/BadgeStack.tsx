import { useMemo, useState } from 'react'
import { capBadges, collectBadgeSignals, layoutBadgesByCorner } from '../utils/badgeSignals'
import {
  clearDismissedBadges,
  dismissBadge,
  filterDismissedBadges,
  listDismissedKinds,
} from '../utils/badgeDismiss'

/**
 * Cap flexible badges but always keep VR / MISSING visible (pinned).
 */
const PINNED_BADGE_KINDS = new Set(['VR', 'MISSING'])

function capWithPinnedStatus(badges: any, maxVisible = 2) {
  const pinned = badges.filter((badge: any) => PINNED_BADGE_KINDS.has(badge.kind))
  const rest = badges.filter((badge: any) => !PINNED_BADGE_KINDS.has(badge.kind))
  const { visible: restVisible, overflow } = capBadges(rest, maxVisible)
  if (pinned.length === 0) {
    return { visible: restVisible, overflow }
  }
  return { visible: [...restVisible, ...pinned], overflow }
}

/**
 * Corner-only badge overlays for title cards.
 * Occupied corners only — no empty reserved slots.
 * VR / MISSING pin top-left and are never dismissable.
 */
export function BadgeStack({
  game,
  preferredCorner = 'top-left',
  collidesWithTitle = false,
  hasPlatformChip = false,
  maxVisible = 2,
  now,
  dismissible = true,
}: LooseProps) {
  void preferredCorner
  const [dismissTick, setDismissTick] = useState(0)
  const badges = useMemo(() => {
    void dismissTick
    return filterDismissedBadges(game?.uuid, collectBadgeSignals(game, { now }))
  }, [game, now, dismissTick])

  const { visible, overflow: cappedOverflow } = capWithPinnedStatus(badges, maxVisible)
  const layout = layoutBadgesByCorner(visible, {
    hasPlatformChip: Boolean(hasPlatformChip),
    collidesWithTitle,
    maxPerCorner: 2,
  })

  const layoutOverflow = layout.corners.reduce((sum, slot) => sum + slot.overflow, 0)
  const totalOverflow = cappedOverflow + layoutOverflow
  let corners = layout.corners.map((slot) => ({ ...slot, overflow: 0 }))
  if (totalOverflow > 0) {
    if (corners.length === 0) {
      corners = [{ corner: 'top-left', badges: [], overflow: totalOverflow }]
    } else {
      corners = corners.map((slot, index) =>
        index === 0 ? { ...slot, overflow: totalOverflow } : slot,
      )
    }
  }

  const hasMain = corners.some((c) => c.badges.length > 0 || c.overflow > 0)
  const dismissed = listDismissedKinds(game?.uuid).filter((kind) => !PINNED_BADGE_KINDS.has(kind))
  if (!hasMain && !(dismissible && dismissed.length > 0)) {
    return null
  }

  const { hasVr, hasMissing } = layout

  function handleDismiss(kind: any, event: any) {
    if (PINNED_BADGE_KINDS.has(kind)) {
      return
    }
    event.preventDefault()
    event.stopPropagation()
    dismissBadge(game?.uuid, kind)
    setDismissTick((n) => n + 1)
  }

  function handleRestore(event: any) {
    event.preventDefault()
    event.stopPropagation()
    clearDismissedBadges(game?.uuid)
    setDismissTick((n) => n + 1)
  }

  if (!hasMain && dismissible && dismissed.length > 0) {
    return (
      <div className="od-badge-layers" role="group" aria-label="Game badges">
        <div
          className="od-badge-stack od-badge-stack--top-left od-badge-stack--interactive"
          data-corner="top-left"
        >
          <button
            type="button"
            className="od-badge od-badge--restore"
            title="Restore hidden badges"
            aria-label="Restore badges"
            onClick={handleRestore}
          >
            Badges
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="od-badge-layers" role="group" aria-label="Game badges">
      {corners.map((slot) => (
        <div
          key={slot.corner}
          className={`od-badge-stack od-badge-stack--${slot.corner}${
            hasVr && slot.corner === 'top-left' ? ' od-badge-stack--vr' : ''
          }${hasMissing && slot.corner === 'top-left' ? ' od-badge-stack--missing' : ''}${
            dismissible ? ' od-badge-stack--interactive' : ''
          }`}
          data-corner={slot.corner}
          data-vr-in-stack={hasVr && slot.corner === 'top-left' ? 'top-left' : undefined}
          data-missing-in-stack={hasMissing && slot.corner === 'top-left' ? 'top-left' : undefined}
        >
          {slot.badges.map((badge: any) => (
            <span
              key={badge.kind}
              className={`od-badge od-badge--${badge.tone}`}
              data-badge={badge.kind}
              title={badge.title}
            >
              <span className="od-badge__label">{badge.label}</span>
              {dismissible && !PINNED_BADGE_KINDS.has(badge.kind) ? (
                <button
                  type="button"
                  className="od-badge__dismiss"
                  aria-label={`Hide ${badge.label} badge`}
                  title="Hide this badge"
                  onClick={(event) => handleDismiss(badge.kind, event)}
                >
                  ×
                </button>
              ) : null}
            </span>
          ))}
          {slot.overflow > 0 && (
            <span className="od-badge od-badge--overflow" title={`${slot.overflow} more badges`}>
              +{slot.overflow}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
