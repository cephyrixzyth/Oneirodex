import { Button } from '@oneirodex/ui'
import { postJson } from '../api/adminApi'
import { AdminLink } from '../components/AdminLink'
import {
  detectLeafType,
  detectPlatformMismatch,
  isGarbageScaffolding,
} from '../components/unmatchedTriage'
import type { ScanUnmatchedModel } from './scanUnmatchedTypes'

type Props = Pick<
  ScanUnmatchedModel,
  | 'badMatchReasons'
  | 'loading'
  | 'error'
  | 'setError'
  | 'setPathModal'
  | 'setActionStatus'
  | 'busyId'
  | 'selectedIds'
  | 'setSelectedIds'
  | 'searchNames'
  | 'setSearchNames'
  | 'setReloadKey'
  | 'sort'
  | 'visibleRows'
  | 'runRowAction'
  | 'toggleSelected'
  | 'toggleIgnore'
  | 'markKind'
  | 'saveSearchName'
  | 'retryMatch'
  | 'placeUpdate'
  | 'saveBadMatch'
  | 'deleteFolderFromDisk'
  | 'toggleSort'
>
export function ScanUnmatchedTable({
  badMatchReasons,
  loading,
  error,
  setError,
  setPathModal,
  setActionStatus,
  busyId,
  selectedIds,
  setSelectedIds,
  searchNames,
  setSearchNames,
  setReloadKey,
  sort,
  visibleRows,
  runRowAction,
  toggleSelected,
  toggleIgnore,
  markKind,
  saveSearchName,
  retryMatch,
  placeUpdate,
  saveBadMatch,
  deleteFolderFromDisk,
  toggleSort,
}: Props) {
  return (
    <div
      className="od-scan-unmatched__table-wrap"
      tabIndex={0}
      aria-label="Unmatched folders table"
    >
      <table className="od-scan-unmatched__table">
        <thead>
          <tr>
            <th scope="col">
              <input
                type="checkbox"
                aria-label="Select visible folders"
                checked={
                  visibleRows.length > 0 &&
                  visibleRows.every((row) => selectedIds.has(String(row.id)))
                }
                onChange={(event) =>
                  setSelectedIds((current) => {
                    const next = new Set(current)
                    visibleRows.forEach((row) =>
                      event.target.checked ? next.add(String(row.id)) : next.delete(String(row.id)),
                    )
                    return next
                  })
                }
              />
            </th>
            {(
              [
                ['folder', 'Folder'],
                ['status', 'Status'],
                ['library', 'Library'],
                ['system', 'System'],
                ['region', 'Region'],
              ] as const
            ).map(([key, label]) => (
              <th
                key={key}
                scope="col"
                aria-sort={
                  sort.key === key ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'
                }
              >
                <Button
                  type="button"
                  aria-pressed={sort.key === key}
                  className={`od-scan-unmatched__sort${sort.key === key ? ' is-active' : ''}`}
                  onClick={() => toggleSort(key)}
                >
                  {label}
                  {sort.key === key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ' ↕'}
                </Button>
              </th>
            ))}
            <th scope="col">Actions</th>
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((row) => (
            <tr key={row.id} data-status={row.status || 'Unknown'}>
              <td>
                <input
                  type="checkbox"
                  aria-label={`Select folder ${row.folder_path || row.id}`}
                  checked={selectedIds.has(String(row.id))}
                  onChange={() => toggleSelected(row.id)}
                />
              </td>
              <td className="od-scan-unmatched__path">
                <label
                  className="od-scan-unmatched__name-label"
                  htmlFor={`unmatched-name-${row.id}`}
                >
                  Search name
                </label>
                <div className="od-scan-unmatched__name-edit">
                  <input
                    id={`unmatched-name-${row.id}`}
                    type="text"
                    value={
                      searchNames[String(row.id)] ??
                      row.search_name ??
                      row.folder_name ??
                      row.folder_path?.split(/[\\/]/).filter(Boolean).at(-1) ??
                      ''
                    }
                    onChange={(event) =>
                      setSearchNames((current) => ({
                        ...current,
                        [String(row.id)]: event.target.value,
                      }))
                    }
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault()
                        void saveSearchName(row)
                      }
                    }}
                    title="Search name for Fix search; does not rename the folder on disk"
                  />
                  <Button
                    type="button"
                    className="od-scan-unmatched__save"
                    disabled={busyId === row.id}
                    onClick={() => void saveSearchName(row)}
                  >
                    Save
                  </Button>
                </div>
                <small className="od-scan-unmatched__on-disk">
                  On disk:{' '}
                  <span title={row.folder_path || undefined}>
                    {row.folder_path?.split(/[\\/]/).filter(Boolean).at(-1) || 'Unknown path'}
                  </span>
                </small>
                <div className="od-scan-unmatched__badges">
                  <span>
                    {detectLeafType(row.folder_path) === 'file-leaf' ? 'ROM files' : 'Folder'}
                  </span>
                  {detectPlatformMismatch(row.folder_path, row.library_name, row.platform_name) ? (
                    <span>Platform mismatch</span>
                  ) : null}
                  {isGarbageScaffolding(row) ? <span>Garbage</span> : null}
                </div>
                {row.matched_game?.name ? (
                  <small>Matched title: {row.matched_game.name}</small>
                ) : null}
                {row.transforms?.length || row.stage_e_candidates?.length ? (
                  <details className="od-scan-unmatched__details">
                    <summary>Match details</summary>
                    {row.transforms?.length ? (
                      <ol>
                        {row.transforms.map((step, index) => (
                          <li key={`${step.stage || 'step'}-${index}`}>
                            <strong>{step.stage || 'Name change'}</strong>{' '}
                            <code>{step.before || ''}</code> → <code>{step.after || ''}</code>
                            {step.reason ? ` · ${step.reason}` : ''}
                          </li>
                        ))}
                      </ol>
                    ) : null}
                    {row.stage_e_candidates?.length ? (
                      <ul>
                        {row.stage_e_candidates.map((candidate, index) => (
                          <li key={`${candidate.source || 'catalog'}-${index}`}>
                            {candidate.name || 'Catalog candidate'}
                            {candidate.source ? ` · ${candidate.source}` : ''}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </details>
                ) : null}
              </td>
              <td className="od-scan-unmatched__status">
                <span
                  className={`od-scan-unmatched__status-label od-scan-unmatched__status-label--${String(row.status || 'unknown').toLowerCase()}`}
                >
                  {row.status || 'Unknown'}
                </span>
                {row.why_unmatched ||
                row.unmatched_reason ||
                row.match_reason ||
                row.match_score != null ? (
                  <small className="od-scan-unmatched__why">
                    <strong>Why unmatched?</strong>{' '}
                    {row.why_unmatched ||
                      row.unmatched_reason ||
                      row.match_reason ||
                      'No match reason'}
                    {row.match_score != null ? ` · Match confidence ${row.match_score}` : ''}
                  </small>
                ) : null}
              </td>
              <td>{row.library_name || '—'}</td>
              <td>{row.platform_name || '—'}</td>
              <td>{row.rom_region || '—'}</td>
              <td>
                <details
                  className="od-scan-unmatched__row-menu"
                  onKeyDown={(event) => {
                    if (event.key !== 'Escape' || !event.currentTarget.open) return
                    event.preventDefault()
                    event.currentTarget.open = false
                    event.currentTarget.querySelector('summary')?.focus()
                  }}
                >
                  <summary className="od-btn od-scan-unmatched__row-menu-summary">Actions</summary>
                  <div
                    className="od-scan-unmatched__row-actions"
                    role="toolbar"
                    aria-label={`Actions for ${row.folder_path || row.id}`}
                  >
                    <Button
                      type="button"
                      onClick={() => setPathModal(String(row.folder_path || ''))}
                    >
                      Open path
                    </Button>
                    <AdminLink
                      className="od-btn"
                      to={`/add_game_manual?${new URLSearchParams({
                        full_disk_path: String(row.folder_path || ''),
                        library_uuid: String(row.library_uuid || ''),
                        name: String(
                          row.search_name ||
                            row.suggested_search_name ||
                            row.folder_name ||
                            String(row.folder_path || '')
                              .split(/[\\/]/)
                              .pop() ||
                            '',
                        ),
                        from_unmatched: 'true',
                      })}`}
                    >
                      Fix search
                    </AdminLink>
                    {row.status === 'Unmatched' ||
                    row.status === 'Pending' ||
                    row.status === 'Duplicate' ? (
                      <>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void markKind(row, 'experience', 'Soft title')}
                        >
                          Mark Soft
                        </Button>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void markKind(row, 'emulator', 'Emulator')}
                        >
                          Mark Emu
                        </Button>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void markKind(row, 'tool', 'Utility')}
                        >
                          Mark Util
                        </Button>
                      </>
                    ) : null}
                    {row.status === 'Unmatched' ? (
                      row.is_bare_update_package ? (
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void placeUpdate(row)}
                        >
                          Place update
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void retryMatch(row)}
                        >
                          Retry match
                        </Button>
                      )
                    ) : null}
                    {badMatchReasons.length ? (
                      <label className="od-scan-unmatched__badmatch">
                        Bad match
                        <select
                          aria-label={`Flag bad match for ${row.folder_path || row.id}`}
                          disabled={busyId === row.id}
                          value={row.bad_match_reason || ''}
                          onChange={(event) => void saveBadMatch(row, event.target.value)}
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
                    {row.status !== 'Duplicate' ? (
                      <Button
                        type="button"
                        disabled={busyId === row.id}
                        onClick={(event) =>
                          void toggleIgnore(row, event.currentTarget.closest('details'))
                        }
                      >
                        {row.status === 'Ignore' ? 'Unignore' : 'Ignore'}
                      </Button>
                    ) : null}
                    {row.status === 'Duplicate' ? (
                      <>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void runRowAction(row, 'merge')}
                        >
                          Merge
                        </Button>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void runRowAction(row, 'keep')}
                        >
                          Keep
                        </Button>
                        <Button
                          type="button"
                          disabled={busyId === row.id}
                          onClick={() => void runRowAction(row, 'ignore')}
                        >
                          Ignore
                        </Button>
                      </>
                    ) : null}
                    <Button
                      type="button"
                      disabled={busyId === row.id}
                      onClick={() => {
                        if (!window.confirm('Remove this entry from the unmatched list?')) return
                        void postJson('/api/unmatched_folders/batch/clear', {
                          ids: [String(row.id)],
                        })
                          .then(() => {
                            setActionStatus('Entry removed successfully.')
                            setReloadKey((value) => value + 1)
                          })
                          .catch(setError)
                      }}
                    >
                      Clear
                    </Button>
                    <Button
                      type="button"
                      className="od-btn od-btn--danger"
                      disabled={busyId === row.id}
                      onClick={() => void deleteFolderFromDisk(row)}
                    >
                      Delete from disk
                    </Button>
                  </div>
                </details>
              </td>
            </tr>
          ))}
          {!loading && !error && visibleRows.length === 0 ? (
            <tr>
              <td colSpan={7}>No folders for this filter.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}
