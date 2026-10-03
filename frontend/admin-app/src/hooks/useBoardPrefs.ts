import { useCallback, useState } from 'react'
import { loadIdSet, saveIdSet } from '../components/dashboardLayout'

/**
 * Per-board widget preferences: which widgets are pinned (locked in place) and
 * which are hidden. Stored beside the layout under `<key>:pinned` / `<key>:hidden`.
 * `defaultHidden` seeds the hidden set until the admin has made a choice, which
 * is how optional widgets stay off the board until they are added.
 */
export function useBoardPrefs(layoutKey: string, defaultHidden: readonly string[] = []) {
  const pinnedKey = `${layoutKey}:pinned`
  const hiddenKey = `${layoutKey}:hidden`
  const [pinned, setPinned] = useState<string[]>(() => loadIdSet(pinnedKey) ?? [])
  const [hidden, setHidden] = useState<string[]>(() => loadIdSet(hiddenKey) ?? [...defaultHidden])

  const togglePin = useCallback(
    (id: string) => {
      setPinned((prev) => {
        const next = prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]
        saveIdSet(pinnedKey, next)
        return next
      })
    },
    [pinnedKey],
  )

  const setHiddenIds = useCallback(
    (updater: (prev: string[]) => string[]) => {
      setHidden((prev) => {
        const next = updater(prev)
        saveIdSet(hiddenKey, next)
        return next
      })
    },
    [hiddenKey],
  )

  const hide = useCallback(
    (id: string) => setHiddenIds((prev) => (prev.includes(id) ? prev : [...prev, id])),
    [setHiddenIds],
  )
  const show = useCallback(
    (id: string) => setHiddenIds((prev) => prev.filter((v) => v !== id)),
    [setHiddenIds],
  )

  const reset = useCallback(() => {
    setPinned([])
    setHidden([...defaultHidden])
    try {
      window.localStorage?.removeItem(pinnedKey)
      window.localStorage?.removeItem(hiddenKey)
    } catch {
      /* private mode */
    }
  }, [defaultHidden, pinnedKey, hiddenKey])

  return { pinned, hidden, togglePin, hide, show, reset }
}
