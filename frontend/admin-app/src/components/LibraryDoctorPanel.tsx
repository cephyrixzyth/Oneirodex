import { useState } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { postJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from './DataTable'

type RenamePlan = { kind?: string; from_path?: string; to_path?: string }
type DoctorRow = {
  path: string
  raw_name?: string
  cleaned_name?: string
  suggested_rename?: string
  rename_plan?: RenamePlan[]
}

export function LibraryDoctorPanel() {
  const [open, setOpen] = useState(false)
  const [roots, setRoots] = useState('')
  const [template, setTemplate] = useState('{title}')
  const [limit, setLimit] = useState('')
  const [rows, setRows] = useState<DoctorRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState('')

  function invalidatePreview() {
    setRows(null)
    setStatus('')
    setError(null)
  }

  async function preview() {
    const paths = roots
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean)
    const numericLimit = limit.trim() ? Number(limit) : undefined
    if (!paths.length) {
      setError(new Error('Enter at least one folder path.'))
      return
    }
    if (numericLimit !== undefined && (!Number.isInteger(numericLimit) || numericLimit < 1)) {
      setError(new Error('The batch limit must be a positive whole number.'))
      return
    }

    setBusy(true)
    setError(null)
    setStatus('')
    try {
      const result = await postJson('/api/library_tools/doctor/dry_run', {
        roots: paths,
        template: template.trim() || '{title}',
        ...(numericLimit === undefined ? {} : { limit: numericLimit }),
      })
      const nextRows = Array.isArray(result?.rows) ? result.rows : []
      setRows(nextRows)
      setStatus(
        `${nextRows.length} folder${nextRows.length === 1 ? '' : 's'} previewed. No files have been changed.`,
      )
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function saveProposals() {
    if (!rows?.length || busy) return
    const confirmed = await confirmAction({
      title: `Save suggestions for ${rows.length} folders?`,
      body: 'This writes proposal sidecar files beside the folders. It does not rename them.',
      confirmLabel: 'Save suggestions',
      tone: 'neutral',
    })
    if (!confirmed) return
    await runMutation('/api/library_tools/doctor/write_proposals', { rows }, 'suggestions saved')
  }

  async function applyRenames() {
    if (!rows?.length || busy) return
    const confirmed = await confirmAction({
      title: `Rename ${rows.length} folders on disk?`,
      body: 'This changes real folder paths and cannot be undone from this page. Check the preview before continuing.',
      confirmLabel: 'Rename folders',
      tone: 'danger',
    })
    if (!confirmed) return
    await runMutation(
      '/api/library_tools/doctor/apply_renames',
      { rows, template: template.trim() || '{title}' },
      'rename run finished',
    )
  }

  async function runMutation(url: string, body: Record<string, unknown>, completion: string) {
    setBusy(true)
    setError(null)
    setStatus('')
    try {
      const result = await postJson(url, body)
      const outcomes = Array.isArray(result?.results) ? result.results : []
      const succeeded = outcomes.filter((row: { ok?: boolean }) => row.ok).length
      setStatus(
        `${completion}: ${succeeded} succeeded, ${outcomes.length - succeeded} failed. Run a new preview before another action.`,
      )
      setRows(null)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const columns: DataTableColumn[] = [
    { key: 'path', label: 'Folder', render: (row) => <code>{row.path}</code> },
    { key: 'raw_name', label: 'Current name', value: (row) => row.raw_name || '—' },
    { key: 'cleaned_name', label: 'Cleaned title', value: (row) => row.cleaned_name || '—' },
    {
      key: 'suggested_rename',
      label: 'Suggested name',
      value: (row) => row.suggested_rename || '—',
    },
    {
      key: 'rename_plan',
      label: 'Planned change',
      render: (row) =>
        row.rename_plan?.length
          ? row.rename_plan
              .map((item: RenamePlan) => `${item.from_path || ''} → ${item.to_path || ''}`)
              .join('; ')
          : 'No rename needed',
    },
  ]

  return (
    <section className="od-admin-panel od-library-doctor" aria-labelledby="od-library-doctor-title">
      <div className="od-admin-panel__toolbar">
        <div>
          <h2 id="od-library-doctor-title" className="od-admin-panel-title">
            Tidy folder names
          </h2>
          <p className="od-admin-lede">
            Preview cleaned titles first. Saving suggestions writes sidecars; renaming changes
            folder paths.
          </p>
        </div>
        <Button
          type="button"
          className="od-btn--secondary"
          aria-expanded={open}
          aria-controls="od-library-doctor-content"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Close folder name tools' : 'Open folder name tools'}
        </Button>
      </div>
      {open ? (
        <div id="od-library-doctor-content">
          <div className="od-library-doctor__fields">
            <label className="od-admin-field" htmlFor="od-library-doctor-roots">
              Folders to check <span className="od-admin-hint">(one path per line)</span>
              <textarea
                id="od-library-doctor-roots"
                className="od-admin-input od-library-doctor__roots"
                rows={4}
                value={roots}
                onChange={(event) => {
                  setRoots(event.target.value)
                  invalidatePreview()
                }}
                disabled={busy}
              />
            </label>
            <label className="od-admin-field" htmlFor="od-library-doctor-template">
              Rename pattern
              <input
                id="od-library-doctor-template"
                className="od-admin-input"
                value={template}
                onChange={(event) => {
                  setTemplate(event.target.value)
                  invalidatePreview()
                }}
                disabled={busy}
              />
              <span className="od-admin-hint">
                Use {'{title}'} and {'{year}'}, for example: {'{title} ({year})'}.
              </span>
            </label>
            <label className="od-admin-field" htmlFor="od-library-doctor-limit">
              Batch limit <span className="od-admin-hint">(optional)</span>
              <input
                id="od-library-doctor-limit"
                className="od-admin-input"
                type="number"
                min="1"
                step="1"
                value={limit}
                onChange={(event) => {
                  setLimit(event.target.value)
                  invalidatePreview()
                }}
                disabled={busy}
              />
            </label>
          </div>
          <div className="od-admin-panel__toolbar od-library-doctor__actions">
            <Button
              type="button"
              className="od-btn--accent"
              disabled={busy}
              onClick={() => void preview()}
            >
              {busy ? 'Working…' : 'Preview folder names'}
            </Button>
            <Button
              type="button"
              className="od-btn--secondary"
              disabled={busy || !rows?.length}
              onClick={() => void saveProposals()}
            >
              Save as suggestions
            </Button>
            <Button
              type="button"
              className="od-btn--danger"
              disabled={busy || !rows?.length}
              onClick={() => void applyRenames()}
            >
              Rename on disk
            </Button>
          </div>
          <PageStatus loading={busy} loadingMessage="Working…" error={error} />
          {status ? (
            <PageStatus announcement="status" className="od-library-doctor__status">
              {status}
            </PageStatus>
          ) : null}
          {rows ? (
            <DataTable
              rows={rows}
              getRowKey={(row) => row.path}
              caption="Folder name preview"
              scrollLabel="Folder name preview table"
              emptyMessage="No folders found under those roots."
              initialSort={{ key: 'path', dir: 'asc' }}
              dense
              columns={columns}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
