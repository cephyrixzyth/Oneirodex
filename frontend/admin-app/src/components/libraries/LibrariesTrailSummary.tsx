import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { postJsonResult } from '../../api/adminApi'
import { ADMIN_TOPBAR_TRAIL_ID } from '../../hooks/useLegacyContextbarPortal'
import { CATALOG_REFRESH_FLAG, CATALOG_REFRESH_URL } from './librariesModel'
import type { LibraryRow, PlatformSummary } from './librariesModel'

/* LibrariesTrailSummary moved out of LibrariesPanel (v11 cycle, H-D.2) — unchanged. */

export function LibrariesTrailSummary({
  libraryCount,
  totalGames,
  totalUnmatched,
  platforms,
  platformFilter,
  onPlatformFilter,
}: {
  libraryCount: number
  totalGames: number
  totalUnmatched: number
  platforms: PlatformSummary[]
  platformFilter: string
  onPlatformFilter: (platform: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
  const [trailHost, setTrailHost] = useState<HTMLElement | null>(() =>
    typeof document !== 'undefined' ? document.getElementById(ADMIN_TOPBAR_TRAIL_ID) : null,
  )
  const rootRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const panelId = useId()

  const closeAndRestoreFocus = () => {
    setOpen(false)
    triggerRef.current?.focus()
  }

  useLayoutEffect(() => {
    setTrailHost(document.getElementById(ADMIN_TOPBAR_TRAIL_ID))
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node | null)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAndRestoreFocus()
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const matches = useMemo(() => {
    const q = needle.trim().toLowerCase()
    if (!q) return platforms
    return platforms.filter((row) => row.platform.toLowerCase().includes(q))
  }, [needle, platforms])

  const label = libraryCount === 1 ? '1 library' : `${libraryCount} libraries`
  const gamesLabel = totalGames === 1 ? '1 game' : `${totalGames} games`
  const unmatchedLabel = totalUnmatched === 1 ? '1 unmatched' : `${totalUnmatched} unmatched`

  const control = (
    <div className="od-pop od-libraries-trail" data-align="end" ref={rootRef}>
      <button
        type="button"
        className={`od-cbtn od-contextbar__count${open ? ' is-on' : ''}`}
        ref={triggerRef}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
      </button>
      {open ? (
        <div
          id={panelId}
          className="od-pop__panel od-libraries-trail__panel"
          role="dialog"
          aria-label="Libraries summary"
        >
          <div className="od-pop__head">
            <span className="od-pop__title">Libraries</span>
            <button type="button" className="od-cbtn" onClick={closeAndRestoreFocus}>
              Done
            </button>
          </div>
          <p className="od-libraries-trail__totals">
            {gamesLabel}
            <span className="od-libraries-trail__unmatched"> ({unmatchedLabel})</span>
          </p>
          <label className="od-libraries-trail__filter">
            <input
              type="search"
              className="od-table__col-filter"
              value={needle}
              onChange={(event) => setNeedle(event.target.value)}
              placeholder="Filter by platform…"
              aria-label="Filter by platform"
              autoComplete="off"
            />
          </label>
          {platformFilter ? (
            <button
              type="button"
              className="od-cbtn od-libraries-trail__clear"
              onClick={() => {
                onPlatformFilter('')
                setNeedle('')
              }}
            >
              Clear platform filter
            </button>
          ) : null}
          <ul className="od-libraries-trail__list">
            {matches.length === 0 ? (
              <li className="od-libraries-trail__empty">No platforms match.</li>
            ) : (
              matches.map((row) => (
                <li key={row.platform}>
                  <button
                    type="button"
                    className={`od-libraries-trail__row${
                      platformFilter === row.platform ? ' is-active' : ''
                    }`}
                    onClick={() => {
                      onPlatformFilter(platformFilter === row.platform ? '' : row.platform)
                      setOpen(false)
                      triggerRef.current?.focus()
                    }}
                  >
                    <span className="od-libraries-trail__name">{row.platform}</span>
                    <span className="od-libraries-trail__n">
                      {row.games}
                      <span className="od-libraries-trail__n-unmatched"> ({row.unmatched})</span>
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}
    </div>
  )

  if (trailHost) {
    return createPortal(control, trailHost)
  }
  return control
}

export async function kickCatalogRefresh(rows: LibraryRow[] | null | undefined) {
  if (typeof window === 'undefined') return
  try {
    if (window.sessionStorage?.getItem(CATALOG_REFRESH_FLAG)) return
  } catch {
    return
  }
  const keys = [
    ...new Set(
      (rows || [])
        .map((lib) => lib.platform_key)
        .filter((key) => key && key !== 'PCWIN' && key !== 'PCDOS' && key !== 'MAC'),
    ),
  ].slice(0, 6)
  if (!keys.length) return
  try {
    window.sessionStorage?.setItem(CATALOG_REFRESH_FLAG, '1')
  } catch {
    /* private mode */
  }
  for (const platform of keys) {
    try {
      await postJsonResult(CATALOG_REFRESH_URL, { library_platform: platform })
    } catch {
      /* best-effort; estimates already color the table */
    }
  }
}
