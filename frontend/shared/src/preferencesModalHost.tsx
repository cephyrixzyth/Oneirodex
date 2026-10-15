import { useEffect, useState, type ReactNode } from 'react'
import { PreferencesModal } from './PreferencesModal.js'

const OPEN_EVENT = 'od:open-preferences'

/** Ask the shell-owned React dialog to open. */
export async function openPreferencesModal(): Promise<void> {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

/** Mount once in each SPA shell so all Preferences entry points share one dialog. */
export function PreferencesModalHost(): ReactNode {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(OPEN_EVENT, show)
    return () => window.removeEventListener(OPEN_EVENT, show)
  }, [])
  return <PreferencesModal open={open} onClose={() => setOpen(false)} />
}
