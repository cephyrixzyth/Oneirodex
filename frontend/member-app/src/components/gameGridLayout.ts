/**
 * Layout helpers for library grid virtualization.
 * Matches fixed-width CSS auto-fill tracks based on `--od-tile-min` + gap.
 */

export function readCssPx(el: any, varName: any, fallback: any) {
  if (!el || typeof getComputedStyle !== 'function') {
    return fallback
  }
  const raw = getComputedStyle(el).getPropertyValue(varName).trim()
  const n = Number.parseFloat(raw)
  return Number.isFinite(n) ? n : fallback
}

/** Column count for CSS auto-fill with fixed tile width and gap. */
export function computeGridColumns(width: any, tileMin = 180, gap = 10) {
  if (!(width > 0)) {
    return 1
  }
  const min = Math.max(1, tileMin)
  const g = Math.max(0, gap)
  return Math.max(1, Math.floor((width + g) / (min + g)))
}

/**
 * Height of one virtual row — the tiles only, no gap.
 *
 * The gap deliberately is *not* here. It used to be, and it was the third of
 * three places the same gap was counted:
 *
 *   1. this estimate returned `tileWidth * 4/3 + gap`
 *   2. GameGrid passes `gap` to the virtualizer, which spaces rows itself
 *   3. `.game-library-row` carried `padding-bottom: var(--od-tile-gap)`, and
 *      rows are measured with `virtualizer.measureElement`, so that padding
 *      landed in the measured height too
 *
 * Rows were therefore spaced roughly twice as far apart vertically as
 * horizontally, and — worse — a *measured* row and an *estimated* row differed
 * by a whole gap, so `getTotalSize()` shrank as rows came into view. The
 * container reserved height for the estimate, the tiles occupied less, and the
 * pagination bar sat below a band of nothing that grew with the tile-size
 * slider (the gap itself scales, 6px → 16px). That is the reported "empty space
 * above/below tiles" and "the section below the grid doesn't sit flush".
 *
 * One owner now: the virtualizer's own `gap` option. It puts the space
 * *between* rows and not after the last one, which is what a CSS grid `gap`
 * does and what makes the grid end flush with its final row.
 *
 * Cover is 2:3, so a row is the cover height plus `titleH` — the title strip
 * is a member preference, and a row that ignored it would leave the estimate
 * short of the measured height and reopen the drifting-total-size bug above.
 */
export function estimateGridRowHeight(width: any, columnCount: any, gap = 10, titleH = 0) {
  const cols = Math.max(1, columnCount)
  const g = Math.max(0, gap)
  const tileWidth = Math.max(1, (Math.max(width, 1) - g * (cols - 1)) / cols)
  return Math.ceil(tileWidth * (3 / 2) + Math.max(0, titleH))
}

/**
 * Nearest scrollable ancestor, or `null` when the page itself scrolls.
 *
 * The library grid virtualises against whatever actually scrolls. In the member
 * shell that is `.od-shell__main` — the shell is `height: 100dvh; overflow:
 * hidden` and the content pane is "the only scroll container in the shell" —
 * so the window never scrolls at all. Walking up for a real scroller keeps the
 * grid working in both cases without hardcoding a shell class here.
 */
export function findScrollParent(el: any) {
  if (!el || typeof getComputedStyle !== 'function') {
    return null
  }
  let node = el.parentElement
  while (node && node !== document.body && node !== document.documentElement) {
    const { overflowY, overflow } = getComputedStyle(node)
    if (/(auto|scroll|overlay)/.test(`${overflowY} ${overflow}`)) {
      return node
    }
    node = node.parentElement
  }
  return null
}

export function chunkGamesIntoRows(games: any, columnCount: any) {
  const cols = Math.max(1, columnCount)
  const rows = []
  for (let i = 0; i < games.length; i += cols) {
    rows.push(games.slice(i, i + cols))
  }
  return rows
}
