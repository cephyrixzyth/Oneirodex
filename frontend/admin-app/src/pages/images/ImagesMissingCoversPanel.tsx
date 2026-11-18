import type { MissingCoverGame } from './imagesModel'
import { Button, PageStatus } from '@oneirodex/ui'

/** Games with no usable cover, from the health check. */
export function ImagesMissingCoversPanel({
  missingCovers,
  missingError,
  syncGameParam,
}: {
  missingCovers: MissingCoverGame[]
  missingError: string
  syncGameParam: (uuid: string, name: string) => void
}) {
  return (
    <section className="od-admin-panel od-admin-panel--stacked">
      <h2 className="od-admin-panel-title">Missing covers (health)</h2>
      <p className="od-admin-lede">
        From <code>/api/health/library</code> worst list — open picker or generate placeholders in
        Art studio. Full “missing cover” filter on the download queue needs Backend.
      </p>
      <PageStatus error={missingError} />
      {!missingCovers.length && !missingError ? (
        <p className="od-admin-lede">No missing-cover titles in the health sample.</p>
      ) : (
        <ul className="od-images-missing">
          {missingCovers.map((g) => (
            <li key={g.uuid}>
              <Button
                type="button"
                variant="ghost"
                onClick={() => syncGameParam(g.uuid, g.name || '')}
              >
                {g.name}
              </Button>
              <span className="od-admin-lede">score {g.score}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
