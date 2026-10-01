import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'

/**
 * Keep keyboard and D-pad users in place when a re-render removes the control
 * they were on (a panel closes, Sync turns into Stop, Undo goes away).
 *
 * Tracks whether the member's focus was last inside `rootRef`. After any
 * render, if it was and has fallen to the page (`<body>`), focus moves to
 * `pickTarget()`. The claim follows every focus change on the page, so focus
 * the member moved themselves (Tab, another card, a dialog) is never taken
 * back, and a pointer press anywhere gives it up. Focus that falls to `<body>`
 * with no new target is the removed or disabled control this recovers.
 *
 * `placeholderRef` names a stand-in (a card heading) this hook may park focus
 * on while nothing better exists; once `pickTarget()` offers something else,
 * focus moves on. Only a placeholder the hook parked on counts: a heading the
 * member focused themselves is left alone.
 */
export function useFocusRecovery(
  rootRef: RefObject<HTMLElement | null>,
  pickTarget: () => HTMLElement | null | undefined,
  placeholderRef?: RefObject<HTMLElement | null>,
) {
  const inside = useRef(false)
  const parked = useRef(false)
  const moving = useRef(false)
  const pick = useRef(pickTarget)
  pick.current = pickTarget

  // Registered at commit, not after paint, and seeded from where focus is now:
  // focus that lands before a passive effect would run must still count.
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return undefined
    inside.current = root.contains(document.activeElement)
    const onFocusIn = (event: FocusEvent) => {
      inside.current = root.contains(event.target as Node)
      if (!moving.current) parked.current = false
    }
    // A press comes before the focus change it causes; a press that focuses
    // something inside the root renews the claim through focusin.
    const onPointerDown = () => {
      inside.current = false
    }
    document.addEventListener('focusin', onFocusIn, true)
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('mousedown', onPointerDown, true)
    return () => {
      document.removeEventListener('focusin', onFocusIn, true)
      document.removeEventListener('pointerdown', onPointerDown, true)
      document.removeEventListener('mousedown', onPointerDown, true)
    }
  }, [rootRef])

  useEffect(() => {
    if (!inside.current) return
    const active = document.activeElement
    const placeholder = placeholderRef?.current ?? null
    const onPlaceholder = parked.current && placeholder !== null && active === placeholder
    if (active && active !== document.body && !onPlaceholder) return
    const target = pick.current()
    if (!target || target === active) return
    moving.current = true
    try {
      target.focus()
    } finally {
      moving.current = false
    }
    parked.current = target === placeholder
  })
}
