import { useCallback, useEffect, useMemo, useState } from 'react'
import { useShellConfig, useViewer } from '@oneirodex/ui'
import { fetchDiscoverSections } from './api/discover'
import { fetchDiscoverPins, saveDiscoverPins } from './api/discoverPins'
import { ContextBar } from './chrome/ContextBar'
import { DiscoverShelf, formatEventEnds, rowItems } from './components/DiscoverShelf'
import { DiscoverRowSettings } from './components/DiscoverRowSettings'
import { DiscoverSurprise } from './components/DiscoverSurprise'
import { DiscoverZoneStrip } from './components/DiscoverZoneStrip'
import { PageStatus } from './components/PageStatus'

/**
 * Apply pin order and hidden rows on the client so Pin / Hide take effect
 * immediately. The feed only honours arrangement on the next load, which made
 * the heading buttons look dead.
 */
export function arrangeDiscoverSections(
  sections: any,
  { pins = [], hidden = [] }: LooseProps = {},
) {
  const hiddenSet = new Set(hidden.map(String))
  const shown = sections.filter((section: any) => {
    if (hiddenSet.has(String(section.identifier || ''))) return false
    return rowItems(section).length > 0
  })
  if (!pins.length) return shown
  const pinIndex = new Map(pins.map((id: any, i: any) => [String(id), i]))
  const pinned = []
  const rest = []
  for (const section of shown) {
    if (pinIndex.has(String(section.identifier || ''))) pinned.push(section)
    else rest.push(section)
  }
  pinned.sort(
    (a, b) =>
      Number(pinIndex.get(String(a.identifier))) - Number(pinIndex.get(String(b.identifier))),
  )
  return pinned.concat(rest)
}

export function DiscoverApp() {
  const { isAdmin } = useViewer()
  const shellConfig = useShellConfig()
  const [sections, setSections] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<any>(null)
  const [pins, setPins] = useState<any[]>([])
  const [hidden, setHidden] = useState<any[]>([])
  const [maxPins, setMaxPins] = useState(0)
  // Every row the feed can show, hidden ones included. The sections payload
  // only carries what is actually rendered, so a hidden row is absent from it
  // by construction — which is exactly the row the settings panel has to be
  // able to list. Kept from the arrangement response, which is derived from
  // `resolve_feed` and therefore always the complete set.
  const [known, setKnown] = useState<any[]>([])
  const [zones, setZones] = useState<any[]>([])

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchDiscoverSections({ signal: controller.signal })
      .then((next) => {
        if (cancelled) return
        setSections(next.sections)
        setZones(next.zones)
        setLoading(false)
      })
      .catch((err: any) => {
        if (cancelled || err?.name === 'AbortError') return
        setError(true)
        setLoading(false)
      })
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])

  const loadArrangement = useCallback((signal: any) => {
    return fetchDiscoverPins({ signal })
      .then((state) => {
        setPins(state.pins)
        setHidden(state.hidden)
        setMaxPins(state.maxPins)
        setKnown(state.available)
      })
      .catch(() => {
        // Arrangement is an enhancement. A feed that loaded is still a feed, so
        // a failure here hides the controls rather than breaking the page.
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    loadArrangement(controller.signal)
    return () => controller.abort()
  }, [loadArrangement])

  /**
   * Push an arrangement change and roll back if the server refuses it.
   *
   * Optimistic: pin order and hides apply on this feed immediately. A refetch
   * after a successful save keeps the payload in agreement with the buttons.
   */
  const reloadFeed = useCallback(() => {
    return fetchDiscoverSections()
      .then((next) => {
        setSections(next.sections)
        // Hiding the last shelf in a zone removes that zone from the strip, so
        // the strip has to be refreshed with the feed, not just once at mount.
        setZones(next.zones)
      })
      .catch(() => {
        /* Arrangement already applied locally; a failed refetch is not a rollback. */
      })
  }, [])

  const commit = useCallback(
    (next: any, previous: any) => {
      saveDiscoverPins(next)
        .then(() => reloadFeed())
        .catch(() => {
          if (previous.pins) setPins(previous.pins)
          if (previous.hidden) setHidden(previous.hidden)
        })
    },
    [reloadFeed],
  )

  const togglePin = useCallback(
    (identifier: any) => {
      setPins((current) => {
        const next = current.includes(identifier)
          ? current.filter((pin) => pin !== identifier)
          : current.concat(identifier).slice(0, maxPins || current.length + 1)
        commit({ pins: next }, { pins: current })
        return next
      })
    },
    [commit, maxPins],
  )

  const toggleHidden = useCallback(
    (identifier: any) => {
      setHidden((current) => {
        const next = current.includes(identifier)
          ? current.filter((row) => row !== identifier)
          : current.concat(identifier)
        commit({ hidden: next }, { hidden: current })
        return next
      })
      // A hidden row cannot also be pinned — the feed would have to both
      // reserve a slot for it and not render it. Dropping the pin here keeps
      // the two lists from disagreeing rather than leaving the server to
      // arbitrate.
      setPins((current) => {
        if (!current.includes(identifier)) return current
        const next = current.filter((pin) => pin !== identifier)
        commit({ pins: next }, { pins: current })
        return next
      })
    },
    [commit],
  )

  /** Move a pinned row one place up (-1) or down (+1) in the member's order. */
  const movePin = useCallback(
    (identifier: any, delta: any) => {
      setPins((current) => {
        const from = current.indexOf(identifier)
        const to = from + delta
        if (from < 0 || to < 0 || to >= current.length) return current
        const next = current.slice()
        next.splice(to, 0, next.splice(from, 1)[0])
        commit({ pins: next }, { pins: current })
        return next
      })
    },
    [commit],
  )

  // Rows of games carry `games`, rows of anything else carry `items`. Reading
  // only the former would have hidden the news row entirely.
  const visible = useMemo(
    () => arrangeDiscoverSections(sections, { pins, hidden }),
    [hidden, pins, sections],
  )

  /**
   * Every row the settings panel can offer, with a title for each.
   *
   * Titles come from the rendered sections where we have them. A hidden row is
   * not in that payload, so it falls back to its identifier prettified — which
   * is not ideal, and is the honest cost of the feed not shipping rows it is
   * not going to render. It stays recognisable ("free_this_week" reads as "Free
   * this week"), and showing the row again replaces it with the real title.
   */
  const settingsRows = useMemo(() => {
    const titles = new Map(
      sections.map((section) => [
        String(section.identifier || ''),
        section.title || String(section.identifier || ''),
      ]),
    )
    return known.map((identifier) => ({
      identifier,
      title: titles.get(identifier) || prettifyIdentifier(identifier),
    }))
  }, [known, sections])

  if (loading || error) {
    return (
      <PageStatus
        loading={loading}
        error={error}
        errorMessage="Unable to load Discover shelves."
        loadingMessage="Loading Discover…"
      />
    )
  }

  /* The way back for a hidden row, and the only place pin order can be said.
     Rendered whenever the server told us what the feed could contain — without
     that list the panel would be a control that cannot list what it controls. */
  const bar = settingsRows.length ? (
    <ContextBar
      summary={`${visible.length} rows`}
      filterCount={hidden.length}
      filtersOnSummary
      filters={
        <DiscoverRowSettings
          rows={settingsRows}
          pins={pins}
          hidden={hidden}
          maxPins={maxPins}
          onTogglePin={togglePin}
          onToggleHidden={toggleHidden}
          onMovePin={movePin}
        />
      }
    />
  ) : null

  if (!visible.length) {
    return (
      <>
        {bar}
        <PageStatus emptyMessage="No Discover shelves to show yet." />
      </>
    )
  }

  return (
    <>
      {bar}
      <DiscoverZoneStrip zones={zones} />
      <DiscoverSurprise
        isAdmin={isAdmin}
        showPlayStatus={Boolean(shellConfig.showPlayStatus)}
        enableDeleteOnDisk={Boolean(shellConfig.enableDeleteOnDisk)}
      />
      {visible.map((section: any) => {
        const identifier = String(section.identifier || section.title || 'section')
        return (
          <DiscoverShelf
            key={identifier}
            section={section}
            isAdmin={isAdmin}
            showPlayStatus={Boolean(shellConfig.showPlayStatus)}
            enableDeleteOnDisk={Boolean(shellConfig.enableDeleteOnDisk)}
            pinned={pins.includes(identifier)}
            canPin={pins.length < maxPins}
            onTogglePin={maxPins ? togglePin : undefined}
            onHide={toggleHidden}
          />
        )
      })}
    </>
  )
}

/** "free_this_week" → "Free this week". Only used for a row we cannot name. */
export function prettifyIdentifier(identifier: any) {
  const words = String(identifier || '')
    .replace(/[_:-]+/g, ' ')
    .trim()
  if (!words) return 'Row'
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// Re-exported for the tests and callers that imported it from here before the
// shelf became its own component.
export { formatEventEnds }
