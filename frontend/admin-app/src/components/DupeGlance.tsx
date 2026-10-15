import { memo, useEffect, useMemo, useState, type Key, type ReactNode } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { PM_IGNORE } from './formIgnore'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import {
  buildDupeCompare,
  folderBasename,
  mergeDuplicateHits,
  normalizeMatchedGame,
  resolveSearchName,
} from './unmatchedDupe'
import { hasStageEHints } from './stageECandidates'
import './DupeGlance.css'

import type { UnmatchedFolderRow } from './dupeGlance/dupeGlanceTypes'
import {
  BadMatchReason,
  DupeCompare,
  FixLog,
  SUGGESTED_KIND_LABELS,
  StageECandidates,
  TransformTrail,
  formatMatchScore,
  formatWhyUnmatched,
  markKindsOrdered,
  normalizeSuggestedKind,
  normalizeTransforms,
} from './dupeGlance/DupeCompare'

export type { UnmatchedFolderRow } from './dupeGlance/dupeGlanceTypes'
export type { TransformStep } from './dupeGlance/DupeCompare'
export { formatMatchScore, formatWhyUnmatched, normalizeTransforms } from './dupeGlance/DupeCompare'

export const DupeGlance = memo(function DupeGlance({
  onOpenPath,
}: {
  onOpenPath?: (v: any) => void
}) {
  const [rows, setRows] = useState<UnmatchedFolderRow[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [fixLog, setFixLog] = useState<FixLog | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyFolderId, setBusyFolderId] = useState<unknown>(null)
  const [statusFilter, setStatusFilter] = useState('Duplicate')
  const [sortKey, setSortKey] = useState('folder')
  const [sortDir, setSortDir] = useState('asc')
  // UX-C5: the vocabulary is served, never hardcoded here, so it can grow
  // without a frontend release.
  const [badMatchReasons, setBadMatchReasons] = useState<BadMatchReason[]>([])
  const [noteFor, setNoteFor] = useState<unknown>(null)
  const [noteText, setNoteText] = useState('')

  function load() {
    setLoading(true)
    setError(null)
    return getJson('/api/unmatched_folders')
      .then(async (data) => {
        let list: UnmatchedFolderRow[] = Array.isArray(data) ? data : []
        const needsEnrich = list.some(
          (row) =>
            (row.status === 'Duplicate' || row.matched_game_uuid) && !normalizeMatchedGame(row),
        )
        if (needsEnrich) {
          try {
            const dupes = await getJson('/api/unmatched_folders/duplicates')
            list = mergeDuplicateHits(list, dupes)
          } catch {
            // Soft-degrade: glance still works without matched_game hit
          }
        }
        setRows(list)
      })
      .catch((err) => {
        setError(err)
        setRows([])
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    // Soft-degrade: without the vocabulary the rest of triage still works, so a
    // failure here hides the picker rather than breaking the page.
    getJson('/api/unmatched/bad_match_reasons')
      .then((data) => setBadMatchReasons(Array.isArray(data?.reasons) ? data.reasons : []))
      .catch(() => setBadMatchReasons([]))
  }, [])

  async function submitBadMatch(
    row: UnmatchedFolderRow,
    reason: string | null,
    note: string | null,
  ) {
    setBusy(true)
    setBusyFolderId(row.id)
    setError(null)
    try {
      await postJson(`/api/unmatched/${row.id}/bad_match`, {
        reason: reason || null,
        ...(note ? { note } : {}),
      })
      setNoteFor(null)
      setNoteText('')
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
      setBusyFolderId(null)
    }
  }

  function handleBadMatchChange(row: UnmatchedFolderRow, reason: string) {
    // 'other' is not feedback without a note — the API rejects it, so ask here
    // rather than posting something we know will fail.
    if (reason === 'other') {
      setNoteFor(row.id)
      setNoteText(String(row.bad_match_note || ''))
      return
    }
    setNoteFor(null)
    void submitBadMatch(row, reason, null)
  }

  const visible = useMemo(() => {
    if (statusFilter === 'all') return rows
    return rows.filter((row) => row.status === statusFilter)
  }, [rows, statusFilter])

  const sortedVisible = useMemo(() => {
    const list = [...visible]
    const dir = sortDir === 'asc' ? 1 : -1
    list.sort((a, b) => {
      let av = ''
      let bv = ''
      switch (sortKey) {
        case 'status':
          av = String(a.status || '')
          bv = String(b.status || '')
          break
        case 'library':
          av = String(a.library_name || '')
          bv = String(b.library_name || '')
          break
        case 'platform':
          av = String(a.platform_name || '')
          bv = String(b.platform_name || '')
          break
        case 'folder':
        default:
          av = String(resolveSearchName(a) || folderBasename(a.folder_path) || a.folder_path || '')
          bv = String(resolveSearchName(b) || folderBasename(b.folder_path) || b.folder_path || '')
          break
      }
      return av.localeCompare(bv, undefined, { sensitivity: 'base', numeric: true }) * dir
    })
    return list
  }, [visible, sortKey, sortDir])

  const grouped = useMemo(() => {
    const map = new Map<string, UnmatchedFolderRow[]>()
    for (const row of sortedVisible) {
      const key = `${row.library_name || 'Library'}::${row.platform_name || ''}`
      const list = map.get(key) || []
      list.push(row)
      map.set(key, list)
    }
    return [...map.entries()]
  }, [sortedVisible])

  function toggleSort(nextKey: string) {
    if (sortKey === nextKey) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(nextKey)
      setSortDir('asc')
    }
  }

  async function handleReclassify() {
    setBusy(true)
    setFixLog(null)
    try {
      const result = await postJson('/api/unmatched_folders/reclassify_duplicates', {})
      setFixLog({
        ok: true,
        message: `Reclassified ${result.changed_count ?? 0} · kept ${result.kept_count ?? 0} as duplicate`,
        detail: result,
      })
      await load()
    } catch (err) {
      setFixLog({ ok: false, message: errorText(err) || 'Reclassify failed' })
    } finally {
      setBusy(false)
    }
  }

  async function handleBackfillKindHints() {
    const ok = await confirmAction({
      title: 'Fill in missing kind hints from scan proposals?',
      body: 'Only rows with no hint change, and it is safe to re-run.',
      confirmLabel: 'Fill in hints',
      tone: 'neutral',
    })
    if (!ok) {
      return
    }
    setBusy(true)
    setFixLog(null)
    try {
      const result = await postJson('/api/unmatched_folders/backfill_suggested_kind', {})
      const updated = result.updated ?? 0
      const scanned = result.scanned ?? 0
      setFixLog({
        ok: true,
        message: `Kind hints updated ${updated} of ${scanned} scanned${
          result.skipped_no_sidecar ? ` · ${result.skipped_no_sidecar} without proposal` : ''
        }`,
        detail: result,
      })
      await load()
    } catch (err) {
      setFixLog({ ok: false, message: errorText(err) || 'Backfill kind hints failed' })
    } finally {
      setBusy(false)
    }
  }

  async function handleMarkKind(row: UnmatchedFolderRow, itemKind: string) {
    if (busy) return
    setBusy(true)
    setBusyFolderId(row.id)
    setFixLog(null)
    const name = resolveSearchName(row) || folderBasename(row.folder_path)
    try {
      const result = await postJson(`/api/unmatched_folders/${row.id}/mark_kind`, {
        item_kind: itemKind,
        ...(name ? { name } : {}),
      })
      const kindLabel =
        itemKind === 'experience' ? 'Soft title' : itemKind === 'emulator' ? 'Emulator' : 'Utility'
      setFixLog({
        ok: true,
        message: `Cataloged “${result.name || name || 'folder'}” as ${kindLabel} (no IGDB game match)`,
      })
      await load()
    } catch (err) {
      setFixLog({
        ok: false,
        message: errorText(err) || `Could not mark as ${itemKind}`,
      })
    } finally {
      setBusy(false)
      setBusyFolderId(null)
    }
  }

  async function handleFix(row: UnmatchedFolderRow, action: string) {
    if (busy) return
    setBusy(true)
    setBusyFolderId(row.id)
    setFixLog(null)
    try {
      const result = await postJson(`/api/unmatched_folders/${row.id}/fix`, { action })
      const label =
        action === 'merge' ? 'Merged' : action === 'keep' ? 'Kept as Unmatched' : 'Ignored'
      setFixLog({
        ok: true,
        message: `${label}${result.folder_path ? ` · ${result.folder_path}` : ''}`,
      })
      await load()
    } catch (err) {
      setFixLog({ ok: false, message: errorText(err) || `Could not ${action}` })
    } finally {
      setBusy(false)
      setBusyFolderId(null)
    }
  }

  function canMarkKind(status: unknown) {
    return status === 'Unmatched' || status === 'Pending' || status === 'Duplicate'
  }

  return (
    <section className="od-dupe-glance" aria-labelledby="od-dupe-glance-title">
      <div className="od-dupe-glance__header">
        <div>
          <h2 id="od-dupe-glance-title">Dupe glance</h2>
          <p className="od-dupe-glance__lede">
            Compare unmatched / duplicate folders without leaving this page. Open path opens a popup
            (clipboard / companion) — it does not jump to Auto Scan. Mark as Soft title / Emulator /
            Utility catalogs gaming software without a fake IGDB game match. Duplicate rows show a
            side-by-side folder vs library compare (same fields as Scan management).
          </p>
        </div>
        <div className="od-dupe-glance__toolbar">
          <label>
            Status{' '}
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="Duplicate">Duplicate</option>
              <option value="Unmatched">Unmatched</option>
              <option value="Ignore">Ignore</option>
              <option value="all">All</option>
            </select>
          </label>
          <div className="od-dupe-glance__sort" role="group" aria-label="Sort rows">
            <span className="od-dupe-glance__sort-label">Sort</span>
            {[
              ['folder', 'Folder'],
              ['status', 'Status'],
              ['library', 'Library'],
              ['platform', 'Platform'],
            ].map(([key, label]) => (
              <Button
                key={key}
                className={`od-dupe-glance__sort-btn${sortKey === key ? ' is-active' : ''}`}
                aria-pressed={sortKey === key}
                onClick={() => toggleSort(key)}
              >
                {label}
                {sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
              </Button>
            ))}
          </div>
          <Button onClick={() => void load()} disabled={loading}>
            Refresh
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={() => void handleReclassify()}
            title="Downgrade false Duplicate rows when folder titles differ"
          >
            {busy && !busyFolderId ? 'Fixing…' : 'Fix false duplicates'}
          </Button>
          <Button
            type="button"
            disabled={busy}
            onClick={() => void handleBackfillKindHints()}
            title="Fill missing Suggested kind chips from on-disk scan proposals (legacy rows)"
          >
            Backfill kind hints
          </Button>
        </div>
      </div>

      {fixLog ? <PageStatus announcement="status">{fixLog.message}</PageStatus> : null}

      <PageStatus
        loading={loading}
        loadingMessage="Loading unmatched folders…"
        error={error}
        errorMessage="Unable to load unmatched folders."
      />

      {!loading && !error && visible.length === 0 ? (
        <p className="od-dupe-glance__empty">No folders for this filter.</p>
      ) : null}

      {grouped.map(([groupKey, items]) => (
        <div key={groupKey} className="od-dupe-glance__group">
          <h3>{groupKey.replace('::', ' · ')}</h3>
          <ul className="od-dupe-glance__list">
            {items.map((row) => {
              const why = formatWhyUnmatched(row)
              const matchScore = formatMatchScore(row.match_score)
              const transforms = normalizeTransforms(row)
              const marking = busyFolderId === row.id
              const suggestedKind = normalizeSuggestedKind(row.suggested_kind)
              const markKinds = markKindsOrdered(suggestedKind)
              const showWhyUnmatchedLabel = row.status === 'Unmatched' || row.status === 'Pending'
              const diskName = folderBasename(row.folder_path)
              const searchName = resolveSearchName(row)
              const showStageE = hasStageEHints(row)
              const showWhyBlock =
                Boolean(why) ||
                (Boolean(matchScore) && row.status !== 'Duplicate') ||
                transforms.length > 0 ||
                showStageE
              return (
                <li key={row.id as Key} className="od-dupe-glance__row">
                  <div className="od-dupe-glance__actions" role="toolbar" aria-label="Row actions">
                    <Button
                      type="button"
                      onClick={() =>
                        onOpenPath?.({
                          path: row.folder_path,
                          label: 'Unmatched folder',
                          matchReason: why || undefined,
                        })
                      }
                    >
                      Open path
                    </Button>
                    <a
                      className="od-btn"
                      href={`/add_game_manual?full_disk_path=${encodeURIComponent(String(row.folder_path || ''))}&library_uuid=${encodeURIComponent(String(row.library_uuid || ''))}&platform_name=${encodeURIComponent(String(row.platform_name || ''))}&platform_id=${encodeURIComponent(String(row.platform_id || ''))}&from_unmatched=true`}
                      title="Fix search — opens manual add / IGDB search (uses Search name when set)"
                    >
                      Fix search
                    </a>
                    {canMarkKind(row.status)
                      ? markKinds.map(({ kind, label }) => (
                          <Button
                            key={kind}
                            variant={suggestedKind === kind ? 'primary' : 'default'}
                            className={suggestedKind === kind ? 'is-suggested' : undefined}
                            disabled={busy}
                            title={
                              suggestedKind === kind
                                ? `Suggested: catalog as ${label.replace('Mark as ', '')} without an IGDB game match`
                                : `Catalog as ${label.replace('Mark as ', '')} without an IGDB game match`
                            }
                            onClick={() => void handleMarkKind(row, kind)}
                          >
                            {marking ? 'Saving…' : label}
                          </Button>
                        ))
                      : null}
                    {row.status === 'Duplicate' ? (
                      <>
                        <Button
                          type="button"
                          disabled={busy}
                          title="Keep library game; clear this duplicate row"
                          onClick={() => void handleFix(row, 'merge')}
                        >
                          Merge
                        </Button>
                        <Button
                          type="button"
                          disabled={busy}
                          title="Reclassify as Unmatched"
                          onClick={() => void handleFix(row, 'keep')}
                        >
                          Keep
                        </Button>
                        <Button
                          type="button"
                          disabled={busy}
                          title="Ignore this duplicate"
                          onClick={() => void handleFix(row, 'ignore')}
                        >
                          Ignore
                        </Button>
                      </>
                    ) : null}
                    {badMatchReasons.length ? (
                      <label className="od-dupe-glance__badmatch">
                        <span className="od-dupe-glance__badmatch-label">Bad match</span>
                        <select
                          className="od-select"
                          aria-label={`Flag bad match for ${row.folder_path || row.id}`}
                          value={String(row.bad_match_reason || '')}
                          disabled={busy}
                          onChange={(event) => handleBadMatchChange(row, event.target.value)}
                          {...PM_IGNORE}
                        >
                          <option value="">Not flagged</option>
                          {badMatchReasons.map((reason) => (
                            <option key={reason.id} value={reason.id}>
                              {reason.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    {noteFor === row.id ? (
                      <span className="od-dupe-glance__badmatch-note">
                        <input
                          type="text"
                          className="od-input"
                          aria-label="Bad match note"
                          placeholder="What is wrong with this match?"
                          value={noteText}
                          maxLength={500}
                          onChange={(event) => setNoteText(event.target.value)}
                          {...PM_IGNORE}
                        />
                        <Button
                          type="button"
                          variant="primary"
                          disabled={busy || !noteText.trim()}
                          onClick={() => void submitBadMatch(row, 'other', noteText.trim())}
                        >
                          Save note
                        </Button>
                        <Button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            setNoteFor(null)
                            setNoteText('')
                          }}
                        >
                          Cancel
                        </Button>
                      </span>
                    ) : null}
                  </div>
                  <div className="od-dupe-glance__meta">
                    <div className="od-dupe-glance__chips">
                      <span
                        className={`od-dupe-glance__status status-${String(row.status || '').toLowerCase()}`}
                      >
                        {row.status === 'Duplicate'
                          ? 'Duplicate (same title)'
                          : (row.status as ReactNode)}
                      </span>
                      {suggestedKind ? (
                        <span
                          className="od-dupe-glance__suggested"
                          title="Suggested kind from scan proposal (software path)"
                        >
                          Suggested {SUGGESTED_KIND_LABELS[suggestedKind]}
                        </span>
                      ) : null}
                      {row.bad_match_reason ? (
                        <span
                          className="od-dupe-glance__badmatch-chip"
                          title={String(row.bad_match_note || 'Flagged as a bad match')}
                        >
                          Bad match:{' '}
                          {badMatchReasons.find((r) => r.id === row.bad_match_reason)?.label ||
                            (row.bad_match_reason as ReactNode)}
                        </span>
                      ) : null}
                    </div>
                    {searchName && searchName !== diskName ? (
                      <p className="od-dupe-glance__amend">
                        <span className="od-dupe-glance__amend-label">Search name</span>{' '}
                        {searchName}
                        <span className="od-dupe-glance__ondisk"> · On disk: {diskName}</span>
                      </p>
                    ) : diskName ? (
                      <p className="od-dupe-glance__ondisk">On disk: {diskName}</p>
                    ) : null}
                    {buildDupeCompare(row) ? null : (
                      <code title={row.folder_path as string | undefined}>
                        {row.folder_path as ReactNode}
                      </code>
                    )}
                    <DupeCompare row={row} onOpenPath={onOpenPath} />
                    {showWhyBlock ? (
                      <div className="od-dupe-glance__why">
                        {why || (matchScore && row.status !== 'Duplicate') ? (
                          <p className="od-dupe-glance__reason">
                            {showWhyUnmatchedLabel ? (
                              <span className="od-dupe-glance__why-label">Why unmatched? </span>
                            ) : null}
                            {matchScore && row.status !== 'Duplicate' ? (
                              <span
                                className="od-dupe-glance__match-score"
                                title="Match confidence score"
                              >
                                {matchScore}
                              </span>
                            ) : null}
                            {why ? (
                              <>
                                {matchScore && row.status !== 'Duplicate' ? ' ' : null}
                                {why}
                              </>
                            ) : null}
                          </p>
                        ) : showWhyUnmatchedLabel ? (
                          <p className="od-dupe-glance__reason">
                            <span className="od-dupe-glance__why-label">Why unmatched? </span>
                          </p>
                        ) : null}
                        <TransformTrail transforms={transforms} />
                        <StageECandidates row={row} />
                      </div>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </section>
  )
})
