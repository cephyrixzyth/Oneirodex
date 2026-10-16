import type { GameHit, ImageRow } from './imagesModel'
import { ArtworkPicker } from '../../components/ArtworkPicker'
import { Button } from '@oneirodex/ui'

/** Pick one title by search and manage its images. */
export function ImagesSingleTitlePanel({
  gameHits,
  gameName,
  gameQuery,
  gameUuid,
  loadMissing,
  loadQueue,
  searchGames,
  setGameHits,
  setGameQuery,
  syncGameParam,
}: {
  gameHits: GameHit[]
  gameName: string
  gameQuery: string
  gameUuid: string
  loadMissing: () => Promise<void>
  loadQueue: () => Promise<void>
  searchGames: () => Promise<void>
  setGameHits: (hits: GameHit[]) => void
  setGameQuery: (value: string) => void
  syncGameParam: (uuid: string, name: string) => void
}) {
  return (
    <section className="od-admin-panel od-admin-panel--stacked">
      <h2 className="od-admin-panel-title">Single title</h2>
      <div className="od-images-game-search">
        <label className="od-images-game-search__field">
          Find game in library
          <input
            type="search"
            value={gameQuery}
            onChange={(e) => setGameQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                searchGames()
              }
            }}
            placeholder="Type a title…"
          />
        </label>
        <Button onClick={searchGames}>Find</Button>
        {gameUuid ? <Button onClick={() => syncGameParam('', '')}>Clear target</Button> : null}
        {gameUuid ? (
          <a className="od-btn" href={`/edit_game_images/${encodeURIComponent(gameUuid)}`}>
            Edit all artwork
          </a>
        ) : null}
      </div>
      {gameHits.length ? (
        <ul className="od-images-game-hits">
          {gameHits.map((g) => (
            <li key={g.uuid}>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  syncGameParam(g.uuid, g.name || '')
                  setGameHits([])
                  setGameQuery(g.name || '')
                }}
              >
                {g.name}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <ArtworkPicker
        gameUuid={gameUuid}
        gameName={gameName}
        onApplied={() => {
          loadQueue()
          loadMissing()
        }}
      />
    </section>
  )
}
