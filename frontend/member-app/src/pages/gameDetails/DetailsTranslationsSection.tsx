import { queueClientCommand } from '../../api/clientCommands'
import { initiateGameDownload } from '../../api/downloads'
import { seatCanUseCompanion } from '../../utils/seatMode'
import { attachPatchCatalogGuide, searchPatchCatalog } from '../../api/patchCatalog'
import { showToast } from '../../utils/toast'
import { Button } from '@oneirodex/ui'
import { Link, useNavigate } from 'react-router-dom'

import { useState } from 'react'
import type { CatalogHit, DetailsGame, VersionActions } from './detailsTypes'

/** Translation patches on the row plus the patch-catalogue search and attach flow. */
export function DetailsTranslationsSection({
  game,
  busyVersionKey,
  setBusyVersionKey,
  setVersionActionStatus,
  setRetryCount,
}: {
  game: DetailsGame
  setRetryCount: (update: (n: number) => number) => void
} & Pick<VersionActions, 'busyVersionKey' | 'setBusyVersionKey' | 'setVersionActionStatus'>) {
  const [catalogHits, setCatalogHits] = useState<CatalogHit[]>([])
  const [catalogBusy, setCatalogBusy] = useState(false)
  const [catalogStatus, setCatalogStatus] = useState<string | null>(null)
  const navigate = useNavigate()

  async function downloadPatch(patch: any) {
    const versionKey = `patch:${patch.uuid}`
    setBusyVersionKey(versionKey)
    setVersionActionStatus(null)
    try {
      await initiateGameDownload(game.uuid, { kind: 'extra', versionUuid: patch.uuid })
      setVersionActionStatus(`${patch.label} added to Downloads`)
      showToast(`${patch.label} added to Downloads`, 'success')
      navigate('/downloads')
    } catch (error: any) {
      const message = error?.message || 'Unable to start this patch download.'
      setVersionActionStatus(message)
      showToast(message, 'error')
    } finally {
      setBusyVersionKey(null)
    }
  }

  return (
    <section className="od-details-page__section" id="translations">
      <h2>Translations &amp; patches</h2>
      <p className="od-details-page__muted">
        {game.needs_translation
          ? `This ROM may not match your preferred game language (${game.preferred_game_locale || 'en-US'}).`
          : 'Translation patches available for this title.'}{' '}
        Always keep a backup of the original ROM. See the in-app{' '}
        <Link to="/help#translations">Help → Translations</Link> guide or{' '}
        <code>docs/user/translation-patches.md</code>.
      </p>
      {Array.isArray(game.translation_patches) && game.translation_patches.length > 0 ? (
        <ul className="od-details-page__versions">
          {game.translation_patches.map((patch: any) => {
            const versionKey = `patch:${patch.uuid}`
            const applyBusy = busyVersionKey === versionKey
            // TC-3: a thin seat gets the Guide link, never a queue button.
            const canApplyPatch =
              seatCanUseCompanion() &&
              Boolean(game.client_connected) &&
              Boolean(game.rom_patch_apply_enabled)
            return (
              <li key={patch.uuid}>
                <div className="od-details-page__version-row">
                  <div>
                    <strong>{patch.label}</strong>
                    <span className="od-details-page__muted">
                      {' '}
                      · {(patch.patch_format || 'patch').toUpperCase()}
                      {patch.target_language ? ` · → ${patch.target_language}` : ''}
                    </span>
                  </div>
                  <div className="od-details-page__version-actions">
                    <Button
                      type="button"
                      disabled={Boolean(busyVersionKey)}
                      onClick={() => void downloadPatch(patch)}
                    >
                      {busyVersionKey === `patch:${patch.uuid}` ? 'Queuing…' : 'Download patch'}
                    </Button>
                    {patch.source_url ? (
                      <a
                        className="od-btn"
                        href={patch.source_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Guide
                      </a>
                    ) : null}
                    {canApplyPatch ? (
                      <Button
                        type="button"
                        disabled={Boolean(busyVersionKey)}
                        onClick={() => {
                          setBusyVersionKey(versionKey)
                          setVersionActionStatus(null)
                          void queueClientCommand(game.uuid, 'apply_patch', {
                            kind: 'extra',
                            versionUuid: patch.uuid,
                          })
                            .then(() => {
                              setVersionActionStatus(`${patch.label} queued for companion apply`)
                              showToast(`${patch.label} queued for companion apply`, 'success')
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
                    ) : (
                      <Link className="od-btn" to="/help#translations">
                        How to apply
                      </Link>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="od-details-page__muted">
          No patch files in extras yet. Ask a librarian to add a curated <code>.ips</code>/
          <code>.bps</code>/<code>.ups</code> under the game extras folder, or follow the how-to for
          applying a patch you already have.
        </p>
      )}
      {game.rom_ai_translate?.show_panel ? (
        <div className="od-details-page__ai-translate">
          <h3>Live translate (RetroArch AI)</h3>
          <p className="od-details-page__muted">
            {game.rom_ai_translate.note} Target language hint:{' '}
            <code>{game.rom_ai_translate.target_lang || 'en'}</code>
            {game.rom_ai_translate.service_url_hint
              ? ` · service ${game.rom_ai_translate.service_url_hint}`
              : ''}
            . Offline dump→rebuild is not available for this system yet.
          </p>
          <Link className="od-btn" to="/help#translations">
            Setup guide
          </Link>
        </div>
      ) : null}
      {game.is_admin && game.patch_catalog_enabled ? (
        <div className="od-details-page__catalog">
          <h3>Operator catalog</h3>
          <p className="od-details-page__muted">
            Search your local YAML/JSON patch guide catalog (metadata only - no third-party scrape).
          </p>
          <Button
            type="button"
            disabled={catalogBusy}
            onClick={() => {
              setCatalogBusy(true)
              setCatalogStatus(null)
              void searchPatchCatalog({ gameUuid: game.uuid })
                .then((data) => {
                  setCatalogHits(Array.isArray(data.hits) ? data.hits : [])
                  setCatalogStatus(
                    data.hits?.length ? `${data.hits.length} hit(s)` : 'No catalog matches',
                  )
                })
                .catch((err: any) => {
                  setCatalogHits([])
                  setCatalogStatus(err?.message || 'Catalog search failed')
                })
                .finally(() => {
                  setCatalogBusy(false)
                })
            }}
          >
            {catalogBusy ? 'Searching…' : 'Search catalog'}
          </Button>
          {catalogStatus ? (
            <p className="od-details-page__muted" role="status">
              {catalogStatus}
            </p>
          ) : null}
          {catalogHits.length > 0 ? (
            <ul className="od-details-page__versions">
              {catalogHits.map((hit) => (
                <li key={hit.id}>
                  <div className="od-details-page__version-row">
                    <div>
                      <strong>{hit.title}</strong>
                      <span className="od-details-page__muted">
                        {' '}
                        · {hit.provider}
                        {hit.patch_format ? ` · ${hit.patch_format}` : ''}
                        {hit.target_language ? ` · → ${hit.target_language}` : ''}
                      </span>
                      {hit.notes ? <p className="od-details-page__muted">{hit.notes}</p> : null}
                    </div>
                    <div className="od-details-page__version-actions">
                      {hit.source_url ? (
                        <a
                          className="od-btn"
                          href={hit.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open guide
                        </a>
                      ) : null}
                      <Button
                        type="button"
                        disabled={catalogBusy}
                        onClick={() => {
                          setCatalogBusy(true)
                          void attachPatchCatalogGuide({
                            game_uuid: game.uuid,
                            source_url: hit.source_url,
                            notes: hit.notes,
                            target_language: hit.target_language,
                            patch_format: hit.patch_format,
                          })
                            .then(() => {
                              setCatalogStatus('Guide attached to game')
                              showToast('Guide attached', 'success')
                              setRetryCount((n) => n + 1)
                            })
                            .catch((err: any) => {
                              setCatalogStatus(err?.message || 'Attach failed')
                            })
                            .finally(() => {
                              setCatalogBusy(false)
                            })
                        }}
                      >
                        Attach guide
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
