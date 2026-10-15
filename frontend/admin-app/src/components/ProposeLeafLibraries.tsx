import { useMemo, useState } from 'react'
import { confirmAction, Button, PageStatus } from '@oneirodex/ui'

import { DataTable } from './DataTable'
import {
  confirmCreateSelected,
  fetchProposeLeafLibraries,
  type CandidateRow,
  type LeafCreateResult,
} from '../api/proposeLeafLibrariesApi'
import { errorText } from '../utils/errorText'
import './ProposeLeafLibraries.css'

/**
 * Admin: propose per-platform leaf libraries under a console/tree root,
 * multi-select candidates, create only on confirm (never auto-create).
 */
export function ProposeLeafLibraries({
  heading = 'Propose leaf libraries',
  lede = 'Point at a console or platform tree root. Review candidates, then confirm — Oneirodex never auto-creates libraries or family mega-libs.',
} = {}) {
  const [root, setRoot] = useState('')
  const [candidates, setCandidates] = useState<CandidateRow[]>([])
  const [proposedRoot, setProposedRoot] = useState('')
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [loading, setLoading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [confirmLog, setConfirmLog] = useState<LeafCreateResult[]>([])

  const selectedCount = selected.size
  const allSelected = candidates.length > 0 && selectedCount === candidates.length

  const selectedRows = useMemo(
    () => candidates.filter((c) => selected.has(c.id)),
    [candidates, selected],
  )

  async function onPropose(event?: { preventDefault?: () => void }) {
    event?.preventDefault?.()
    setLoading(true)
    setError('')
    setStatus('')
    setConfirmLog([])
    setUnavailable(false)
    setCandidates([])
    setSelected(new Set())
    setProposedRoot('')

    try {
      const result: any = await fetchProposeLeafLibraries(root)
      if (result.unavailable) {
        setUnavailable(true)
        setError(result.error || 'Propose API unavailable.')
        return
      }
      if (result.error) {
        setError(result.error)
        return
      }
      const rows = result.candidates || []
      setCandidates(rows)
      setProposedRoot(result.root || root.trim())
      if (!rows.length) {
        setStatus(
          'No leaf candidates under this root. Family mega-lib roots and emu/FE installs are never proposed.',
        )
      } else {
        setStatus(
          `${rows.length} candidate${rows.length === 1 ? '' : 's'} — select leaves, then Confirm create. Nothing is created until you confirm.`,
        )
      }
    } catch (err) {
      setError(errorText(err) || String(err))
    } finally {
      setLoading(false)
    }
  }

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
      return
    }
    setSelected(new Set(candidates.map((c) => c.id)))
  }

  async function onConfirm() {
    if (!selectedRows.length || confirming) return
    const ok = await confirmAction({
      title: `Create ${selectedRows.length} librar${selectedRows.length === 1 ? 'y' : 'ies'} and queue a first scan for each?`,
      body: 'Nothing has been written yet — this is the step that does it.',
      confirmLabel: `Create librar${selectedRows.length === 1 ? 'y' : 'ies'}`,
      tone: 'neutral',
    })
    if (!ok) return

    setConfirming(true)
    setError('')
    setStatus('Creating selected libraries…')
    try {
      const outcome = await confirmCreateSelected(selectedRows)
      setConfirmLog(outcome.results)
      setStatus(
        `Done: ${outcome.created} created, ${outcome.scanned} scan(s) queued, ${outcome.failed} failed.`,
      )
      if (outcome.created > 0) {
        // Drop successfully created rows from the table so re-confirm is not accidental.
        const failedPaths = new Set(outcome.results.filter((r) => !r.ok).map((r) => r.path))
        const kept = candidates.filter((c) => failedPaths.has(c.path) || !selected.has(c.id))
        const keptSelected = new Set(kept.filter((c) => selected.has(c.id)).map((c) => c.id))
        setCandidates(kept)
        setSelected(keptSelected)
      }
    } catch (err) {
      setError(errorText(err) || String(err))
    } finally {
      setConfirming(false)
    }
  }

  return (
    <section className="od-propose-leaf" aria-labelledby="od-propose-leaf-title">
      <div className="od-propose-leaf__header">
        <h2 id="od-propose-leaf-title" className="od-admin-panel-title">
          {heading}
        </h2>
        <p className="od-admin-lede">{lede}</p>
      </div>

      <form className="od-propose-leaf__form" onSubmit={onPropose}>
        <label className="od-propose-leaf__label" htmlFor="od-propose-leaf-root">
          Root path
        </label>
        <div className="od-propose-leaf__row">
          <input
            id="od-propose-leaf-root"
            className="od-propose-leaf__input"
            type="text"
            value={root}
            onChange={(e) => setRoot(e.target.value)}
            placeholder="/storage/games/_console-gaming"
            autoComplete="off"
            disabled={loading || confirming}
          />
          <Button
            type="submit"
            className="od-btn--accent"
            disabled={loading || confirming || !root.trim()}
          >
            {loading ? 'Proposing…' : 'Propose'}
          </Button>
        </div>
        <p className="od-propose-leaf__hint">
          Absolute path under allowed bases. Propose lists candidates only — create happens on
          Confirm.
        </p>
      </form>

      {unavailable ? (
        <PageStatus
          announcement="status"
          className={'od-propose-leaf__banner od-propose-leaf__banner--soft'}
        >
          {error}
        </PageStatus>
      ) : null}

      {/* The soft `unavailable` banner above and the live `status` line below
          stay as they are: one discloses that a feature is switched off, the
          other is streaming progress. Neither is a page loading/error state. */}
      {!unavailable ? <PageStatus error={error} /> : null}

      {status ? (
        <PageStatus announcement="status" className="od-propose-leaf__status">
          {status}
          {proposedRoot ? (
            <>
              {' '}
              <span className="od-propose-leaf__muted">
                Root: <code>{proposedRoot}</code>
              </span>
            </>
          ) : null}
        </PageStatus>
      ) : null}

      {candidates.length > 0 ? (
        <div className="od-admin-panel od-propose-leaf__panel">
          <div className="od-propose-leaf__toolbar">
            <label className="od-propose-leaf__check">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                disabled={confirming}
              />
              Select all ({candidates.length})
            </label>
            <Button
              type="button"
              className="od-btn--accent"
              onClick={() => void onConfirm()}
              disabled={confirming || selectedCount === 0}
            >
              {confirming ? 'Creating…' : `Confirm create (${selectedCount})`}
            </Button>
          </div>

          {/* Sorting and filtering a scan result is the point of this screen —
              a root scan can propose dozens of folders and "show me the SNES
              ones" was previously a manual read (W27-C1).

              Selection is safe under both: it is held outside the table and
              keyed by row id, so re-ordering or filtering never moves a tick to
              a different row. The Select column opts out of sorting and
              filtering, since neither means anything for a checkbox. */}
          <DataTable
            rows={candidates}
            getRowKey={(row) => row.id}
            emptyMessage="No candidate folders."
            initialSort={{ key: 'suggested_name', dir: 'asc' }}
            dense
            columns={[
              {
                key: 'select',
                label: 'Select',
                sortable: false,
                filterable: false,
                render: (row) => (
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.suggested_name}`}
                    checked={selected.has(row.id)}
                    onChange={() => toggleOne(row.id)}
                    disabled={confirming}
                  />
                ),
              },
              { key: 'suggested_name', label: 'Suggested name' },
              {
                key: 'platform',
                label: 'Platform',
                render: (row) => <code>{row.platform}</code>,
              },
              { key: 'scan_mode', label: 'Mode' },
              { key: 'scan_depth', label: 'Depth' },
              {
                key: 'path',
                label: 'Path',
                render: (row) => <code className="od-propose-leaf__path">{row.path}</code>,
              },
              {
                key: 'reason',
                label: 'Reason',
                render: (row) => row.reason || '—',
              },
            ]}
          />
        </div>
      ) : null}

      {confirmLog.length > 0 ? (
        <div className="od-propose-leaf__log" aria-live="polite">
          <h3 className="od-admin-panel-title">Confirm results</h3>
          <ul>
            {confirmLog.map((row) => (
              <li key={`${row.path}-${row.stage}-${row.ok}`}>
                <strong>{row.name}</strong>
                {row.ok ? (
                  <span> — {row.note || 'OK'}</span>
                ) : (
                  <span className="od-propose-leaf__fail"> — {row.error || 'Failed'}</span>
                )}
                <br />
                <code className="od-propose-leaf__path">{row.path}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
