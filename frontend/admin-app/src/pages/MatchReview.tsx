import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import type { UnmatchedRow } from './scanUnmatchedTypes'
export function MatchReview({ row, onChange }: { row: UnmatchedRow; onChange: () => void }) {
  const [candidate, setCandidate] = useState(row.matched_game_uuid || '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [choices, setChoices] = useState<
    Array<{ uuid: string; name: string; year?: number; provider_id?: number }>
  >([])
  const [searched, setSearched] = useState(false)
  useEffect(() => {
    setChoices([])
    setSearched(false)
    if (query.trim().length < 2) return
    const abort = new AbortController()
    const timer = window.setTimeout(() => {
      getJson(
        '/api/unmatched/' +
          encodeURIComponent(String(row.id)) +
          '/candidates?q=' +
          encodeURIComponent(query.trim()),
        { signal: abort.signal },
      )
        .then((data) => {
          if (!abort.signal.aborted) {
            setChoices(data.items || [])
            setSearched(true)
          }
        })
        .catch(() => {
          if (!abort.signal.aborted) setError('Candidate search is unavailable')
        })
    }, 250)
    return () => {
      clearTimeout(timer)
      abort.abort()
    }
  }, [query, row.id])
  async function submit(action: 'accept' | 'reject' | 'undo') {
    setBusy(true)
    setError('')
    try {
      await postJson('/api/unmatched/' + encodeURIComponent(String(row.id)) + '/review', {
        action,
        candidate: candidate.trim() || null,
        note: note.trim(),
        revision: row.review?.revision || 0,
      })
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the review')
    } finally {
      setBusy(false)
    }
  }
  return (
    <details>
      <summary>Review catalog match</summary>
      {row.review?.current && (
        <p>
          {row.review.current.action} · {row.review.current.label || 'No candidate'} ·{' '}
          {row.review.current.note}
        </p>
      )}
      <label>
        Find a title in {row.library_name || 'this library'}
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          maxLength={120}
        />
      </label>
      {choices.length > 0 && (
        <ul>
          {choices.map((choice) => (
            <li key={choice.uuid}>
              <Button
                aria-pressed={candidate === choice.uuid}
                onClick={() => setCandidate(choice.uuid)}
              >
                {choice.name}
                {choice.year ? ' · ' + choice.year : ''}
                {choice.provider_id ? ' · IGDB ' + choice.provider_id : ''}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {searched && !choices.length && (
        <PageStatus announcement="status" inline>
          No matching titles in this library.
        </PageStatus>
      )}
      <label>
        Candidate game UUID
        <input value={candidate} onChange={(e) => setCandidate(e.target.value)} maxLength={36} />
      </label>
      <label>
        Reason
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </label>
      <Button
        disabled={busy || !candidate.trim() || !note.trim()}
        onClick={() => void submit('accept')}
      >
        Accept match
      </Button>
      <Button disabled={busy || !note.trim()} onClick={() => void submit('reject')}>
        Reject match
      </Button>
      {row.review?.can_undo && (
        <Button disabled={busy} onClick={() => void submit('undo')}>
          Undo decision
        </Button>
      )}
      {error && <PageStatus error={error} />}
    </details>
  )
}
