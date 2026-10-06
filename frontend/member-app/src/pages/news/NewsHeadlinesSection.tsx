import { truncate } from './newsHelpers'
import type { NewsItem } from './newsTypes'
import { formatLocaleDate } from '../../utils/formatLocaleDate'
import { safeHttpUrl } from '../../utils/safeUrl'

/** Headlines with the per-source mute chips. */
export function NewsHeadlinesSection({
  error,
  headlineItems,
  headlines,
  layout,
  mutedSources,
  showHeadlines,
  sources,
  toggleSource,
  visibleHeadlines,
}: {
  error: unknown
  headlineItems: NewsItem[]
  headlines: NewsItem[] | null
  layout: string
  mutedSources: Set<string>
  showHeadlines: boolean
  sources: string[]
  toggleSource: (source: string) => void
  visibleHeadlines: NewsItem[]
}) {
  return (
    <>
      {!error && headlines && showHeadlines ? (
        <section
          className="od-news__section od-news__headlines"
          aria-labelledby="news-headlines-heading"
        >
          <div className="od-news__section-head">
            <h2 id="news-headlines-heading">Gaming headlines</h2>
            <span className="od-news__count">{visibleHeadlines.length}</span>
          </div>

          {/* Pick your sites. Every configured source is listed whether or not
          it has an article today — filtering by what happened to arrive
          would hide a quiet site behind its own silence. */}
          {sources.length > 0 ? (
            <div className="od-news__sources" role="group" aria-label="Headline sources">
              {sources.map((source) => {
                const on = !mutedSources.has(source)
                return (
                  <button
                    key={source}
                    type="button"
                    className="od-cbtn od-news__source"
                    aria-pressed={on}
                    onClick={() => toggleSource(source)}
                    title={on ? `Hide ${source}` : `Show ${source}`}
                  >
                    {source}
                  </button>
                )
              })}
            </div>
          ) : null}

          {visibleHeadlines.length === 0 ? (
            <p className="od-news__empty">
              {mutedSources.size > 0 && headlines.length > 0
                ? 'Every source is switched off — turn one back on above.'
                : 'No external headlines available right now.'}
            </p>
          ) : layout === 'rss' ? (
            <div className="od-news__panel-body">
              <ul className="od-news__magazine">
                {headlineItems.map((item: any) => (
                  <li key={item.url} className="od-news__mag-row">
                    <article>
                      <a
                        className="od-news__mag-link"
                        href={safeHttpUrl(item.url) || '/news'}
                        target="_blank"
                        rel="noreferrer"
                      >
                        <strong>{item.title}</strong>
                      </a>
                      {item.summary ? <p>{truncate(item.summary, 180)}</p> : null}
                      <p className="od-news__meta">
                        <span className="od-news__source">{item.source}</span>
                        {item.published_at ? (
                          <time dateTime={item.published_at}>
                            {formatLocaleDate(item.published_at)}
                          </time>
                        ) : null}
                      </p>
                    </article>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            /* Image-forward cards (UX-C14) — the way Steam/Epic present news.
           Feeds that carry no artwork fall back to a text card rather than
           a broken frame. Grid mode keeps this markup and densifies in CSS. */
            <div className="od-news__panel-body">
              <ul className="od-news__cards">
                {headlineItems.map((item: any) => (
                  <li key={item.url} className="od-news__card">
                    <a
                      className="od-news__card-link"
                      href={safeHttpUrl(item.url) || '/news'}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <span className="od-news__card-art-wrap">
                        {item.image_url ? (
                          <img
                            className="od-news__card-art"
                            src={item.image_url}
                            alt=""
                            loading="lazy"
                            onError={(event) => {
                              event.currentTarget.classList.add('is-broken')
                            }}
                          />
                        ) : (
                          <span
                            className="od-news__card-art od-news__card-art--empty"
                            aria-hidden="true"
                          />
                        )}
                        {item.source ? (
                          <span className="od-news__card-badge">{item.source}</span>
                        ) : null}
                        {item.published_at ? (
                          <time className="od-news__card-when" dateTime={item.published_at}>
                            {formatLocaleDate(item.published_at, {
                              compact: true,
                              fallback: null,
                            })}
                          </time>
                        ) : null}
                      </span>
                      <span className="od-news__card-body">
                        <strong className="od-news__card-title">{item.title}</strong>
                        {item.summary ? (
                          <span className="od-news__card-summary">
                            {truncate(item.summary, 140)}
                          </span>
                        ) : null}
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      ) : null}
    </>
  )
}
