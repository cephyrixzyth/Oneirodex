import { useEffect } from 'react'
import {
  burstToastMessages,
  groupLibraryScanToasts,
  markLibraryScanToastSeen,
  MAX_NARROW_INDIVIDUAL_TOASTS,
  pickUnseenLibraryScanToasts,
} from '@oneirodex/ui'
import { showToast } from '../utils/toast'

const POLL_MS = 45000

/**
 * Same library-add toasts the member shell shows (UX-B7).
 * Staff spend the scan on admin pages; the digest must surface here too.
 */
export function useLibraryScanToasts({ enabled = true, intervalMs = POLL_MS } = {}) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return undefined
    }

    let cancelled = false
    let timer = 0

    async function poll() {
      try {
        const res = await fetch('/api/notifications?limit=20', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        })
        if (cancelled || !res.ok) {
          return
        }
        const data = await res.json().catch(() => null)
        const rows = Array.isArray(data?.notifications)
          ? data.notifications
          : Array.isArray(data)
            ? data
            : []
        const maxIndividual = window.matchMedia?.('(max-width: 40rem)').matches
          ? MAX_NARROW_INDIVIDUAL_TOASTS
          : undefined
        for (const burst of burstToastMessages(
          groupLibraryScanToasts(pickUnseenLibraryScanToasts(rows)),
          { maxIndividual },
        )) {
          if (burst.count > 1) {
            showToast(
              burst.message,
              'success',
              maxIndividual === undefined
                ? { count: burst.count }
                : { count: burst.count, maxIndividual },
            )
          } else if (maxIndividual === undefined) {
            showToast(burst.message, 'success')
          } else {
            showToast(burst.message, 'success', { maxIndividual })
          }
          for (const row of burst.rows) {
            markLibraryScanToastSeen(row.id ?? row.uuid ?? row.created_at ?? row.title)
          }
        }
      } catch {
        // Soft-fail — endpoint missing or a page stub that rejects unknown URLs.
      }
    }

    void poll()
    timer = window.setInterval(() => {
      void poll()
    }, intervalMs)

    function onFocus() {
      void poll()
    }
    window.addEventListener('focus', onFocus)

    return () => {
      cancelled = true
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
    }
  }, [enabled, intervalMs])
}
