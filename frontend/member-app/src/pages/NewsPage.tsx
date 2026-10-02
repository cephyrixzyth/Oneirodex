import { useEffect, useMemo, useState } from 'react'
import { fetchAnnouncements } from '../api/announcements'
import { claimFreeGameAssist, fetchFreeGames } from '../api/freeGames'
import { fetchGamingNews } from '../api/gamingNews'
import { ContextBar } from '../chrome/ContextBar'
import { formatLocaleDate } from '../utils/formatLocaleDate'
import { safeClaimUrl } from '../utils/safeUrl'
import { PageStatus } from '../components/PageStatus'
import './NewsPage.css'
import { useShellConfig } from '@oneirodex/ui'
import {
  MUTED_SOURCES_KEY,
  NEWS_LAYOUTS,
  NEWS_VIEWS,
  persistNewsLayout,
  readNewsLayout,
  tabFromHash,
  truncate,
} from './news/newsHelpers'
import type { FeaturedNews, NewsItem } from './news/newsTypes'
import { NewsFeaturedHero } from './news/NewsFeaturedHero'
import { NewsFreeGamesSection } from './news/NewsFreeGamesSection'
import { NewsHeadlinesSection } from './news/NewsHeadlinesSection'

export function NewsPage() {
  const shellConfig = useShellConfig()
  const useNewChrome = Boolean(shellConfig.enableNewChrome)
  const [announcements, setAnnouncements] = useState<NewsItem[] | null>(null)
  const [freeGames, setFreeGames] = useState<NewsItem[] | null>(null)
  const [headlines, setHeadlines] = useState<NewsItem[] | null>(null)
  const [sources, setSources] = useState<string[]>([])
  // Which sites the reader has switched off. Kept client-side: this is a view
  // preference over a list the operator controls, not account state, and a
  // schema column for "I do not care for that site" would be heavier than the
  // thing it stores.
  const [mutedSources, setMutedSources] = useState<Set<string>>(() => {
    try {
      return new Set<string>(JSON.parse(window.localStorage.getItem(MUTED_SOURCES_KEY) || '[]'))
    } catch {
      return new Set<string>()
    }
  })
  const [error, setError] = useState<any>(null)
  const [retryCount, setRetryCount] = useState(0)
  const [assistMsg, setAssistMsg] = useState<Record<string, string>>({})
  const [activeTab, setActiveTab] = useState(() => tabFromHash() || 'all')
  const [layout, setLayout] = useState(readNewsLayout)

  function handleLayout(next: any) {
    setLayout(next)
    persistNewsLayout(next)
  }

  async function claimAssist(item: NewsItem) {
    if (!item?.id) {
      return
    }
    try {
      const result = await claimFreeGameAssist(item.id)
      setAssistMsg((prev) => ({
        ...prev,
        [item.id]: result.message || (result.ok ? 'Ownership updated.' : result.error || 'Failed'),
      }))
      // First candidate that survives the scheme check. A hostile feed URL is
      // skipped, not opened, and does not hide a good https fallback behind it.
      const href = [result.links?.protocol, result.links?.https, item.links?.https]
        .map(safeClaimUrl)
        .find(Boolean)
      if (href && result.ok) {
        window.open(href, '_blank', 'noopener,noreferrer')
      }
    } catch (err: any) {
      setAssistMsg((prev) => ({
        ...prev,
        [item.id]: err?.message || 'Claim assist failed',
      }))
    }
  }

  useEffect(() => {
    function onHash() {
      const fromHash = tabFromHash()
      if (fromHash) setActiveTab(fromHash)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    setError(null)
    setAnnouncements(null)
    setFreeGames(null)
    setHeadlines(null)

    Promise.allSettled([
      fetchAnnouncements({ signal: controller.signal }),
      fetchFreeGames({ signal: controller.signal }),
      fetchGamingNews({ signal: controller.signal }),
    ]).then(([announceResult, freeResult, newsResult]) => {
      if (!active) {
        return
      }
      if (announceResult.status === 'fulfilled') {
        const announceData = announceResult.value
        setAnnouncements(
          Array.isArray(announceData.announcements) ? announceData.announcements : [],
        )
      } else if (announceResult.reason?.name !== 'AbortError') {
        setError(announceResult.reason)
        setAnnouncements([])
      }
      if (freeResult.status === 'fulfilled') {
        const freeData = freeResult.value
        setFreeGames(Array.isArray(freeData.items) ? freeData.items : [])
      } else {
        setFreeGames([])
      }
      if (newsResult.status === 'fulfilled') {
        const newsData = newsResult.value
        setHeadlines(Array.isArray(newsData.items) ? newsData.items : [])
        setSources(Array.isArray(newsData.sources) ? newsData.sources : [])
      } else {
        setHeadlines([])
      }
    })

    return () => {
      active = false
      controller.abort()
    }
  }, [retryCount])

  function toggleSource(source: string) {
    setMutedSources((previous) => {
      const next = new Set(previous)
      if (next.has(source)) next.delete(source)
      else next.add(source)
      try {
        window.localStorage.setItem(MUTED_SOURCES_KEY, JSON.stringify([...next]))
      } catch {
        // View preference only — the filter still applies for this session.
      }
      return next
    })
  }

  // Muting a site hides its articles everywhere on this page, including the
  // hero — a muted source promoted to the featured slot would be the one story
  // you asked not to see, in the largest box.
  const visibleHeadlines = useMemo(
    () => (headlines || []).filter((item: any) => !mutedSources.has(item.source)),
    [headlines, mutedSources],
  )

  const loading = !error && (!announcements || !freeGames || !headlines)
  const showAdmins = activeTab === 'all' || activeTab === 'admins'
  const showFree = activeTab === 'all' || activeTab === 'free'
  const showHeadlines = activeTab === 'all' || activeTab === 'headlines'

  const featured = useMemo((): FeaturedNews | null => {
    if (activeTab === 'free' || activeTab === 'headlines') return null
    if (announcements?.length) {
      return { kind: 'admin', item: announcements[0] }
    }
    if (activeTab === 'admins') return null
    if (visibleHeadlines.length) {
      return { kind: 'headline', item: visibleHeadlines[0] }
    }
    if (freeGames?.length) {
      return { kind: 'free', item: freeGames[0] }
    }
    return null
  }, [activeTab, announcements, visibleHeadlines, freeGames])

  const adminRest =
    announcements && featured?.kind === 'admin' ? announcements.slice(1) : announcements || []
  const headlineRest = featured?.kind === 'headline' ? visibleHeadlines.slice(1) : visibleHeadlines
  const freeRest = freeGames && featured?.kind === 'free' ? freeGames.slice(1) : freeGames || []

  // Counts ride on the segments themselves rather than a separate summary —
  // "Free now 3" answers the question the tab was asking. Omitted while
  // loading, so a section never reads as empty when it is simply unfetched.
  const viewsWithCounts = useMemo(() => {
    if (loading || error) return NEWS_VIEWS
    const counts: LooseProps = {
      admins: announcements?.length || 0,
      free: freeGames?.length || 0,
      headlines: visibleHeadlines.length,
    }
    counts.all = counts.admins + counts.free + counts.headlines
    return NEWS_VIEWS.map((view) => ({ ...view, count: counts[view.id] }))
  }, [loading, error, announcements, freeGames, visibleHeadlines])

  const freeItems = activeTab === 'free' ? freeGames || [] : freeRest
  const headlineItems = activeTab === 'headlines' ? visibleHeadlines : headlineRest

  return (
    <>
      {useNewChrome ? (
        <ContextBar
          views={viewsWithCounts}
          activeView={activeTab}
          onSelectView={setActiveTab}
          viewUnfurl={{
            views: NEWS_LAYOUTS,
            active: layout,
            onSelect: handleLayout,
            triggerLabel: 'View',
          }}
        />
      ) : null}
      <div className="od-more-page od-news od-news--fill" data-layout={layout} data-tab={activeTab}>
        {useNewChrome ? null : (
          <div className="od-page-header od-news__header od-panels__full">
            <div>
              <h1>News</h1>
              <p className="od-more-page__lede">Admin notes, free claims, and gaming headlines.</p>
            </div>
            <nav className="od-news__tabs" aria-label="News sections">
              {NEWS_VIEWS.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  className={activeTab === id ? 'is-active' : ''}
                  aria-pressed={activeTab === id}
                  onClick={() => setActiveTab(id)}
                >
                  {label}
                </button>
              ))}
            </nav>
          </div>
        )}

        <PageStatus
          loading={loading}
          error={error}
          errorMessage="Unable to load news."
          loadingMessage="Loading news…"
          onRetry={() => setRetryCount((n) => n + 1)}
        />

        <NewsFeaturedHero
          activeTab={activeTab}
          error={error}
          featured={featured}
          loading={loading}
        />

        <div className="od-news__stage">
          {/* Admin notes lead, full width, and only when there are any.
          `announcements` is an array, so the old `announcements &&` was true
          even when empty and rendered a heading, a zero count and "No
          announcements yet." — a permanent empty panel taking a column from the
          two sections that always have something in them. On the Admins tab the
          empty state still shows, because there the section *is* the page and
          silence would read as a failed load. */}
          {!error &&
          announcements &&
          showAdmins &&
          (announcements.length > 0 || activeTab === 'admins') ? (
            <section
              className="od-news__section od-news__admins"
              aria-labelledby="news-admins-heading"
            >
              <div className="od-news__section-head">
                <h2 id="news-admins-heading">From your admins</h2>
                <span className="od-news__count">{announcements.length}</span>
              </div>
              <div className="od-news__panel-body">
                {announcements.length === 0 ? (
                  <p className="od-news__empty">No announcements yet.</p>
                ) : null}
                {adminRest.length > 0 ? (
                  <ul className="od-news__rail">
                    {adminRest.map((item: any) => (
                      <li key={item.id} className="od-news__rail-item od-news__rail-item--admin">
                        <article>
                          <header className="od-news__rail-head">
                            <strong>{item.title}</strong>
                            {item.created_at ? (
                              <time dateTime={item.created_at}>
                                {formatLocaleDate(item.created_at)}
                              </time>
                            ) : null}
                          </header>
                          <p>{truncate(item.body, 220)}</p>
                        </article>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </section>
          ) : null}

          <NewsFreeGamesSection
            assistMsg={assistMsg}
            claimAssist={claimAssist}
            error={error}
            freeGames={freeGames}
            freeItems={freeItems}
            layout={layout}
            showFree={showFree}
          />

          {/* Headlines take a column rather than the full row, so News and Free sit
          side by side under the admin notes. Spanning the row was what pushed
          Free up beside admins and left the page reading as one long scroll on
          the tab that shows everything. */}
          <NewsHeadlinesSection
            error={error}
            headlineItems={headlineItems}
            headlines={headlines}
            layout={layout}
            mutedSources={mutedSources}
            showHeadlines={showHeadlines}
            sources={sources}
            toggleSource={toggleSource}
            visibleHeadlines={visibleHeadlines}
          />
        </div>
      </div>
    </>
  )
}
