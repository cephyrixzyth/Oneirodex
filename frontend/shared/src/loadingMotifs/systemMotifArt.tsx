import type { ReactElement } from 'react'
/**
 * Systems share hardware silhouettes. The generated variant controls details
 * such as button count, cartridge slot position and screen shape.
 */

import { SYSTEM_MOTIFS } from './systemMotifCatalogue.js'

const svgProps = {
  viewBox: '0 0 48 48',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': 'true',
} as const

/** Face-button cluster; count varies 2-4 so pads differ at a glance. */
function FaceButtons({ variant }: { variant: number }) {
  const count = 2 + (variant % 3)
  const spots = [
    { cx: 34, cy: 20 },
    { cx: 38, cy: 24 },
    { cx: 34, cy: 28 },
    { cx: 30, cy: 24 },
  ].slice(0, count)
  return (
    <g className="od-sysmotif__buttons">
      {spots.map((spot, i) => (
        <circle
          key={spot.cx + '-' + spot.cy}
          {...spot}
          r="2"
          style={{ animationDelay: `${i * 0.14}s` }}
        />
      ))}
    </g>
  )
}

const ARCHETYPES: Record<string, (variant: number) => ReactElement> = {
  /** Controller — grips, d-pad, face buttons pressing in sequence. */
  pad: (variant: number) => (
    <svg {...svgProps}>
      <path
        className="od-sysmotif__shell"
        d={
          variant % 2
            ? 'M9 18h30a6 6 0 0 1 6 6v4a5 5 0 0 1-9 3l-3-4H15l-3 4a5 5 0 0 1-9-3v-4a6 6 0 0 1 6-6z'
            : 'M8 18h32a5 5 0 0 1 5 5v6a4 4 0 0 1-7 2.5L35 29H13l-3 2.5A4 4 0 0 1 3 29v-6a5 5 0 0 1 5-5z'
        }
      />
      <path className="od-sysmotif__dpad" d="M14 24h6M17 21v6" />
      <FaceButtons variant={variant} />
    </svg>
  ),

  /** Console deck — power LED pulses, cartridge/disc slot reads. */
  console: (variant: number) => (
    <svg {...svgProps}>
      <rect
        className="od-sysmotif__shell"
        x="5"
        y="16"
        width="38"
        height="18"
        rx={2 + (variant % 3)}
      />
      <path
        className="od-sysmotif__vents"
        d={variant % 2 ? 'M10 21h8M10 25h8M10 29h8' : 'M10 22h6M10 27h6'}
      />
      <rect className="od-sysmotif__slot" x="24" y="20" width="14" height="4" rx="1" />
      <circle className="od-sysmotif__led" cx="21" cy="30" r="1.6" />
    </svg>
  ),

  /** Handheld — screen refresh line, d-pad, power LED. */
  handheld: (variant: number) => (
    <svg {...svgProps}>
      <rect
        className="od-sysmotif__shell"
        x="13"
        y="5"
        width="22"
        height="38"
        rx={variant % 2 ? 5 : 3}
      />
      <rect
        className="od-sysmotif__screen"
        x="17"
        y="10"
        width="14"
        height={variant % 3 ? 11 : 13}
        rx="1"
      />
      <rect className="od-sysmotif__scanline" x="17" y="11" width="14" height="2" />
      <path className="od-sysmotif__dpad" d="M18 30h5M20.5 27.5v5" />
      <circle className="od-sysmotif__led" cx="30" cy="30" r="1.5" />
    </svg>
  ),

  /** Arcade cabinet — marquee glows, screen rasters. */
  cabinet: (variant: number) => (
    <svg {...svgProps}>
      <path className="od-sysmotif__shell" d="M12 6h24v34a2 2 0 0 1-2 2H14a2 2 0 0 1-2-2z" />
      <rect className="od-sysmotif__marquee" x="15" y="9" width="18" height="5" rx="1" />
      <rect className="od-sysmotif__screen" x="16" y="17" width="16" height="12" rx="1" />
      <rect className="od-sysmotif__scanline" x="16" y="18" width="16" height="2" />
      <path className="od-sysmotif__dpad" d={variant % 2 ? 'M18 35h4M24 35h6' : 'M19 35h10'} />
    </svg>
  ),

  /** Home computer / PC — monitor raster over a keyboard. */
  computer: (variant: number) => (
    <svg {...svgProps}>
      <rect className="od-sysmotif__shell" x="8" y="8" width="32" height="21" rx="2" />
      <rect className="od-sysmotif__scanline" x="11" y="11" width="26" height="3" />
      <path className="od-sysmotif__vents" d={variant % 2 ? 'M6 36h36M6 40h36' : 'M6 38h36'} />
      <path className="od-sysmotif__stand" d="M20 29v4h8v-4" />
    </svg>
  ),

  /** Disc-era system — platter spins under a tracking head. */
  disc: () => (
    <svg {...svgProps}>
      <g className="od-sysmotif__platter">
        <circle className="od-sysmotif__shell" cx="24" cy="22" r="13" />
        <path className="od-sysmotif__glint" d="M24 9a13 13 0 0 1 11 6.5" />
      </g>
      <circle className="od-sysmotif__hub" cx="24" cy="22" r="3.5" />
      <rect className="od-sysmotif__head" x="23" y="28" width="2" height="12" rx="1" />
    </svg>
  ),

  /** Cartridge — slots home, lifts, repeats. Also the honest fallback for the
   *  handful of entries that are not consoles at all (Daphne, Pinball). */
  cart: (variant: number) => (
    <svg {...svgProps}>
      <path className="od-sysmotif__slot" d="M11 32h26v9H11z" />
      <g className="od-sysmotif__cart">
        <rect
          className="od-sysmotif__shell"
          x="15"
          y="8"
          width="18"
          height="22"
          rx={variant % 2 ? 3 : 1}
        />
        <rect className="od-sysmotif__label" x="18" y="11" width="12" height="8" rx="1" />
        <path className="od-sysmotif__pins" d="M18 26h12" />
      </g>
    </svg>
  ),
}

export const SYSTEM_MOTIF_ARCHETYPES = Object.keys(ARCHETYPES)

/**
 * @param {{ archetype: string, variant?: number }} props
 * @returns {JSX.Element} never null — an unknown archetype falls back to the
 *   cartridge rather than rendering an empty box, which reads as "not loading".
 */
export function SystemMotifArt({
  archetype,
  variant = 0,
}: {
  archetype: string
  variant?: number
}) {
  const draw = ARCHETYPES[archetype] || ARCHETYPES.cart
  return draw(variant)
}

/**
 * The motif for one LibraryPlatform, by its enum name (`NES`, `PS2`, `PCWIN`).
 *
 * The generator derives every motif id as `LibraryPlatform.<NAME>.lower()`, so
 * the lookup is exactly that and nothing has to be kept in sync by hand — see
 * scripts/gen_loading_motifs.py.
 *
 * @param {string} platformValue
 * @returns {{ id: string, name: string, archetype: string, variant: number } | null}
 */
export function motifForPlatform(platformValue: unknown) {
  const id = String(platformValue || '').toLowerCase()
  if (!id) return null
  return SYSTEM_MOTIFS.find((motif) => motif.id === id) || null
}
