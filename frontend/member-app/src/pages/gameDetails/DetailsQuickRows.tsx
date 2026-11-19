import { supportsWebRetroSaves } from '../../api/saves'
import type { DetailsGame } from './detailsTypes'
import { AddToCollection } from '../../components/AddToCollection'
import { ExternalStoreLinks } from '../../components/ExternalStoreLinks'
import { Button } from '@oneirodex/ui'
import { VrWayToPlayLine } from '../../components/VrWayToPlay'
import { VrProfileEditor } from '../../components/VrProfileEditor'

/** The three quick rows under the action bar: play/core, collections, freshness. */
export function DetailsQuickRows({
  game,
  playHref,
  selectedCore,
  setSelectedCore,
  firmwareBlocked,
  firmwareMessage,
  freshnessBusy,
  handleFreshnessCheck,
}: {
  game: DetailsGame
  playHref: string | null
  selectedCore: string
  setSelectedCore: (core: string) => void
  firmwareBlocked: boolean
  firmwareMessage: string | undefined
  freshnessBusy: boolean
  handleFreshnessCheck: () => Promise<void>
}) {
  return (
    <div className="od-details-page__quick">
      <div className="od-details-page__quick-row od-details-page__quick-row--seg">
        {playHref ? (
          <>
            {supportsWebRetroSaves(playHref) &&
            Array.isArray(game.emulator_cores) &&
            game.emulator_cores.length > 1 ? (
              <label className="od-details-page__core-picker">
                Core{' '}
                <select
                  value={selectedCore || game.emulator_core || game.emulator_cores[0]}
                  onChange={(event) => setSelectedCore(event.target.value)}
                >
                  {game.emulator_cores.map((core: any) => (
                    <option key={core} value={core}>
                      {core}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <a className="od-btn od-btn--primary" href={playHref}>
              Play in browser
            </a>
          </>
        ) : firmwareBlocked || game.play_blocker === 'unsupported_archive' ? (
          <Button
            type="button"
            variant="primary"
            disabled
            title={
              firmwareBlocked
                ? firmwareMessage
                : game.companion_hint ||
                  'This archive type cannot be extracted for browser play. Use .zip / .7z / .rar / ROM.gz or a raw ROM.'
            }
          >
            Play in browser
          </Button>
        ) : null}
        {/* Same control as the tile menu's, at the other place the "where
          does this go" decision gets made. */}
        <AddToCollection gameUuid={game.uuid} gameName={game.name} variant="inline" />
      </div>

      {/* Rider R3: how this plays in VR, when known; INSP-40: the record behind it. */}
      <VrWayToPlayLine vrCompat={game.vr_compat} profiles={game.vr_profiles} />
      {game.can_edit ? (
        <VrProfileEditor gameUuid={game.uuid} initial={game.vr_profiles || []} />
      ) : null}

      <div className="od-details-page__quick-row">
        <ExternalStoreLinks
          urls={game.urls}
          steamUrl={game.steam_url}
          igdbUrl={game.url_igdb || game.url}
        />
        {/* Launch Steam closes the "elsewhere" row.
            It used to lead the actions, right after Play in browser —
            two "start the game" buttons side by side, one of which only
            works if you own it on Steam and have the client installed.
            Grouped with the store links it reads as the last of the
            elsewhere actions, which is what it is. */}
        {game.steam_app_id ? (
          <a className="od-btn" href={`steam://run/${game.steam_app_id}`}>
            Launch Steam
          </a>
        ) : null}
      </div>

      <div className="od-details-page__quick-row od-details-page__quick-row--seg">
        <Button
          type="button"
          disabled={freshnessBusy}
          title="Re-read the store listing for a newer version, updates, or DLC"
          onClick={() => {
            void handleFreshnessCheck()
          }}
        >
          {/* "Check stores" read like a store-availability lookup; it
              actually re-reads the listing for updates/DLC. */}
          {freshnessBusy ? 'Checking…' : 'Check updates & DLC'}
        </Button>
      </div>
    </div>
  )
}
