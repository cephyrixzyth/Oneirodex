import { useLayoutEffect, type RefObject } from 'react'

/** Reserve the actual wrapped header size without changing its own minimum height. */
export function useTopBarReserve(ref: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const header = ref.current
    if (!header) return
    const scope = header.closest<HTMLElement>('.od-shell') || document.body
    const measure = () => {
      const height = Math.ceil(header.getBoundingClientRect().height)
      if (height > 0) {
        const value = `${height}px`
        scope.style.setProperty('--od-topbar-reserve-h', value)
        // Toasts are portalled to body, outside the shell that owns the
        // measured header. Share its live height so notices can stay below
        // navigation even when the mobile bar wraps onto multiple rows.
        document.body.style.setProperty('--od-topbar-reserve-h', value)
      }
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(header)
    window.addEventListener('resize', measure)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', measure)
      scope.style.removeProperty('--od-topbar-reserve-h')
      document.body.style.removeProperty('--od-topbar-reserve-h')
    }
  }, [ref])
}
