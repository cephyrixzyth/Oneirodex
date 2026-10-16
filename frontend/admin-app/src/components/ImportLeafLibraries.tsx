import { useMemo, useState } from 'react'
import { confirmAction, Button, PageStatus } from '@oneirodex/ui'

import { DataTable } from './DataTable'
import {
  confirmCreateSelected,
  fetchImportLeafLibrariesPreview,
  type CandidateRow,
  type ImportPreviewError,
  type LeafCreateResult,
} from '../api/proposeLeafLibrariesApi'
import { errorText } from '../utils/errorText'
import './ProposeLeafLibraries.css'

/**
 * Admin: CSV/JSON leaf library import preview → multi-select → Confirm create
 * (same create path as Propose; never auto-create).
 */
export function ImportLeafLibraries({
  heading = 'Import leaf libraries (CSV / JSON)',
  lede = 'Upload or paste leaf definitions, preview candidates and row errors, then confirm create — Oneirodex never auto-creates libraries or family mega-libs.',
} = {}) {
  const [inputMode, setInputMode] = useState('json')
  const [pasteText, setPasteText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [candidates, setCandidates] = useState<CandidateRow[]>([])
  const [rowErrors, setRowErrors] = useState<ImportPreviewError[]>([])
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [loading, setLoading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [createHint, setCreateHint] = useState('')
  const [confirmLog, setConfirmLog] = useState<LeafCreateResult[]>([])

  const selectedCount = selected.size
  const allSelected = candidates.length > 0 && selectedCount === candidates.length

  const selectedRows = useMemo(
    () => candidates.filter((c) => selected.has(c.id)),
    [candidates, selected],
  )

  const canPreview = inputMode === 'file' ? Boolean(file) : Boolean(String(pasteText || '').trim())

  async function onPreview(event?: { preventDefault?: () => void }) {
    event?.preventDefault?.()
    setLoading(true)
    setError('')
    setStatus('')
    setConfirmLog([])
    setUnavailable(false)
    setCandidates([])
    setRowErrors([])
    setSelected(new Set())
    setCreateHint('')

    try {
      const result: any = await fetchImportLeafLibrariesPreview({
        mode: inputMode,
        text: pasteText,
        file,
      })
      if (result.unavailable) {
        setUnavailable(true)
        setError(result.error || 'Import preview API unavailable.')
        return
      }
      if (result.error) {
        setError(result.error)
        return
      }
      const rows = result.candidates || []
      const errs = result.errors || []
      setCandidates(rows)
      setRowErrors(errs)
      setCreateHint(result.createHint || '')
      const count = rows.length
      const errCount = typeof result.errorCount === 'number' ? result.errorCount : errs.length
      if (!count && !errCount) {
        setStatus('No candidates and no row errors — check the payload shape.')
      } else if (!count) {
        setStatus(
          `${errCount} row error${errCount === 1 ? '' : 's'} — nothing to create. Fix rejected rows (family mega-libs are never imported).`,
        )
      } else {
        setStatus(
          `${count} candidate${count === 1 ? '' : 's'}${
            errCount ? `, ${errCount} row error${errCount === 1 ? '' : 's'}` : ''
          } — select leaves, then Confirm create. Nothing is created until you confirm.`,
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
    <section className="od-propose-leaf od-import-leaf" aria-labelledby="od-import-leaf-title">
      <div className="od-propose-leaf__header">
        <h2 id="od-import-leaf-title" className="od-admin-panel-title">
          {heading}
        </h2>
        <p className="od-admin-lede">{lede}</p>
      </div>

      <form className="od-propose-leaf__form" onSubmit={onPreview}>
        <fieldset className="od-import-leaf__modes" disabled={loading || confirming}>
          <legend className="od-propose-leaf__label">Input</legend>
          <div className="od-propose-leaf__row" role="radiogroup" aria-label="Import input mode">
            <label className="od-propose-leaf__check">
              <input
                type="radio"
                name="od-import-mode"
                value="json"
                checked={inputMode === 'json'}
                onChange={() => setInputMode('json')}
              />
              Paste JSON
            </label>
            <label className="od-propose-leaf__check">
              <input
                type="radio"
                name="od-import-mode"
                value="csv"
                checked={inputMode === 'csv'}
                onChange={() => setInputMode('csv')}
              />
              Paste CSV
            </label>
            <label className="od-propose-leaf__check">
              <input
                type="radio"
                name="od-import-mode"
                value="file"
                checked={inputMode === 'file'}
                onChange={() => setInputMode('file')}
              />
              Upload file
            </label>
          </div>
        </fieldset>

        {inputMode === 'file' ? (
          <div className="od-propose-leaf__row">
            <label className="od-propose-leaf__label" htmlFor="od-import-leaf-file">
              File (.json / .csv)
            </label>
            <input
              id="od-import-leaf-file"
              className="od-propose-leaf__input"
              type="file"
              accept=".json,.csv,application/json,text/csv,text/plain"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              disabled={loading || confirming}
            />
            <Button
              type="submit"
              className="od-btn--accent"
              disabled={loading || confirming || !canPreview}
            >
              {loading ? 'Previewing…' : 'Preview'}
            </Button>
          </div>
        ) : (
          <>
            <label className="od-propose-leaf__label" htmlFor="od-import-leaf-paste">
              {inputMode === 'csv' ? 'CSV text' : 'JSON text'}
            </label>
            <textarea
              id="od-import-leaf-paste"
              className="od-propose-leaf__input od-import-leaf__paste"
              rows={8}
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              placeholder={
                inputMode === 'csv'
                  ? 'path,suggested_name,platform,scan_mode,scan_depth\n/storage/games/Switch,Nintendo Switch,SWITCH,folders,1'
                  : '[{"path":"/storage/games/Switch","suggested_name":"Nintendo Switch","platform":"SWITCH","scan_mode":"folders","scan_depth":1}]'
              }
              spellCheck={false}
              disabled={loading || confirming}
            />
            <div className="od-propose-leaf__row">
              <Button
                type="submit"
                className="od-btn--accent"
                disabled={loading || confirming || !canPreview}
              >
                {loading ? 'Previewing…' : 'Preview'}
              </Button>
            </div>
          </>
        )}

        <p className="od-propose-leaf__hint">
          Preview validates paths and platforms only — create happens on Confirm. Family mega-lib
          parents (NINTENDO / Sega / Sony / …) are rejected into errors.
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
        </PageStatus>
      ) : null}

      {createHint && candidates.length > 0 ? (
        <p className="od-propose-leaf__muted">{createHint}</p>
      ) : null}

      {rowErrors.length > 0 ? (
        <div
          className="od-admin-panel od-propose-leaf__panel od-import-leaf__errors"
          role="region"
          aria-labelledby="od-import-leaf-errors-title"
        >
          <h3 id="od-import-leaf-errors-title" className="od-admin-panel-title">
            Row errors ({rowErrors.length})
          </h3>
          {/* Grouping errors by code is how you tell "one malformed column" from
              "this file is wrong throughout", so this one earns sorting too.
              Index sorts numerically because DataTable compares numbers as
              numbers — as strings, row 10 would sort before row 2. */}
          <DataTable
            rows={rowErrors}
            getRowKey={(row) => row.id}
            emptyMessage="No row errors."
            initialSort={{ key: 'index', dir: 'asc' }}
            dense
            columns={[
              {
                key: 'index',
                label: 'Index',
                value: (row) => (row.index == null ? null : Number(row.index)),
                render: (row) => (row.index == null ? '—' : row.index),
              },
              {
                key: 'code',
                label: 'Code',
                render: (row) => <code>{row.code || '—'}</code>,
              },
              {
                key: 'path',
                label: 'Path',
                render: (row) =>
                  row.path ? <code className="od-propose-leaf__path">{row.path}</code> : '—',
              },
              { key: 'message', label: 'Message' },
            ]}
          />
        </div>
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

          {/* Same grid as ProposeLeafLibraries — an import can carry a hundred
              rows from a CSV, so sorting and filtering matter more here, not
              less. Selection lives outside the table and is keyed by row id, so
              re-ordering cannot move a tick onto a different row. */}
          <DataTable
            rows={candidates}
            getRowKey={(row) => row.id}
            emptyMessage="No candidate rows in this file."
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
