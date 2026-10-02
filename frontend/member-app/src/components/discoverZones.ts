import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Discover's zones as the top bar's view strip.
 *
 * The zones (For you, New & updated, Popular here …) used to be a row of pill
 * links in the page gutter above the feed. They are sibling views of one page,
 * which is exactly what the bar's segmented strip is for on Game Catalog, so
 * they render there instead: "All" for the whole feed, then one button per
 * zone, with the one you are on filled.
 *
 * The zone list arrives with the main feed (the server derives it from the
 * shelves it just rendered, so it can never offer a zone that would 404). A
 * zone page does not get that list, so the last one Discover saw is kept for
 * the session and the zone page reuses it. Opened cold, a zone page simply has
 * no strip until Discover has been visited, rather than paying for a second
 * full feed assembly just to draw buttons.
 */

export interface DiscoverZone {
  slug: string
  title: string
  lede?: string
  href?: string
}

/** The id the strip uses for the whole feed. Not a zone slug the server issues. */
export const ALL_ZONES = '__all__'

const STORAGE_KEY = 'od.discover.zones'

let remembered: DiscoverZone[] | null = null

function clean(zones: unknown): DiscoverZone[] {
  if (!Array.isArray(zones)) return []
  return zones
    .filter((zone: any) => zone && typeof zone.slug === 'string' && zone.slug)
    .map((zone: any) => ({
      slug: zone.slug,
      title: String(zone.title || zone.slug),
      lede: zone.lede ? String(zone.lede) : undefined,
      href: zone.href ? String(zone.href) : undefined,
    }))
}

/** Keep the feed's zone list for zone pages opened later in the session. */
export function rememberDiscoverZones(zones: unknown) {
  remembered = clean(zones)
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(remembered))
  } catch {
    /* Private mode or blocked storage: the in-memory copy still serves this tab. */
  }
}

export function recalledDiscoverZones(): DiscoverZone[] {
  if (remembered) return remembered
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    remembered = raw ? clean(JSON.parse(raw)) : []
  } catch {
    remembered = []
  }
  return remembered
}

/** Test seam: forget what the session remembered. */
export function resetDiscoverZones() {
  remembered = null
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* nothing to clear */
  }
}

export function zoneHref(zone: DiscoverZone) {
  return zone.href || `/discover/zone/${encodeURIComponent(zone.slug)}`
}

/**
 * Props for `ContextBar` that put the zones in the bar.
 *
 * Returns `views: undefined` when there is only one zone or none: one zone is
 * not a choice, and "All" on its own would be a button that goes nowhere.
 */
export function useDiscoverZoneViews(active: string, zones?: DiscoverZone[] | null) {
  const navigate = useNavigate()
  const list = useMemo(() => (zones ? clean(zones) : recalledDiscoverZones()), [zones])

  const views = useMemo(() => {
    if (list.length < 2) return undefined
    return [{ id: ALL_ZONES, label: 'All' }].concat(
      list.map((zone) => ({ id: zone.slug, label: zone.title })),
    )
  }, [list])

  const onSelectView = useCallback(
    (id: string) => {
      if (id === active) return
      if (id === ALL_ZONES) {
        navigate('/discover')
        return
      }
      const zone = list.find((entry) => entry.slug === id)
      if (zone) navigate(zoneHref(zone))
    },
    [active, list, navigate],
  )

  return { views, activeView: active, onSelectView }
}
