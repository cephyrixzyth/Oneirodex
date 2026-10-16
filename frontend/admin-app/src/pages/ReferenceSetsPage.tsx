import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button, DataTable, PageStatus, confirmAction, errorFromBody } from '@oneirodex/ui'
import { csrfHeaders, deleteJson, getJson, postJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'

const API = '/api/admin/reference-sets'
type Platform = { id: string; label: string }
type ReferenceSet = {
  id: number
  library_platform: string
  region: string
  source: string
  name: string
  entry_count: number
}
const BUCKETS = [
  {
    key: 'rename_candidates',
    title: 'Hash matches, name differs',
    cols: [
      ['file_name', 'File'],
      ['suggested_name', 'Set name'],
      ['matched_by', 'Matched by'],
    ],
  },
  {
    key: 'hash_mismatches',
    title: 'Name matches, hash differs',
    cols: [
      ['file_name', 'File'],
      ['entry_name', 'Set name'],
      ['file_crc', 'File CRC'],
      ['entry_crc', 'Set CRC'],
    ],
  },
  {
    key: 'clone_named',
    title: 'Clone-named files',
    cols: [
      ['file_name', 'File'],
      ['clone_of', 'Clone of'],
      ['parent_owned', 'Parent owned'],
    ],
  },
  {
    key: 'unknown',
    title: 'Not in the set',
    cols: [
      ['file_name', 'File'],
      ['name', 'Catalogue name'],
      ['hashed', 'Hashed'],
    ],
  },
] as const
type BucketKey = (typeof BUCKETS)[number]['key']
type RepairRow = Record<string, string | number | boolean | null>
type RepairReport = {
  dry_run: boolean
  counts: Record<BucketKey, number>
  owned_total: number
  verified: number
  unhashed_name_matches: number
} & Record<BucketKey, RepairRow[]>
export function ReferenceSetsPage() {
  const [sets, setSets] = useState<ReferenceSet[]>([])
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [catalogPlatforms, setCatalogPlatforms] = useState<Platform[]>([])
  const [regions, setRegions] = useState<string[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [maxBytes, setMaxBytes] = useState(32 * 1024 * 1024)
  const [platform, setPlatform] = useState('')
  const [region, setRegion] = useState('USA')
  const [source, setSource] = useState('nointro')
  const [file, setFile] = useState<File | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const [rehashPlatform, setRehashPlatform] = useState('')
  const [repairPlatform, setRepairPlatform] = useState('')
  const [repairRegion, setRepairRegion] = useState('')
  const [catalogPlatform, setCatalogPlatform] = useState('')
  const [report, setReport] = useState<RepairReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (cancelled) return
        if (
          !Array.isArray(data.sets) ||
          !Array.isArray(data.platforms) ||
          !Array.isArray(data.catalog_platforms) ||
          !Array.isArray(data.regions) ||
          !Array.isArray(data.sources)
        )
          throw new Error('Reference sets returned an invalid response.')
        setSets(data.sets)
        setPlatforms(data.platforms)
        setCatalogPlatforms(data.catalog_platforms)
        setRegions(data.regions)
        setSources(data.sources)
        setMaxBytes(data.max_dat_bytes)
        setPlatform((current) => current || data.platforms[0]?.id || '')
        setRehashPlatform((current) => current || data.platforms[0]?.id || '')
        setRepairPlatform((current) => current || data.platforms[0]?.id || '')
        setCatalogPlatform((current) => current || data.catalog_platforms[0]?.id || '')
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setLoadFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  async function action(work: () => Promise<void>) {
    if (loading || loadFailed || lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await work()
    } catch (err) {
      setError(errorText(err) || 'Could not complete the action.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  function upload(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    if (file.size > maxBytes) {
      setError('DAT must be at most 32 MiB.')
      return
    }
    void action(async () => {
      const existing = sets.find(
        (row) => row.library_platform === platform && row.region === region,
      )
      if (
        existing &&
        !(await confirmAction({
          title: 'Replace reference set?',
          body: `Replace ${existing.name} for ${platform}/${region}? Its current entries will be removed.`,
          confirmLabel: 'Replace set',
          cancelLabel: 'Keep current set',
        }))
      )
        return
      const body = new FormData()
      body.set('library_platform', platform)
      body.set('region', region)
      body.set('source', source)
      body.set('file', file)
      if (existing) body.set('replace', 'true')
      const response = await fetch(API, {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders(),
        body,
      })
      const data = await response.json()
      if (!response.ok || data.ok === false)
        throw errorFromBody(data, response.status, 'DAT upload')
      const row = data.reference_set as ReferenceSet
      if (!row || typeof row.id !== 'number')
        throw new Error('DAT upload returned an invalid response.')
      setSets((current) => [
        ...current.filter(
          (old) => old.library_platform !== row.library_platform || old.region !== row.region,
        ),
        row,
      ])
      setFile(null)
      if (fileInput.current) fileInput.current.value = ''
      setReport(null)
      setMessage(
        `Uploaded ${row.name}: ${row.entry_count} entries for ${row.library_platform}/${row.region}.`,
      )
    })
  }
  function remove(row: ReferenceSet) {
    void action(async () => {
      if (
        !(await confirmAction({
          title: 'Delete reference set?',
          body: `Remove ${row.name} for ${row.library_platform}/${row.region}? Library files are not deleted.`,
          confirmLabel: 'Delete set',
          cancelLabel: 'Keep set',
        }))
      )
        return
      await deleteJson(`${API}/${row.id}`)
      setSets((current) => current.filter((item) => item.id !== row.id))
      setReport(null)
      setMessage('Reference set deleted.')
    })
  }
  const disabled = loading || loadFailed || busy
  function platformSelect(
    label: string,
    value: string,
    change: (value: string) => void,
    options = platforms,
  ) {
    return (
      <label className="od-admin-field">
        {label}
        <select
          className="od-admin-input"
          aria-label={label}
          required
          value={value}
          disabled={disabled}
          onChange={(event) => change(event.target.value)}
        >
          {options.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label} ({row.id})
            </option>
          ))}
        </select>
      </label>
    )
  }
  return (
    <Page
      title="ROM reference sets"
      lede="Upload your own DAT files to compare your library with reference titles and hashes."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading reference sets…"
        error={error || null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>
          Retry loading reference sets
        </Button>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {!loading ? (
        <>
          <form className="od-admin-panel" onSubmit={upload}>
            <fieldset className="od-admin-fieldset" disabled={disabled}>
              <legend>Upload or replace a DAT</legend>
              {platformSelect('Library platform', platform, setPlatform)}
              <label className="od-admin-field">
                Region
                <select
                  className="od-admin-input"
                  aria-label="Upload region"
                  value={region}
                  onChange={(event) => setRegion(event.target.value)}
                >
                  {regions.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label className="od-admin-field">
                Source
                <select
                  className="od-admin-input"
                  aria-label="DAT source"
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                >
                  {sources.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label className="od-admin-field">
                DAT file
                <input
                  ref={fileInput}
                  className="od-admin-input"
                  type="file"
                  required
                  accept=".dat,.xml,text/xml,application/xml"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
              </label>
              <p className="od-admin-hint">
                Maximum 32 MiB. Uploading for an installed platform and region replaces its entries
                after confirmation.
              </p>
            </fieldset>
            <Button type="submit" variant="primary" disabled={disabled || !file || !platform}>
              Upload / replace
            </Button>
          </form>
          <section className="od-admin-panel">
            <h2>Rehash library ROMs</h2>
            <p className="od-admin-hint">
              Compute CRC, MD5 and SHA1 for matching. This reads library files and can take time.
            </p>
            {platformSelect('Rehash platform selection', rehashPlatform, setRehashPlatform)}
            <Button
              disabled={disabled || !rehashPlatform}
              onClick={() =>
                void action(async () => {
                  const result = await postJson('/api/reference-sets/rehash', {
                    library_platform: rehashPlatform,
                  })
                  setReport(null)
                  setMessage(
                    `Hashed ${result.hashed} / ${result.considered} (skipped ${result.skipped}).`,
                  )
                })
              }
            >
              Rehash platform
            </Button>
          </section>
          <section className="od-admin-panel">
            <h2>DAT repair preview</h2>
            <p className="od-admin-hint">
              Compare names and hashes with the installed set. This is a dry run: nothing is
              renamed, moved or marked. Rehash first to populate hash comparisons.
            </p>
            {platformSelect('Repair platform', repairPlatform, (value) => {
              setRepairPlatform(value)
              setReport(null)
            })}
            <label className="od-admin-field">
              Repair region
              <select
                className="od-admin-input"
                aria-label="Repair region"
                disabled={disabled}
                value={repairRegion}
                onChange={(event) => {
                  setRepairRegion(event.target.value)
                  setReport(null)
                }}
              >
                <option value="">All regions</option>
                {regions.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <Button
              disabled={disabled || !repairPlatform}
              onClick={() =>
                void action(async () => {
                  setReport(null)
                  const result = await postJson('/api/reference-sets/repair-preview', {
                    library_platform: repairPlatform,
                    ...(repairRegion ? { region: repairRegion } : {}),
                  })
                  if (!result.dry_run || !result.counts)
                    throw new Error('Repair preview returned an invalid response.')
                  setReport(result as RepairReport)
                  setMessage(
                    `${result.owned_total} owned · ${result.verified} verified by hash and name · ${result.unhashed_name_matches} name-only (not hashed yet) · dry run, nothing changed.`,
                  )
                })
              }
            >
              Preview repairs
            </Button>
            {report ? (
              <div>
                {BUCKETS.map((bucket) => (
                  <section key={bucket.key}>
                    <h3>
                      {bucket.title} · {report.counts[bucket.key] || 0}
                    </h3>
                    <DataTable
                      caption={bucket.title}
                      scrollLabel={`${bucket.title} table`}
                      rows={report[bucket.key] || []}
                      getRowKey={(row, index) => `${row.game_uuid || ''}-${index}`}
                      emptyMessage="None."
                      columns={bucket.cols.map(([key, label]) => ({
                        key,
                        label,
                        render: (row) =>
                          typeof row[key] === 'boolean'
                            ? row[key]
                              ? 'yes'
                              : 'no'
                            : (row[key] ?? ''),
                      }))}
                    />
                    {(report[bucket.key]?.length || 0) < (report.counts[bucket.key] || 0) ? (
                      <p className="od-admin-hint">
                        Showing the first {report[bucket.key]?.length || 0} of{' '}
                        {report.counts[bucket.key]}.
                      </p>
                    ) : null}
                  </section>
                ))}
              </div>
            ) : null}
          </section>
          <section className="od-admin-panel">
            <h2>Licensed catalog</h2>
            <p className="od-admin-hint">
              Refresh one platform from IGDB regional release dates. This contacts IGDB; an empty
              cache means it has not been fetched. Native PC libraries are excluded.
            </p>
            {platformSelect(
              'Catalog platform',
              catalogPlatform,
              setCatalogPlatform,
              catalogPlatforms,
            )}
            <Button
              disabled={disabled || !catalogPlatform}
              onClick={() =>
                void action(async () => {
                  setMessage('Refreshing from IGDB…')
                  const result = await postJson('/api/licensed-catalog/refresh', {
                    library_platform: catalogPlatform,
                  })
                  setMessage(
                    `Cached ${result.unique_titles} titles (${result.cached_rows} region rows, ${result.pages} pages).`,
                  )
                })
              }
            >
              Refresh catalog
            </Button>
          </section>
          <section className="od-admin-panel">
            <h2>Installed sets ({sets.length})</h2>
            <DataTable
              caption="Installed ROM reference sets"
              scrollLabel="Installed reference sets table"
              rows={sets}
              getRowKey={(row) => row.id}
              emptyMessage="No reference sets yet."
              columns={[
                { key: 'library_platform', label: 'Platform' },
                { key: 'region', label: 'Region' },
                { key: 'source', label: 'Source' },
                { key: 'entry_count', label: 'Entries' },
                { key: 'name', label: 'Name' },
                {
                  key: 'actions',
                  label: 'Actions',
                  render: (row) => (
                    <Button
                      variant="danger"
                      disabled={disabled}
                      aria-label={`Delete ${row.name} (${row.library_platform}/${row.region})`}
                      onClick={() => remove(row)}
                    >
                      Delete
                    </Button>
                  ),
                },
              ]}
            />
          </section>
          <a href="/admin/integrations">Back to Integrations</a>
        </>
      ) : null}
    </Page>
  )
}
