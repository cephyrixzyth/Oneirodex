import { formatEndsAt, storeLabel, truncate } from './newsHelpers'
import type { FeaturedNews } from './newsTypes'
import { formatLocaleDate } from '../../utils/formatLocaleDate'
import { safeHttpUrl } from '../../utils/safeUrl'

/** The lead story: an admin note, else the first headline, else the first free game. */
export function NewsFeaturedHero({
  activeTab,
  error,
  featured,
  loading,
}: {
  activeTab: string
  error: unknown
  featured: FeaturedNews | null
  loading: boolean
}) {
  return (
    <>
      {!error && !loading && featured && (activeTab === 'all' || activeTab === 'admins') ? (
        <section className="od-news__hero od-panels__full" aria-label="Featured">
          <p className="od-news__hero-kicker">
            {featured.kind === 'admin'
              ? 'From your admins'
              : featured.kind === 'free'
                ? 'Free now'
                : 'Headline'}
          </p>
          {featured.kind === 'headline' && safeHttpUrl(featured.item.url) ? (
            <a
              className="od-news__hero-link"
              href={safeHttpUrl(featured.item.url) || undefined}
              target="_blank"
              rel="noreferrer"
            >
              <h2 className="od-news__hero-title">{featured.item.title}</h2>
            </a>
          ) : (
            <h2 className="od-news__hero-title">{featured.item.title}</h2>
          )}
          {featured.kind === 'admin' && featured.item.body ? (
            <p className="od-news__hero-body">{truncate(featured.item.body, 280)}</p>
          ) : null}
          {featured.kind === 'headline' && featured.item.summary ? (
            <p className="od-news__hero-body">{truncate(featured.item.summary, 220)}</p>
          ) : null}
          {featured.kind === 'free' && featured.item.description ? (
            <p className="od-news__hero-body">{truncate(featured.item.description, 180)}</p>
          ) : null}
          <p className="od-news__hero-meta">
            {featured.kind === 'admin' && featured.item.created_at ? (
              <time dateTime={featured.item.created_at}>
                {formatLocaleDate(featured.item.created_at)}
              </time>
            ) : null}
            {featured.kind === 'headline' ? (
              <>
                <span>{featured.item.source}</span>
                {featured.item.published_at ? (
                  <time dateTime={featured.item.published_at}>
                    {formatLocaleDate(featured.item.published_at)}
                  </time>
                ) : null}
              </>
            ) : null}
            {featured.kind === 'free' ? (
              <>
                <span className="od-news__store">{storeLabel(featured.item.store)}</span>
                {featured.item.ends_at ? (
                  <time dateTime={featured.item.ends_at}>
                    Ends {formatEndsAt(featured.item.ends_at)}
                  </time>
                ) : null}
              </>
            ) : null}
          </p>
        </section>
      ) : null}
    </>
  )
}
