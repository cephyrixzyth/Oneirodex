import type { DetailsGame, ExtrasModel, VersionActions } from './detailsTypes'
import { queueClientCommand } from '../../api/clientCommands'
import { seatCanUseCompanion } from '../../utils/seatMode'
import { formatVersionSize, isVersionPathMissing } from '../../utils/detailsMedia'
import { showToast } from '../../utils/toast'
import { Button } from '@oneirodex/ui'

/** Extras & DLC rows, built from `extrasPanelModel`. */
export function DetailsExtrasSection({
  game,
  extrasModel,
  busyVersionKey,
  setBusyVersionKey,
  setVersionActionStatus,
  handleVersionDownload,
  canDownload = true,
}: {
  game: DetailsGame
  extrasModel: ExtrasModel
  canDownload?: boolean
} & Pick<
  VersionActions,
  'busyVersionKey' | 'setBusyVersionKey' | 'setVersionActionStatus' | 'handleVersionDownload'
>) {
  const childActionDescriptionId = `extras-child-restriction-${game.uuid}`
  return (
    <section className="od-details-page__section" id="extras">
      <h2>Extras &amp; DLC</h2>
      {!canDownload ? (
        <p className="visually-hidden" id={childActionDescriptionId} role="note">
          Downloads and companion install actions are unavailable for child accounts.
        </p>
      ) : null}
      {extrasModel.loading ? (
        <p className="od-details-page__muted">Loading extras…</p>
      ) : extrasModel.rows.length === 0 ? (
        <p className="od-details-page__muted">No extras or DLC listed for this title yet.</p>
      ) : (
        <ul className="od-details-page__versions">
          {extrasModel.rows.map((row: any) => {
            const versionKey = `extra:${row.uuid || row.id}`
            const applyBusy = busyVersionKey === versionKey
            const onServer =
              row.on_server === true
                ? 'On server'
                : row.on_server === false
                  ? 'Not on server'
                  : null
            const sizeLabel = formatVersionSize(row.size)
            const pathMissing = row.path_missing === true || isVersionPathMissing(row)
            const hasDownload = Boolean(row.download_url && !pathMissing)
            const canApplyWithCompanion = Boolean(
              seatCanUseCompanion() && game.client_connected && row.uuid && hasDownload,
            )
            return (
              <li key={row.id || row.uuid || row.label}>
                <div className="od-details-page__version-row">
                  <div className="od-details-page__version-meta">
                    <strong>{row.label}</strong>
                    <span className="od-details-page__muted">
                      {' '}
                      · {row.kind}
                      {row.kind === 'disc' && row.disc_index != null ? ` ${row.disc_index}` : ''}
                      {sizeLabel ? ` · ${sizeLabel}` : ''}
                      {onServer ? ` · ${onServer}` : ''}
                    </span>
                    {pathMissing ? (
                      <span className="od-details-page__muted od-details-page__version-missing">
                        {' '}
                        · Missing on disk
                      </span>
                    ) : null}
                  </div>
                  <div className="od-details-page__version-actions">
                    {hasDownload ? (
                      <Button
                        type="button"
                        disabled={!canDownload || Boolean(busyVersionKey)}
                        title={!canDownload ? 'Downloads are unavailable for child accounts' : undefined}
                        aria-describedby={!canDownload ? childActionDescriptionId : undefined}
                        onClick={() => {
                          if (!canDownload) return
                          void handleVersionDownload({
                            kind: 'extra',
                            versionUuid: row.uuid,
                            label: row.label,
                          })
                        }}
                      >
                        {busyVersionKey === `download:extra:${row.uuid || 'base'}`
                          ? 'Queuing…'
                          : 'Download'}
                      </Button>
                    ) : null}
                    {canApplyWithCompanion ? (
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
                            kind: 'extra',
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
      )}
    </section>
  )
}
