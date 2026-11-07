import type { DetailsGame, VersionActions, VersionRow } from './detailsTypes'
import { queueClientCommand } from '../../api/clientCommands'
import { ThinSeatNote } from '../../components/ThinSeatNote'
import { seatCanUseCompanion } from '../../utils/seatMode'
import {
  formatVersionSize,
  isVersionDownloadable,
  isVersionPathMissing,
} from '../../utils/detailsMedia'
import { showToast } from '../../utils/toast'
import { Button } from '@oneirodex/ui'

/** Base game and updates: one row per version with download / open-path / remove-missing. */
export function DetailsVersionsSection({
  game,
  baseAndUpdates,
  hasMissingVersions,
  busyVersionKey,
  setBusyVersionKey,
  versionActionStatus,
  setVersionActionStatus,
  cleanupBusy,
  handleCleanupOrphans,
  handleVersionDownload,
  canDownload = true,
}: {
  game: DetailsGame
  baseAndUpdates: VersionRow[]
  hasMissingVersions: boolean
  canDownload?: boolean
} & VersionActions) {
  const childActionDescriptionId = `versions-child-restriction-${game.uuid}`
  return (
    <section className="od-details-page__section" id="updates">
      <div className="od-details-page__section-head">
        <h2>Versions</h2>
        {game.can_cleanup_versions ? (
          <Button
            type="button"
            pill
            disabled={cleanupBusy}
            onClick={() => void handleCleanupOrphans()}
            title={
              hasMissingVersions
                ? 'Remove version rows whose files are missing on disk'
                : 'Scan and remove orphaned version rows'
            }
          >
            {cleanupBusy ? 'Removing…' : 'Remove missing versions'}
          </Button>
        ) : null}
      </div>
      {versionActionStatus ? (
        <p className="od-details-page__muted" role="status">
          {versionActionStatus}
        </p>
      ) : null}
      {!canDownload ? (
        <p className="visually-hidden" id={childActionDescriptionId} role="note">
          Downloads and companion install actions are unavailable for child accounts.
        </p>
      ) : !seatCanUseCompanion() ? (
        <ThinSeatNote what="per-update download and apply" />
      ) : null}
      <ul className="od-details-page__versions">
        {baseAndUpdates.map((row) => {
          const versionKey = `${row.kind}:${row.uuid}`
          const downloadKey = `download:${row.kind}:${row.uuid || 'base'}`
          const companionSeat = seatCanUseCompanion()
          const rowHasDownload = isVersionDownloadable(row) && companionSeat
          const pathMissing = isVersionPathMissing(row)
          const sizeLabel = formatVersionSize(row.size)
          const applyBusy = busyVersionKey === versionKey
          const downloadBusy = busyVersionKey === downloadKey
          return (
            <li key={`${row.kind}-${row.id || row.uuid}`}>
              <div className="od-details-page__version-row">
                <div className="od-details-page__version-meta">
                  <strong>{row.label}</strong>
                  {row.is_default ? (
                    <span className="chip od-chip" title="Default download version">
                      Default
                    </span>
                  ) : null}
                  <span className="od-details-page__muted">
                    {' '}
                    · {row.kind}
                    {sizeLabel ? ` · ${sizeLabel}` : ''}
                  </span>
                  {pathMissing ? (
                    <span className="od-details-page__muted od-details-page__version-missing">
                      {' '}
                      · Missing on disk
                    </span>
                  ) : null}
                </div>
                <div className="od-details-page__version-actions">
                  {/* Updates get a Download; the base row does not.
                    Downloading the base game is what the action bar at
                    the top of the page is for, and it is the *primary*
                    action there — so this row was a second, quieter copy
                    of the page's loudest button, sitting under a heading
                    about versions. Per-update download stays, because
                    that is the one thing the action bar genuinely cannot
                    express: "I have the game, I only need patch 1.03". */}
                  {rowHasDownload && row.kind === 'update' ? (
                    <Button
                      type="button"
                      disabled={!canDownload || Boolean(busyVersionKey)}
                      title={!canDownload ? 'Downloads are unavailable for child accounts' : undefined}
                      aria-describedby={!canDownload ? childActionDescriptionId : undefined}
                      onClick={() => {
                        if (!canDownload) return
                        void handleVersionDownload({
                          kind: 'update',
                          versionUuid: row.uuid,
                          label: row.label ?? undefined,
                        })
                      }}
                    >
                      {downloadBusy ? 'Queuing…' : 'Download'}
                    </Button>
                  ) : null}
                  {companionSeat && Boolean(game.client_connected) && row.kind === 'update' && rowHasDownload ? (
                    <Button
                      type="button"
                      disabled={!canDownload || Boolean(busyVersionKey)}
                      title={!canDownload ? 'Companion actions are unavailable for child accounts' : undefined}
                      aria-describedby={!canDownload ? childActionDescriptionId : undefined}
                      onClick={() => {
                        if (!canDownload) return
                        setBusyVersionKey(versionKey)
                        setVersionActionStatus(null)
                        void queueClientCommand(game.uuid, 'update', {
                          kind: row.kind,
                          versionUuid: row.uuid,
                        })
                          .then(() => {
                            setVersionActionStatus(`${row.label} queued for companion`)
                            showToast(`${row.label} queued for companion`, 'success')
                          })
                          .catch((err: any) => {
                            setVersionActionStatus(err?.message || 'Failed to queue apply')
                            showToast(err?.message || 'Queue failed', 'error')
                          })
                          .finally(() => {
                            setBusyVersionKey(null)
                          })
                      }}
                    >
                      {applyBusy ? 'Queuing…' : 'Apply with companion'}
                    </Button>
                  ) : null}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
