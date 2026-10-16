import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { deleteJson, getJson, postJson } from '../api/adminApi'
import { DataTable } from '../components/DataTable'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import './ScanFiltersPage.css'

type FilterKind = 'name' | 'dir' | 'regex'
type ScanFilter = { id: number; filter_pattern: string; kind: FilterKind; case_sensitive: string }
const API = '/api/admin/scan-filters'

const presets: Array<{ label: string; kind: FilterKind; pattern: string }> = [
  { label: 'Name · GOG', kind: 'name', pattern: 'GOG' },
  { label: 'Name · Open Source', kind: 'name', pattern: 'Open Source' },
  { label: 'Name · Public Domain', kind: 'name', pattern: 'Public Domain' },
  { label: 'Skip · _MyTools', kind: 'dir', pattern: '_MyTools' },
  { label: 'Skip · OpenVR*', kind: 'dir', pattern: 'OpenVR*' },
  { label: 'Skip · Tools*', kind: 'dir', pattern: 'Tools*' },
]

export function ScanFiltersPage() {
  const [rows, setRows] = useState<ScanFilter[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState(false)
  const [kind, setKind] = useState<FilterKind>('name')
  const [pattern, setPattern] = useState('')
  const [caseSensitive, setCaseSensitive] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError('')
    getJson(API)
      .then((data) => {
        if (!Array.isArray(data.filters))
          throw new Error('Scanning filters returned an invalid response.')
        if (!cancelled) setRows(data.filters)
      })
      .catch((error) => {
        if (!cancelled) setLoadError(errorText(error) || 'Unable to load scanning filters.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [revision])

  async function add(event: FormEvent) {
    event.preventDefault()
    if (busy || loading || loadError || !pattern.trim()) return
    setBusy(true)
    try {
      await postJson(API, {
        kind,
        pattern: pattern.trim(),
        case_sensitive: kind === 'name' && caseSensitive,
      })
      setPattern('')
      setCaseSensitive(false)
      setRevision((value) => value + 1)
      showToast('Scanning filter added.', 'success')
    } catch (error) {
      showToast(errorText(error) || 'Could not add scanning filter.', 'error')
    } finally {
      setBusy(false)
    }
  }

  async function remove(row: ScanFilter) {
    if (busy) return
    const confirmed = await confirmAction({
      title: 'Remove scanning filter?',
      body: `Remove ${row.filter_pattern} from scan filters?`,
      confirmLabel: 'Remove filter',
      cancelLabel: 'Keep filter',
    })
    if (!confirmed) return
    setBusy(true)
    try {
      await deleteJson(`${API}/${row.id}`)
      setRows((current) => current.filter((item) => item.id !== row.id))
      showToast('Scanning filter removed.', 'success')
    } catch (error) {
      showToast(errorText(error) || 'Could not remove scanning filter.', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page
      title="Game scanning filters"
      lede="Strip tags from game folder names or skip matching folders during scans."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading scanning filters…"
        error={loadError || null}
      />
      {loadError ? (
        <Button onClick={() => setRevision((value) => value + 1)}>Retry loading filters</Button>
      ) : null}
      <section
        className="od-admin-panel od-scan-filter-help"
        aria-labelledby="scan-filter-how-title"
      >
        <h2 id="scan-filter-how-title">How filters work</h2>
        <ul>
          <li>
            <strong>Name tag:</strong> plain text such as <code>GOG</code>; removes{' '}
            <code>-GOG</code> or <code>.GOG</code> from folder names, without hiding folders.
          </li>
          <li>
            <strong>Skip folder:</strong> case-insensitive <code>dir:</code> glob against folder
            basenames.
          </li>
          <li>
            <strong>Skip folder (regex):</strong> case-insensitive <code>re:</code> expression
            against folder basenames.
          </li>
          <li>
            Prefer prefix globs such as <code>dolphin*</code> and <code>GOD v*</code>. Skip filters
            add protection; configure a library for each game leaf.
          </li>
        </ul>
      </section>
      <section className="od-admin-panel" aria-labelledby="scan-filter-add-title">
        <h2 id="scan-filter-add-title">Add scanning filter</h2>
        <div className="od-scan-filter-presets" role="group" aria-label="Common filter presets">
          {presets.map((preset) => (
            <Button
              key={preset.label}
              size="sm"
              onClick={() => {
                setKind(preset.kind)
                setPattern(preset.pattern)
                setCaseSensitive(false)
              }}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <form className="od-scan-filter-form" onSubmit={add}>
          <label className="od-admin-field">
            Filter type
            <select
              className="od-admin-input"
              value={kind}
              onChange={(event) => setKind(event.target.value as FilterKind)}
              disabled={busy}
            >
              <option value="name">Name tag</option>
              <option value="dir">Skip folder glob</option>
              <option value="regex">Skip folder regex</option>
            </select>
          </label>
          <label className="od-admin-field">
            {kind === 'name'
              ? 'Tag to strip'
              : kind === 'dir'
                ? 'Folder glob'
                : 'Folder regular expression'}
            <input
              className="od-admin-input"
              value={pattern}
              onChange={(event) => setPattern(event.target.value)}
              maxLength={200}
              required
              disabled={busy}
              placeholder={
                kind === 'name'
                  ? 'e.g. GOG'
                  : kind === 'dir'
                    ? 'e.g. OpenVR*'
                    : String.raw`e.g. \[Demo\s+Build\]`
              }
            />
          </label>
          {kind === 'name' ? (
            <label className="od-scan-filter-check">
              <input
                type="checkbox"
                checked={caseSensitive}
                onChange={(event) => setCaseSensitive(event.target.checked)}
                disabled={busy}
              />{' '}
              Case sensitive
            </label>
          ) : null}
          <Button
            type="submit"
            variant="primary"
            disabled={busy || loading || Boolean(loadError) || !pattern.trim()}
          >
            {busy ? 'Working…' : 'Save filter'}
          </Button>
        </form>
      </section>
      <section className="od-admin-panel" aria-labelledby="scan-filter-existing-title">
        <h2 id="scan-filter-existing-title">Existing filters ({rows.length})</h2>
        {!loading && !loadError ? (
          <DataTable
            caption="Existing game scanning filters"
            scrollLabel="Scanning filters table"
            rows={rows}
            getRowKey={(row) => row.id}
            emptyMessage="No custom filters yet. Built-in skip-folder patterns still apply."
            initialSort={{ key: 'filter_pattern', dir: 'asc' }}
            columns={[
              {
                key: 'kind',
                label: 'Kind',
                value: (row) =>
                  row.kind === 'name'
                    ? 'Name tag'
                    : row.kind === 'dir'
                      ? 'Skip folder'
                      : 'Skip folder regex',
              },
              {
                key: 'filter_pattern',
                label: 'Pattern',
                render: (row) => <code>{row.filter_pattern}</code>,
              },
              {
                key: 'case_sensitive',
                label: 'Case sensitive',
                value: (row) =>
                  row.kind === 'name' ? (row.case_sensitive === 'yes' ? 'Yes' : 'No') : 'N/A',
              },
              {
                key: 'actions',
                label: 'Actions',
                sortable: false,
                filterable: false,
                render: (row) => (
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy}
                    aria-label={`Remove ${row.filter_pattern}`}
                    onClick={() => void remove(row)}
                  >
                    Remove
                  </Button>
                ),
              },
            ]}
          />
        ) : null}
      </section>
      <a className="od-cbtn" href="/scan_management?active_tab=scan_filters">
        Back to Scan management
      </a>
    </Page>
  )
}
