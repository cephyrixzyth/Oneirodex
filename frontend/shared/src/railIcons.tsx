/**
 * Rail glyphs for every destination, shared by the member and admin shells.
 *
 * This lived in both apps as two hand-maintained copies. The stated reason was
 * that `frontend/shared` had to be staged explicitly in the Dockerfile and had
 * broken the image build once — but the Dockerfile stages all of `frontend/`
 * now, and the two copies had already drifted apart: the member set carried a
 * `ways-to-play` glyph the admin set never got. That is exactly the failure
 * duplication produces, so the copies are gone and this is the one source.
 *
 * Drawn from `partials/icons.html` rather than redrawn, so the SPAs and the
 * Jinja pages keep speaking one visual language. Same 24x24 grid, everything
 * `currentColor` and 2px stroke, so the icon-pack tokens (`--od-icon-stroke`,
 * `--od-icon-linecap`, `--od-icon-fill`) restyle them per theme for free —
 * which is how a preset gets its own glyph treatment without redrawing
 * twenty-three paths per theme.
 */
import type { SVGProps } from 'react'
import { eraForGlyphs, eraGlyph } from './railIconsEra.js'

/**
 * Padded by one unit on each side: a 2px stroke sitting on the edge of the
 * 24-unit grid is otherwise sliced in half by the viewport boundary. The glyphs
 * are drawn on 0 0 24 24; this box is the same drawing with breathing room.
 */
export const RAIL_VIEWBOX = '-1 -1 26 26'

const base = {
  className: 'od-icon',
  viewBox: RAIL_VIEWBOX,
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
} as const

export const railIconPaths: Record<string, React.ReactNode> = {
  acquire: (
    <>
      <path d="M5 8h14l-1.3 11.2a2 2 0 0 1-2 1.8H8.3a2 2 0 0 1-2-1.8L5 8z" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" />
      <path d="M12 11.5v5M9.5 14h5" strokeWidth="2.2" />
    </>
  ),
  activity: (
    <>
      <path d="M2 12h4l2.5-7 4 14L15.5 12H22" />
      <circle cx="15.5" cy="12" r="2" fill="currentColor" stroke="none" />
    </>
  ),
  admin: (
    <>
      <path d="M12 2.5 4 5.5v6c0 5 3.4 9.2 8 10.5 4.6-1.3 8-5.5 8-10.5v-6l-8-3z" />
      <path d="m8.8 12 2.2 2.2 4.2-4.4" fill="none" />
    </>
  ),
  'big-picture': (
    <>
      <rect x="2" y="4" width="20" height="14" rx="2" />
      <path d="M8 21h8" />
      <path d="M10.5 8.7v4.6L15 11l-4.5-2.3z" fill="currentColor" stroke="none" />
    </>
  ),
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3 10h18" />
      <rect x="6.5" y="13" width="4" height="4" rx="1" fill="currentColor" stroke="none" />
    </>
  ),
  chat: (
    <>
      <path d="M21 12a8 7 0 0 1-8 7 9 9 0 0 1-3-.5L5 20l1.2-3.3A6.7 6.7 0 0 1 5 12a8 7 0 0 1 16 0z" />
      <circle cx="9.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="13" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="16.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  collections: (
    <>
      <path d="M12 2 2 7l10 5 10-5-10-5z" fill="currentColor" stroke="none" />
      <polyline points="2 12 12 17 22 12" />
      <polyline points="2 17 12 22 22 17" />
    </>
  ),
  content: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 8h6M7 12h10M7 16h10" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="4" width="7.5" height="16" rx="2" fill="currentColor" stroke="none" />
      <rect x="13.5" y="4" width="7.5" height="7" rx="2" />
      <rect x="13.5" y="13" width="7.5" height="7" rx="2" />
    </>
  ),
  discover: (
    <>
      <circle cx="12" cy="12" r="10" />
      <polygon
        points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"
        fill="currentColor"
        stroke="none"
      />
    </>
  ),
  downloads: (
    <>
      <path d="M12 3v9" />
      <path d="M8 10.5 12 15l4-4.5z" fill="currentColor" stroke="none" />
      <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </>
  ),
  favorites: (
    <>
      <path
        d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z"
        fill="currentColor"
        stroke="none"
      />
    </>
  ),
  friends: (
    <>
      <circle cx="9" cy="8" r="3.6" fill="currentColor" stroke="none" />
      <path d="M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5" />
      <circle cx="17.5" cy="9.5" r="2.6" />
      <path d="M17.5 14.2c2.4 0 4.3 1.9 4.3 4.3" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.4 9.4a2.7 2.7 0 1 1 3.5 2.6c-.6.2-.9.8-.9 1.4v.3" />
      <circle cx="12" cy="17" r="1.2" fill="currentColor" stroke="none" />
    </>
  ),
  integrations: (
    <>
      <path d="M6 8h12v3a6 6 0 0 1-12 0V8z" />
      <path d="M9 8V2M15 8V2M12 17v5" />
    </>
  ),
  libraries: (
    <>
      <path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6z" />
    </>
  ),
  library: (
    <>
      <rect x="3" y="4" width="4.5" height="16" rx="1" fill="currentColor" stroke="none" />
      <rect x="9.5" y="4" width="4.5" height="16" rx="1" />
      <path d="m16.6 5.4 3.9 1-3.1 13.2-3.9-1z" />
    </>
  ),
  logout: (
    <>
      <path d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4" />
      <path d="m16 17 5-5-5-5" />
      <path d="M21 12H9" />
    </>
  ),
  news: (
    <>
      <path d="M4 5h13a1 1 0 0 1 1 1v13H6a2 2 0 0 1-2-2V5z" />
      <path d="M18 9h2a1 1 0 0 1 1 1v7a2 2 0 0 1-2 2" />
      <rect x="7" y="8" width="8" height="3" rx="0.5" fill="currentColor" stroke="none" />
      <path d="M7 14h8" />
    </>
  ),
  notifications: (
    <>
      <path d="M6 10.5a6 6 0 0 1 12 0c0 3.8 1.4 5.2 1.4 5.2H4.6S6 14.3 6 10.5z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
      <circle cx="18" cy="5.5" r="2.6" fill="currentColor" stroke="none" />
    </>
  ),
  // A key, not a shopping bag (W28). The bag was the `store` glyph doing double
  // duty, and it said "buy something" on the one page that is about what you
  // already have. Ownership here is licences held across Steam / GOG / Epic / Amazon —
  // and a game licence has been called a key for as long as it has existed, so
  // the metaphor needs no learning.
  ownership: (
    <>
      <circle cx="8" cy="8" r="4.2" fill="currentColor" stroke="none" />
      <path d="m11 11 9 9" />
      <path d="m17.5 17.5 2-2M15 15l2-2" />
    </>
  ),
  playtime: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.2V12l3.2 2.1" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    </>
  ),
  // A flag, not a beetle. The bug glyph named one *kind* of report — and at
  // 18px a six-legged silhouette is a smudge. Flagging is the conventional verb
  // for raising an issue, and a filled pennant on a pole survives the size.
  report: (
    <>
      <path d="M5 21V3" />
      <path d="M5 4.2h11.5l-2 3.4 2 3.4H5z" fill="currentColor" stroke="none" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
    </>
  ),
  // --- Admin sub-section glyphs: same 24-grid, currentColor, 2px stroke. ---
  scan: (
    <>
      <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15.5 6.2L3 16" />
      <path d="M3 21v-5h5" />
    </>
  ),
  tools: (
    <>
      <path d="M14.5 6.5a4 4 0 0 0-5 5L3.5 17.5a2 2 0 0 0 3 3l6-6a4 4 0 0 0 5-5l-2.5 2.5-2-.5-.5-2z" />
    </>
  ),
  unmatched: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  filter: (
    <>
      <path d="M3 5h18l-7 8.5V20l-4-2v-4.5L3 5z" />
    </>
  ),
  art: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="1.8" />
      <path d="m3.5 18 5.5-5 4 3.5 3-2.5 4.5 4" />
    </>
  ),
  plugins: (
    <>
      <path d="M10 3v3H7a2 2 0 0 0-2 2v3h3a2 2 0 1 1 0 4H5v3a2 2 0 0 0 2 2h3v-3a2 2 0 1 1 4 0v3h3a2 2 0 0 0 2-2v-3h-3a2 2 0 1 1 0-4h3V8a2 2 0 0 0-2-2h-3V3a2 2 0 1 0-4 0z" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20V10M10 20V4M16 20v-8M22 20H2" />
    </>
  ),
  danger: (
    <>
      <path d="M12 3 2 20h20L12 3z" />
      <path d="M12 10v4.5" />
      <circle cx="12" cy="17.3" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  storage: (
    <>
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M5 13l2-8h10l2 8" />
      <circle cx="7.5" cy="16.5" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  emulators: (
    <>
      <rect x="2" y="7" width="20" height="11" rx="5" />
      <path d="M7 10.5v4M5 12.5h4" />
      <circle cx="15.5" cy="11.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="18" cy="14" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  themes: (
    <>
      <path d="M12 3a9 9 0 1 0 0 18c1.3 0 2-.8 2-1.8 0-1.2-1-1.4-1-2.5 0-.9.7-1.7 1.7-1.7H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z" />
      <circle cx="7.5" cy="11" r="1" fill="currentColor" stroke="none" />
      <circle cx="10" cy="7.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="7.5" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  layout: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 21V9" />
    </>
  ),
  attract: (
    <>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="m10 9.5 5 2.5-5 2.5v-5z" fill="currentColor" stroke="none" />
    </>
  ),
  ai: (
    <>
      <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" />
      <path d="M19 15v4M17 17h4" />
    </>
  ),
  quality: (
    <>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  reference: (
    <>
      <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4z" />
      <path d="M5 17a3 3 0 0 1 3-3h11" />
    </>
  ),
  matching: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
      <path d="m8 10.5 2 2 3.5-3.5" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3.5 7 8.5 6 8.5-6" />
    </>
  ),
  metadata: (
    <>
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </>
  ),
  identity: (
    <>
      <circle cx="8" cy="14" r="4" />
      <path d="m11 11 9-8M16 6l3 3M14 8l2 2" />
    </>
  ),
  voice: (
    <>
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </>
  ),
  stores: (
    <>
      <path d="M4 9l1.5-5h13L20 9" />
      <path d="M4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9" />
      <path d="M5.5 11.5V20h13v-8.5M10 20v-5h4v5" />
    </>
  ),
  remote: (
    <>
      <rect x="2" y="4" width="20" height="13" rx="2" />
      <path d="M8 21h8M12 17v4" />
      <path d="M9 10.5a4 4 0 0 1 6 0M10.8 12.3a1.6 1.6 0 0 1 2.4 0" />
    </>
  ),
  server: (
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <circle cx="7" cy="7.5" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="7" cy="16.5" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  system: (
    <>
      <rect x="2" y="3" width="20" height="7" rx="2" />
      <rect x="2" y="14" width="20" height="7" rx="2" />
      <path d="M6 6.5h.01M6 17.5h.01" />
    </>
  ),
  systems: (
    <>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
      <rect x="10" y="10" width="4" height="4" rx="1" fill="currentColor" stroke="none" />
      <path d="M9.5 2v3M14.5 2v3M9.5 19v3M14.5 19v3M2 9.5h3M2 14.5h3M19 9.5h3M19 14.5h3" />
    </>
  ),
  trailers: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M4 8h3M4 12h3M4 16h3M17 8h3M17 12h3M17 16h3" />
      <path d="M10.5 9.2v5.6L15 12l-4.5-2.8z" fill="currentColor" stroke="none" />
    </>
  ),
  updates: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20.5 3v5h-5z" fill="currentColor" stroke="none" />
    </>
  ),
  users: (
    <>
      <circle cx="8.5" cy="8" r="3.4" />
      <path d="M2 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5" />
      <circle cx="17.5" cy="6.5" r="2.4" fill="currentColor" stroke="none" />
      <path d="M17.5 11.5c2.5 0 4.5 2 4.5 4.5" />
    </>
  ),
  vr: (
    <>
      <path d="M3 8.5h18a1 1 0 0 1 1 1v4a2 2 0 0 1-2 2h-3.4l-1.8-2.2h-3.6L11.4 15.5H8a2 2 0 0 1-2-2" />
      <path d="M2 9.5v4a2 2 0 0 0 2 2" />
      <circle cx="8.2" cy="11.6" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="15.8" cy="11.6" r="1.5" fill="currentColor" stroke="none" />
    </>
  ),
  'ways-to-play': (
    <>
      <rect x="3.5" y="8" width="17" height="10.5" rx="3.2" />
      <path d="M8 13.2h.01M16 12.2h.01M18 14.2h.01" />
      <path d="M7.2 11.4v3.6M5.4 13.2h3.6" />
      <circle cx="16" cy="12.2" r="1.05" fill="currentColor" stroke="none" />
      <circle cx="18.1" cy="14.2" r="1.05" fill="currentColor" stroke="none" />
    </>
  ),
  wishlist: (
    <>
      <path d="m12 3.2 2.7 5.5 6 .9-4.35 4.24 1.03 6-5.38-2.83-5.38 2.83 1.03-6L3.3 9.6l6-.9L12 3.2z" />
      <path
        d="m12 7.5 1.2 2.5 2.7.4-1.95 1.9.46 2.7L12 13.7l-2.41 1.3.46-2.7L8.1 10.4l2.7-.4L12 7.5z"
        fill="currentColor"
        stroke="none"
      />
    </>
  ),
}

export interface RailIconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: string
  size?: number
  /** Era whose hand draws the glyph (E4). Defaults to the shell's `data-era`
   * when the current theme is a decade room or system-family pack; pass
   * `null` to force the shared drawing. */
  era?: string | null
}

export function RailIcon({ name, size = 18, era, ...rest }: RailIconProps) {
  const activeEra = era === undefined ? eraForGlyphs() : era
  const glyph = eraGlyph(name, activeEra) ?? railIconPaths[name]
  // An unknown id renders nothing rather than a dot: a missing glyph should be
  // invisible, not a mark the eye reads as a real category.
  if (!glyph) return null
  return (
    <svg
      {...base}
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-icon={name}
      data-era-hand={activeEra && eraGlyph(name, activeEra) ? activeEra : undefined}
      {...rest}
    >
      {glyph}
    </svg>
  )
}
