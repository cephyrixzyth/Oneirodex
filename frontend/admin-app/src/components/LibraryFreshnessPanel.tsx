import { useEffect, useState } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from './DataTable'

type LibraryOption = { uuid?: string; name?: string }
type UpdatedRow = { uuid?: string; name?: string; status?: string }
type ErrorRow = { uuid?: string; name?: string; error?: string }

export function LibraryFreshnessPanel() {
  const [open, setOpen] = useState(false)
  const [libraries, setLibraries] = useState<LibraryOption[]>([])
  const [libraryUuid, setLibraryUuid] = useState('')
  const [limit, setLimit] = useState('25')
  const [onlyStale, setOnlyStale] = useState(true)
  const [updated, setUpdated] = useState<UpdatedRow[] | null>(null)
  const [errors, setErrors] = useState<ErrorRow[]>([])
  const [skipped, setSkipped] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState('')

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    getJson('/api/get_libraries', { signal: controller.signal })
      .then((result) => setLibraries(Array.isArray(result) ? result : []))
      .catch((err) => {
        if (!controller.signal.aborted) setError(err)
      })
    return () => controller.abort()
  }, [open])

  async function refresh(entireScope = false) {
    const batchSize = entireScope ? 500 : Number(limit)
    if (!Number.isInteger(batchSize) || batchSize < 1 || batchSize > 500) {
      setError(new Error('Batch size must be a whole number from 1 to 500.'))
      return
    }
    if (entireScope) {
      const scope = libraryUuid
        ? `library ${libraries.find((item) => item.uuid === libraryUuid)?.name || ''}`
        : 'all libraries'
      const confirmed = await confirmAction({
        title: `Refresh up to 500 games in ${scope}?`,
        body: 'This may take time and makes store freshness requests. Store APIs may rate-limit large batches.',
        confirmLabel: 'Start large refresh',
        tone: 'neutral',
      })
      if (!confirmed) return
    }
    setBusy(true)
    setError(null)
    setStatus('')
    setUpdated(null)
    setErrors([])
    setSkipped(0)
    try {
      const result = await postJson('/api/admin/freshness/refresh', {
        limit: batchSize,
        only_stale: onlyStale,
        ...(libraryUuid ? { library_uuid: libraryUuid } : {}),
        ...(entireScope ? { entire_library: true } : {}),
      })
      const changed = Array.isArray(result?.updated) ? result.updated : []
      const failures = Array.isArray(result?.errors) ? result.errors : []
      const skippedFresh = Number(result?.skipped_fresh) || 0
      setUpdated(changed)
      setErrors(failures)
      setSkipped(skippedFresh)
      setStatus(
        `Done: ${changed.length} updated, ${skippedFresh} skipped as fresh, ${failures.length} errors.`,
      )
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const updatedColumns: DataTableColumn[] = [
    { key: 'name', label: 'Game', value: (row) => row.name || 'Untitled' },
    { key: 'status', label: 'Freshness', value: (row) => row.status || 'Unknown' },
  ]
  const errorColumns: DataTableColumn[] = [
    { key: 'name', label: 'Game', value: (row) => row.name || 'Untitled' },
    { key: 'error', label: 'Error', value: (row) => row.error || 'Update failed' },
  ]

  return (
    <section
      className="od-admin-panel od-library-freshness"
      aria-labelledby="od-library-freshness-title"
    >
      <div className="od-admin-panel__toolbar">
        <div>
          <h2 id="od-library-freshness-title" className="od-admin-panel-title">
            Check for updates
          </h2>
          <p className="od-admin-lede">
            Check stored version hints against connected stores and refresh freshness badges.
          </p>
        </div>
        <Button
          type="button"
          className="od-btn--secondary"
          aria-expanded={open}
          aria-controls="od-library-freshness-content"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Close update checks' : 'Open update checks'}
        </Button>
      </div>
      {open ? (
        <div id="od-library-freshness-content">
          <p className="od-library-doctor__status" role="note">
            Store requests can be rate-limited. Start with a small batch; the 500-game action asks
            for confirmation.
          </p>
          <div className="od-library-freshness__fields">
            <label className="od-admin-field" htmlFor="od-library-freshness-library">
              Library <span className="od-admin-hint">(optional)</span>
              <select
                id="od-library-freshness-library"
                className="od-admin-input"
                value={libraryUuid}
                onChange={(event) => setLibraryUuid(event.target.value)}
                disabled={busy}
              >
                <option value="">All libraries</option>
                {libraries.map((library) => (
                  <option key={library.uuid} value={library.uuid}>
                    {library.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="od-admin-field" htmlFor="od-library-freshness-limit">
              Batch size
              <input
                id="od-library-freshness-limit"
                className="od-admin-input"
                type="number"
                min="1"
                max="500"
                step="1"
                value={limit}
                onChange={(event) => setLimit(event.target.value)}
                disabled={busy}
              />
              <span className="od-admin-hint">Maximum 500 games per request.</span>
            </label>
            <label className="od-admin-field od-admin-field--check">
              <input
                type="checkbox"
                checked={onlyStale}
                onChange={(event) => setOnlyStale(event.target.checked)}
                disabled={busy}
              />
              Skip games checked in the last 24 hours
            </label>
          </div>
          <div className="od-admin-panel__toolbar od-library-freshness__actions">
            <Button
              type="button"
              className="od-btn--accent"
              disabled={busy}
              onClick={() => void refresh()}
            >
              {busy ? 'Checking…' : 'Refresh batch'}
            </Button>
            <Button
              type="button"
              className="od-btn--secondary"
              disabled={busy}
              onClick={() => void refresh(true)}
            >
              Refresh up to 500 games
            </Button>
          </div>
          <PageStatus loading={busy} loadingMessage="Checking store freshness…" error={error} />
          {status ? (
            <PageStatus announcement="status" className="od-library-doctor__status">
              {status}
            </PageStatus>
          ) : null}
          {updated ? (
            <DataTable
              rows={updated}
              getRowKey={(row) => row.uuid || `${row.name}-${row.status}`}
              caption="Freshness checks completed"
              scrollLabel="Freshness results table"
              emptyMessage="No games were updated in this batch."
              dense
              columns={updatedColumns}
            />
          ) : null}
          {errors.length ? (
            <DataTable
              rows={errors}
              getRowKey={(row) => row.uuid || `${row.name}-${row.error}`}
              caption="Freshness check errors"
              scrollLabel="Freshness errors table"
              dense
              columns={errorColumns}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
