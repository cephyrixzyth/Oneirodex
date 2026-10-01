import { useEffect, type RefObject } from 'react'

/**
 * Arrow-key (and so D-pad) movement through a vertical list of controls.
 *
 * Steam Deck's browser controller template, most TV remotes and a keyboard all
 * arrive here as ArrowUp / ArrowDown. `useShelfGridNavigation` covers grids of
 * covers; forms and action lists had nothing, so a controller user could only
 * reach the second store by tabbing through every field of the first.
 *
 * Moves focus between elements marked `data-od-nav` inside `rootRef`, in DOM
 * order. Home / End jump to the ends. Keys typed into a text field, textarea or
 * select are left alone — arrows move the caret or the option there. A radio
 * or checkbox marked `data-od-nav` is a stop like any button (a D-pad cannot
 * Tab into a choice group); unmarked ones keep the browser's own arrow keys.
 *
 * Pass `enabled=false` until the root element is actually rendered (e.g.
 * while a list is still loading): the listener attaches when it flips true.
 */
export function useListFocusNavigation(rootRef: RefObject<HTMLElement | null>, enabled = true) {
  useEffect(() => {
    const root = rootRef.current
    if (!root || !enabled) return undefined

    function onKeyDown(event: KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey) return
      const target = event.target as HTMLElement | null
      if (!target || ownsArrowKeys(target)) return
      // On a marked radio or checkbox, Left/Right would check the next choice
      // (and wrap) natively; a D-pad sends them too, so they move like Up/Down.
      const choice = target instanceof HTMLInputElement
      const key =
        choice && event.key === 'ArrowRight'
          ? 'ArrowDown'
          : choice && event.key === 'ArrowLeft'
            ? 'ArrowUp'
            : event.key
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) return
      const items = Array.from(root!.querySelectorAll<HTMLElement>('[data-od-nav]')).filter(
        (el) => !el.hasAttribute('disabled') && !el.closest('[hidden]'),
      )
      if (!items.length) return
      const current = items.indexOf(target)
      let next = current
      if (key === 'Home') next = 0
      else if (key === 'End') next = items.length - 1
      else if (current < 0) {
        // Focus on something that is not a stop (a card heading): step to the
        // nearest stop after or before it, not to the top of the list. With
        // nothing that way, do nothing, as at a real end of the list.
        const after = items.findIndex(
          (el) => target.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING,
        )
        if (key === 'ArrowDown') {
          if (after < 0) return
          next = after
        } else {
          if (after === 0) return
          next = after < 0 ? items.length - 1 : after - 1
        }
      } else if (key === 'ArrowDown') next = Math.min(current + 1, items.length - 1)
      else next = Math.max(current - 1, 0)
      // A marked radio at either end would otherwise fall through to the
      // browser's own radio arrows, which wrap and check a choice unasked.
      if (next !== current || choice) event.preventDefault()
      if (next !== current) items[next].focus()
    }

    root.addEventListener('keydown', onKeyDown)
    return () => root.removeEventListener('keydown', onKeyDown)
  }, [rootRef, enabled])
}

/** Text entry keeps its caret and option keys; only a marked radio or checkbox is a nav stop. */
function ownsArrowKeys(el: HTMLElement): boolean {
  if (el.closest('textarea, select, [contenteditable="true"]')) return true
  if (!(el instanceof HTMLInputElement)) return Boolean(el.closest('input'))
  const choice = el.type === 'radio' || el.type === 'checkbox'
  return !(choice && el.hasAttribute('data-od-nav'))
}
