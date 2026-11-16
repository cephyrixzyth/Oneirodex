import { useEffect, useState } from 'react'
import { Button } from '@oneirodex/ui'
import {
  deleteSavedState,
  fetchSavedStates,
  resumeHref,
  slotLabel,
  type GameSave,
} from '../api/saves'
import { formatRelativeTime } from '../utils/formatRelativeTime'
import { showToast } from '../utils/toast'
import { PageStatus } from './PageStatus'
import './SavedStatesPanel.css'

/**
 * Game details — this member's save states for the title. Each row resumes
 * straight into the play shell (which asks before loading, so a mis-click
 * costs nothing) or deletes. Saving happens in the room, not here.
 *
 * Mounts only when the title is browser-playable: a state you cannot open
 * is not worth a section.
 */
export function SavedStatesPanel({
  gameUuid,
  playHref,
}: {
  gameUuid: string
  playHref: string | null
}) {
  const [states, setStates] = useState<GameSave[]>([])
  const [enabled, setEnabled] = useState(true)
  const [canDelete, setCanDelete] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busySlot, setBusySlot] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    if (!gameUuid || !playHref) return undefined
    const controller = new AbortController()
    let active = true
    setLoading(true)
    setError(null)
    fetchSavedStates(gameUuid, { signal: controller.signal })
      .then((data) => {
        if (!active) return
        setStates(data.states)
        setEnabled(data.enabled)
        setCanDelete(data.canDelete)
        setLoading(false)
      })
      .catch((err: { name?: string }) => {
        if (!active || err?.name === 'AbortError') return
        setError(err)
        setStates([])
        setLoading(false)
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [gameUuid, playHref, reloadTick])

  if (!playHref) return null

  async function handleDelete(slot: string) {
    if (busySlot) return
    setBusySlot(slot)
    try {
      await deleteSavedState(gameUuid, slot)
      showToast(`Deleted ${slotLabel(slot)}`, 'success')
      setReloadTick((n) => n + 1)
    } catch (err) {
      showToast((err as Error)?.message || 'Could not delete that save.', 'error')
    } finally {
      setBusySlot(null)
    }
  }

  return (
    <section
      className="od-details-page__section od-saved-states"
      id="saved-states"
      aria-labelledby="saved-states-head"
    >
      <h2 id="saved-states-head">Saved states</h2>
      <PageStatus
        loading={loading}
        loadingMessage="Reading saved states…"
        error={error}
        onRetry={() => setReloadTick((n) => n + 1)}
        errorMessage="Could not read saved states."
        inline
      />
      {loading || error ? null : !enabled ? (
        <p className="od-saved-states__lede">
          Save sync is off on this server, so states stay in your browser.
        </p>
      ) : states.length === 0 ? (
        <p className="od-saved-states__lede">
          None yet. Your place is kept when you leave the room, and you can name saves from the
          Saves panel while playing.
        </p>
      ) : (
        <ul className="od-saved-states__list">
          {states.map((row) => {
            const label = slotLabel(row.slot_name)
            const href = resumeHref(playHref, row.slot_name)
            return (
              <li key={row.slot_name} className="od-saved-states__row" data-slot={row.slot_name}>
                <span className="od-saved-states__meta">
                  <strong className="od-saved-states__name">{label}</strong>
                  <span className="od-saved-states__when">
                    {formatRelativeTime(row.updated_at)}
                  </span>
                </span>
                <span className="od-saved-states__actions">
                  {href ? (
                    <a
                      className="od-btn od-btn--primary od-btn--sm"
                      href={href}
                      aria-label={`Resume ${label}`}
                    >
                      Resume
                    </a>
                  ) : null}
                  {canDelete ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={busySlot === row.slot_name}
                      onClick={() => handleDelete(row.slot_name)}
                      aria-label={`Delete ${label}`}
                    >
                      Delete
                    </Button>
                  ) : null}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
