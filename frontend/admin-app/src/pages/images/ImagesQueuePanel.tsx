import {
  BEST_AVAILABLE_POLICY,
  IMAGE_KIND_OPTIONS,
  queueFailureText,
  type ImageGroup,
  type ImageRow,
  type LibraryOption,
  type Option,
} from './imagesModel'
import { QueueRow } from './QueueRow'
import { DataTable } from '../../components/DataTable'
import { Button, PageStatus } from '@oneirodex/ui'

/** The mass image queue: filters, bulk actions, the grouped or flat row list. */
export function ImagesQueuePanel({
  autoPick,
  downloadBatch,
  downloadOne,
  gameUuid,
  generateArtwork,
  groupToggle,
  groups,
  images,
  libraries,
  libraryFilter,
  loadQueue,
  loadingQueue,
  massSearch,
  pathStatus,
  platformFilter,
  platforms,
  queueBusy,
  queueError,
  queueMsg,
  removeOne,
  retryFailed,
  serviceFilter,
  serviceOptions,
  setGroupToggle,
  setLibraryFilter,
  setPlatformFilter,
  setServiceFilter,
  setStatusFilter,
  setTypeFilter,
  statusFilter,
  syncGameParam,
  typeFilter,
}: {
  autoPick: () => Promise<void>
  downloadBatch: (size: number) => Promise<void>
  downloadOne: (imageId: string) => Promise<void>
  gameUuid: string
  generateArtwork: () => Promise<void>
  groupToggle: boolean
  groups: ImageGroup[] | null
  images: ImageRow[]
  libraries: LibraryOption[]
  libraryFilter: string
  loadQueue: () => Promise<void>
  loadingQueue: boolean
  massSearch: () => Promise<void>
  pathStatus: { error?: string; path?: string } | null
  platformFilter: string
  platforms: Option[]
  queueBusy: string
  queueError: string
  queueMsg: string
  removeOne: (imageId: string) => Promise<void>
  retryFailed: () => Promise<void>
  serviceFilter: string
  serviceOptions: Option[]
  setGroupToggle: (value: boolean) => void
  setLibraryFilter: (value: string) => void
  setPlatformFilter: (value: string) => void
  setServiceFilter: (value: string) => void
  setStatusFilter: (value: string) => void
  setTypeFilter: (value: string) => void
  statusFilter: string
  syncGameParam: (uuid: string, name: string) => void
  typeFilter: string
}) {
  const queueCounts = images.reduce(
    (counts, image) => {
      const state = image.status || (image.is_downloaded ? 'downloaded' : 'pending')
      if (state === 'failed') counts.failed += 1
      else if (state === 'downloaded') counts.downloaded += 1
      else counts.pending += 1
      return counts
    },
    { pending: 0, failed: 0, downloaded: 0 },
  )

  return (
    <section className="od-admin-panel od-admin-panel--stacked">
      <header className="od-image-queue-head">
        <div>
          <h2 className="od-admin-panel-title">Image queue</h2>
          <p className="od-admin-lede">
            Review downloads and run artwork actions for the selected scope.
          </p>
        </div>
        <Button type="button" variant="ghost" disabled={Boolean(queueBusy)} onClick={loadQueue}>
          Refresh queue
        </Button>
      </header>

      {pathStatus?.error ? (
        <PageStatus
          error={pathStatus.error}
          errorMessage={
            pathStatus.path
              ? `IMAGE_SAVE_PATH: ${pathStatus.error} (${pathStatus.path})`
              : `IMAGE_SAVE_PATH: ${pathStatus.error}`
          }
        />
      ) : null}
      <PageStatus error={queueError} />
      {queueMsg ? (
        <p className="od-admin-lede" aria-live="polite">
          {queueMsg}
        </p>
      ) : null}

      <div className="od-image-queue-stats" aria-label="Visible queue totals">
        <div>
          <strong>{queueCounts.pending}</strong>
          <span>Pending</span>
        </div>
        <div className="is-warning">
          <strong>{queueCounts.failed}</strong>
          <span>Failed</span>
        </div>
        <div className="is-success">
          <strong>{queueCounts.downloaded}</strong>
          <span>Downloaded</span>
        </div>
      </div>

      <details className="od-image-queue-filters">
        <summary>
          Filters{' '}
          <span>
            {statusFilter} · {typeFilter}
          </span>
        </summary>
        <div className="od-images-filters">
          <label>
            Status
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">All</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="downloaded">Downloaded</option>
            </select>
          </label>
          <label>
            Type
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">All</option>
              {IMAGE_KIND_OPTIONS.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Library (auto-pick / missing)
            <select value={libraryFilter} onChange={(e) => setLibraryFilter(e.target.value)}>
              <option value="">All libraries</option>
              {libraries.map((lib) => (
                <option key={lib.uuid} value={lib.uuid}>
                  {lib.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Platform (auto-pick)
            <select
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value)}
              aria-label="Platform filter for mass auto-pick"
            >
              <option value="">All platforms</option>
              {platforms.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Service (auto-pick / search)
            <select
              value={serviceFilter}
              onChange={(e) => setServiceFilter(e.target.value)}
              aria-label="Service filter for mass cover tools"
            >
              <option value="">All services</option>
              {serviceOptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="od-images-filters__check">
            <input
              type="checkbox"
              checked={groupToggle}
              onChange={(e) => setGroupToggle(e.target.checked)}
            />
            Group by game
          </label>
        </div>
      </details>

      <div className="od-image-queue-actions">
        <div>
          <h3>Queue actions</h3>
          <p>Download or retry items already in the queue.</p>
          <Button type="button" disabled={Boolean(queueBusy)} onClick={() => downloadBatch(10)}>
            Download 10
          </Button>
          <Button type="button" disabled={Boolean(queueBusy)} onClick={() => downloadBatch(50)}>
            Download 50
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={Boolean(queueBusy)}
            onClick={retryFailed}
          >
            Retry failed
          </Button>
        </div>
        <div>
          <h3>Find missing artwork</h3>
          <p>Uses the selected library, platform, and service scope.</p>
          <Button
            type="button"
            disabled={Boolean(queueBusy)}
            onClick={massSearch}
            title="POST /admin/api/covers/batch/search"
          >
            {queueBusy === 'mass-search' ? 'Searching…' : 'Mass cover search'}
          </Button>
          <Button
            type="button"
            disabled={Boolean(queueBusy)}
            onClick={autoPick}
            title={`POST /admin/api/covers/batch/apply policy=${BEST_AVAILABLE_POLICY}`}
          >
            {queueBusy === 'autopick' ? 'Auto-picking…' : 'Auto-pick best available'}
          </Button>
          <Button
            type="button"
            disabled={Boolean(queueBusy) || !gameUuid}
            onClick={generateArtwork}
            title={
              gameUuid
                ? 'POST /admin/api/artwork/generate — needs ENABLE_AI_ARTWORK + AI_ARTWORK_URL'
                : 'Select a title above first'
            }
          >
            {queueBusy === 'generate' ? 'Generating…' : 'Generate artwork'}
          </Button>
        </div>
      </div>

      {loadingQueue ? (
        <PageStatus loading inline loadingMessage="Loading queue…" />
      ) : images.length === 0 ? (
        <p className="od-admin-lede">No images match these filters.</p>
      ) : groups ? (
        <div className="od-images-groups">
          {groups.map((group) => {
            const failed = group.items.filter((i) => i.status === 'failed').length
            const pending = group.items.filter((i) => i.status === 'pending').length
            return (
              <div key={group.uuid || group.name} className="od-images-group">
                <div className="od-images-group__head">
                  <div>
                    <strong>{group.name}</strong> <code className="od-mono">{group.uuid}</code>
                    {failed ? (
                      <span className="od-badge od-badge--danger">{failed} failed</span>
                    ) : null}
                    {pending ? (
                      <span className="od-badge od-badge--warn">{pending} pending</span>
                    ) : null}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => syncGameParam(group.uuid, group.name)}
                  >
                    Open picker
                  </Button>
                </div>
                <ul className="od-images-group__list">
                  {group.items.map((image) => (
                    <QueueRow
                      key={image.id}
                      image={image}
                      busy={queueBusy}
                      onDownload={downloadOne}
                      onDelete={removeOne}
                    />
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      ) : (
        /* Flat mode is a real table (UX-C7): sortable + filterable like the
           other admin pages, instead of an unsorted list you scroll. */
        <DataTable
          columns={[
            {
              key: 'thumb',
              label: '',
              sortable: false,
              filterable: false,
              render: (image) =>
                image.local_url ? (
                  <img
                    src={image.local_url}
                    alt=""
                    className="od-images-row__thumb"
                    loading="lazy"
                  />
                ) : (
                  <span
                    className="od-images-row__thumb od-images-row__thumb--empty"
                    aria-hidden="true"
                  />
                ),
            },
            { key: 'game_name', label: 'Game' },
            { key: 'image_type', label: 'Kind' },
            {
              key: 'status',
              label: 'Status',
              value: (image) => image.status || (image.is_downloaded ? 'downloaded' : 'pending'),
            },
            {
              key: 'failure',
              label: 'Detail',
              value: (image) =>
                queueFailureText(image) || (image.file_missing ? 'file missing' : ''),
            },
            {
              key: 'actions',
              label: '',
              sortable: false,
              filterable: false,
              render: (image) => {
                const status = image.status || (image.is_downloaded ? 'downloaded' : 'pending')
                return (
                  <span className="od-images-row__actions">
                    {status === 'pending' || status === 'failed' || image.file_missing ? (
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={Boolean(queueBusy)}
                        onClick={() => downloadOne(image.id)}
                      >
                        {status === 'failed' || image.file_missing ? 'Retry' : 'Download'}
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={Boolean(queueBusy)}
                      onClick={() => removeOne(image.id)}
                    >
                      Delete
                    </Button>
                  </span>
                )
              },
            },
          ]}
          rows={images}
          getRowKey={(image) => image.id}
          emptyMessage="No images match these filters."
          dense
        />
      )}
    </section>
  )
}
