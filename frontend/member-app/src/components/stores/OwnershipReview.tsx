import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@oneirodex/ui'
import {
  fetchOwnershipCandidates,
  fetchOwnershipTitles,
  reviewOwnershipMatch,
  undoOwnershipMatch,
  type OwnershipCandidate as Candidate,
  type OwnershipTitle as Title,
} from '../../api/ownership'
import { apiErrorInfo } from './apiErrorInfo'
import { useFocusRecovery } from '../../hooks/useFocusRecovery'
import { useListFocusNavigation } from '../../hooks/useListFocusNavigation'
import { PageStatus } from '../PageStatus'
import './OwnershipReview.css'

export type ReviewFilter = 'needs_review' | 'matched' | 'all'

const STORE_NAMES: Record<string, string> = {
  steam: 'Steam',
  gog: 'GOG',
  epic: 'Epic Games',
  amazon: 'Amazon Games',
  xbox: 'Xbox',
  psn: 'PlayStation',
  meta_quest: 'Meta Quest',
  playnite: 'Playnite',
}
const NONE = '__none__'

function statusOf(title: Title) {
  if (title.matched_game_uuid)
    return { label: title.match_reviewed ? 'Matched · confirmed' : 'Matched', tone: 'good' }
  if (title.match_hidden) return { label: 'Matched · not in your libraries', tone: 'muted' }
  if (title.match_reviewed) return { label: 'No match · confirmed', tone: 'muted' }
  return { label: 'Needs review', tone: 'warn' }
}

/**
 * Review how each recorded store title maps to a library game (LIB-02 over
 * the LIB-03 review API). A name match is only ever a suggestion: nothing is
 * linked until the member picks a candidate and confirms, and the latest
 * decision can be undone. Game rows are never merged or deleted.
 */
export function OwnershipReview({ initialFilter = 'needs_review' as ReviewFilter }) {
  const [filter, setFilter] = useState<ReviewFilter>(initialFilter)
  const [titles, setTitles] = useState<Title[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  // One page request at a time. Changing the filter aborts a pending
  // "Show more", so rows from the old filter never land in the new list.
  const inflight = useRef<AbortController | null>(null)
  useListFocusNavigation(rootRef)

  const load = useCallback(
    async (after: number, replace: boolean) => {
      inflight.current?.abort()
      const controller = new AbortController()
      inflight.current = controller
      setLoading(true)
      try {
        const page = await fetchOwnershipTitles(after, {
          signal: controller.signal,
          status: filter,
        })
        if (controller.signal.aborted) return
        setTitles((current) => (replace ? page.titles : [...current, ...page.titles]))
        setNext(page.next_after_id ?? null)
        setError(null)
      } catch (err) {
        if (!controller.signal.aborted && !apiErrorInfo(err).aborted) setError(err)
      } finally {
        if (inflight.current === controller) {
          inflight.current = null
          setLoading(false)
        }
      }
    },
    [filter],
  )

  useEffect(() => {
    load(0, true)
    return () => inflight.current?.abort()
  }, [load])

  const replaceTitle = (updated: Title) =>
    setTitles((current) => current.map((t) => (t.id === updated.id ? { ...t, ...updated } : t)))

  const filters: [ReviewFilter, string][] = [
    ['needs_review', 'Needs review'],
    ['matched', 'Matched'],
    ['all', 'All'],
  ]

  return (
    <div ref={rootRef} className="od-review">
      <div className="od-cbtn-group" role="group" aria-label="Show titles">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            data-od-nav
            className={`od-cbtn${filter === value ? ' is-on' : ''}`}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="od-review__lede">
        Titles recorded from your stores and imports. A matching name is only a suggestion: check
        the edition, remaster, DLC and platform before confirming. Nothing is merged or deleted.
      </p>
      {error ? (
        <PageStatus
          error={error}
          errorMessage="Unable to load your recorded titles."
          onRetry={() => load(0, true)}
        />
      ) : null}
      {!error && !loading && titles.length === 0 ? (
        <p className="od-review__empty">
          {filter === 'needs_review' ? 'Nothing is waiting for review.' : 'No titles to show.'}
        </p>
      ) : null}
      <ul className="od-review__list">
        {titles.map((title) => (
          <ReviewRow key={title.id} title={title} onChange={replaceTitle} />
        ))}
      </ul>
      {loading && titles.length === 0 ? (
        <PageStatus loading loadingMessage="Loading recorded titles" />
      ) : null}
      {next !== null ? (
        <Button data-od-nav size="sm" disabled={loading} onClick={() => load(next, false)}>
          {loading ? 'Loading…' : 'Show more'}
        </Button>
      ) : null}
    </div>
  )
}

function ReviewRow({ title, onChange }: { title: Title; onChange: (title: Title) => void }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [choice, setChoice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(false)
  const [message, setMessage] = useState<{ tone: 'good' | 'bad'; text: string } | null>(null)
  // The member's own latest decision, and what the title was linked to before
  // it, so Undo can say what it restored.
  const [undoable, setUndoable] = useState<{
    revision: number
    before: Title['matched_game']
  } | null>(null)
  const toggleRef = useRef<HTMLButtonElement | null>(null)
  const reloadRef = useRef<HTMLButtonElement | null>(null)
  const rowRef = useRef<HTMLLIElement | null>(null)
  const status = statusOf(title)

  // Confirm, Undo and Reload title each remove the button that was focused.
  // Focus that fell to the page returns to this row: to Reload title when a
  // conflict needs it, otherwise to the review toggle.
  useFocusRecovery(rowRef, () => {
    const reload = reloadRef.current
    if (reload && !reload.disabled) return reload
    const toggle = toggleRef.current
    return toggle && !toggle.disabled
      ? toggle
      : rowRef.current?.querySelector<HTMLElement>('[data-od-nav]:not([disabled])')
  })
  const store = STORE_NAMES[title.store] || title.store

  async function openReview() {
    setOpen((v) => !v)
    if (candidates === null) {
      try {
        const data = await fetchOwnershipCandidates(title.id)
        setCandidates(data.candidates || [])
        setTruncated(Boolean(data.truncated))
      } catch (err) {
        setMessage({ tone: 'bad', text: apiErrorInfo(err, 'Unable to load suggestions.').message })
        setCandidates([])
      }
    }
  }

  /** Re-read this one title after a conflict; the member's pick is kept. */
  async function reload() {
    setBusy(true)
    try {
      const page = await fetchOwnershipTitles(Math.max(title.id - 1, 0))
      const fresh = page.titles?.find((t) => t.id === title.id)
      if (fresh) onChange(fresh)
      // Only the member's own latest decision can be undone; after someone
      // else's change there is nothing of theirs left to undo.
      if (!fresh || fresh.match_revision !== undoable?.revision) setUndoable(null)
      setConflict(false)
      setMessage({
        tone: 'good',
        text: 'Reloaded. Your choice is still selected — confirm it if it is still right.',
      })
    } catch (err) {
      setMessage({ tone: 'bad', text: apiErrorInfo(err, 'Unable to reload this title.').message })
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (choice === null) return
    setBusy(true)
    setMessage(null)
    try {
      const gameUuid = choice === NONE ? null : choice
      const result = await reviewOwnershipMatch(title.id, gameUuid, title.match_revision)
      const picked = candidates?.find((c) => c.game_uuid === gameUuid)
      onChange({
        ...title,
        matched_game_uuid: result.matched_game_uuid,
        match_available: Boolean(result.matched_game_uuid),
        match_reviewed: result.match_reviewed,
        match_revision: result.match_revision,
        matched_game: picked ? { name: picked.name, platform: picked.platform } : null,
        // A decision links a game this member can see, or nothing.
        match_hidden: false,
      })
      // A match to a game the member cannot see cannot be put back by them
      // (the server refuses to link it), so no Undo is offered for replacing one.
      setUndoable(
        title.match_hidden
          ? null
          : {
              revision: result.match_revision,
              before: title.matched_game_uuid ? (title.matched_game ?? null) : null,
            },
      )
      setMessage({
        tone: 'good',
        text: gameUuid
          ? `Matched to ${picked?.name ?? 'the selected game'}.`
          : 'Kept without a match.',
      })
      setOpen(false)
    } catch (err) {
      const info = apiErrorInfo(err, 'Unable to save this decision.')
      if (info.status === 409) {
        setConflict(true)
        setMessage({
          tone: 'bad',
          text: 'This title changed after you opened it (another tab or a sync). Your choice is kept — reload to check it.',
        })
      } else {
        setMessage({ tone: 'bad', text: info.message })
      }
    } finally {
      setBusy(false)
    }
  }

  async function undo() {
    if (undoable === null) return
    setBusy(true)
    try {
      const result = await undoOwnershipMatch(title.id, undoable.revision)
      onChange({
        ...title,
        matched_game_uuid: result.matched_game_uuid,
        match_available: Boolean(result.matched_game_uuid),
        match_reviewed: result.match_reviewed,
        match_revision: result.match_revision,
        // The game the title was linked to before the decision, not the one
        // just undone. Unknown (null) reads as "this library game".
        matched_game: result.matched_game_uuid ? undoable.before : null,
        match_hidden: false,
      })
      setUndoable(null)
      setMessage({ tone: 'good', text: 'Your last decision was undone.' })
    } catch (err) {
      const info = apiErrorInfo(err, 'Unable to undo.')
      if (info.status === 409) {
        setUndoable(null)
        setConflict(true)
        setMessage({
          tone: 'bad',
          text: 'This title changed since your decision, so it cannot be undone. Reload it to see where it stands.',
        })
      } else {
        // A refusal (the earlier game is no longer available) repeats on every
        // press, so the Undo goes; a network error keeps it for a retry.
        if (info.status === 404) setUndoable(null)
        setMessage({ tone: 'bad', text: info.message })
      }
    } finally {
      setBusy(false)
    }
  }

  /** A controller's A button arrives as Enter, which does not check a radio by itself. */
  const chooseOnEnter = (value: string) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      setChoice(value)
    }
  }

  return (
    <li ref={rowRef} className="od-review__row" data-tone={status.tone}>
      <div className="od-review__head">
        <strong className="od-review__name">{title.name || 'Unnamed title'}</strong>
        <span className="od-review__badge" data-tone={status.tone}>
          {status.label}
        </span>
      </div>
      <p className="od-review__source">
        {store} · ID {title.external_app_id}
      </p>
      {title.match_hidden ? (
        <p className="od-review__current">Linked to a game in a library you cannot open.</p>
      ) : null}
      {title.matched_game_uuid ? (
        <p className="od-review__current">
          Linked to{' '}
          <Link to={`/game/${title.matched_game_uuid}`}>
            {title.matched_game?.name || 'this library game'}
          </Link>
          {title.matched_game?.platform ? ` (${title.matched_game.platform})` : ''}
        </p>
      ) : null}
      {message ? (
        <p
          className="od-review__message"
          data-tone={message.tone}
          role={message.tone === 'bad' ? 'alert' : 'status'}
        >
          {message.text}
        </p>
      ) : null}
      <div className="od-review__actions">
        <Button
          ref={toggleRef}
          data-od-nav
          size="sm"
          aria-expanded={open}
          aria-controls={open ? `${id}-panel` : undefined}
          disabled={busy}
          onClick={openReview}
        >
          {open ? 'Close' : 'Review match'}
        </Button>
        {undoable !== null ? (
          <Button data-od-nav size="sm" variant="quiet" disabled={busy} onClick={undo}>
            Undo
          </Button>
        ) : null}
        {conflict ? (
          <Button
            ref={reloadRef}
            data-od-nav
            size="sm"
            variant="primary"
            disabled={busy}
            onClick={reload}
          >
            Reload title
          </Button>
        ) : null}
      </div>
      {open ? (
        <fieldset id={`${id}-panel`} className="od-review__panel">
          <legend>Which library game is this?</legend>
          {candidates === null ? (
            <p className="od-review__lede">Looking for games with this name…</p>
          ) : null}
          {candidates && candidates.length === 0 ? (
            <p className="od-review__lede">
              No library game has this exact name. You can keep it unmatched.
            </p>
          ) : null}
          {(candidates || []).map((candidate) => (
            <label key={candidate.game_uuid} className="od-review__option">
              <input
                type="radio"
                data-od-nav
                name={`${id}-choice`}
                value={candidate.game_uuid}
                checked={choice === candidate.game_uuid}
                onChange={() => setChoice(candidate.game_uuid)}
                onKeyDown={chooseOnEnter(candidate.game_uuid)}
              />
              <span>
                {candidate.name}
                {candidate.platform ? ` · ${candidate.platform}` : ''}
                {candidate.game_uuid === title.matched_game_uuid ? ' · current match' : ''}
              </span>
            </label>
          ))}
          {truncated ? (
            <p className="od-review__lede">Only the first 20 suggestions are shown.</p>
          ) : null}
          <label className="od-review__option">
            <input
              type="radio"
              data-od-nav
              name={`${id}-choice`}
              value={NONE}
              checked={choice === NONE}
              onChange={() => setChoice(NONE)}
              onKeyDown={chooseOnEnter(NONE)}
            />
            <span>
              {title.match_hidden
                ? 'Remove this match (you cannot undo this: the game is in a library you cannot open)'
                : title.matched_game_uuid
                  ? 'Remove this match'
                  : 'None of these — keep unmatched'}
            </span>
          </label>
          <Button
            data-od-nav
            size="sm"
            variant="primary"
            disabled={busy || choice === null}
            onClick={confirm}
          >
            {busy ? 'Saving…' : 'Confirm'}
          </Button>
        </fieldset>
      ) : null}
    </li>
  )
}
