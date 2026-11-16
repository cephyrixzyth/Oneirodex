import { useEffect } from 'react'
import {
  burstToastMessages,
  groupLibraryScanToasts,
  markLibraryScanToastSeen,
  MAX_NARROW_INDIVIDUAL_TOASTS,
  pickUnseenLibraryScanToasts,
} from '@oneirodex/ui'
import { fetchNotificationSnapshot } from '../api/notifications'
import { showToast } from '../utils/toast'

const POLL_MS = 45000

/**
 * Soft-poll notifications for incremental library adds → top-right toast.
 * Silent when the endpoint is missing or the event kind is not ready yet.
 */
export function useLibraryScanToasts({ enabled = true, intervalMs = POLL_MS }: LooseProps = {}) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return undefined
    }

    let cancelled = false
    let timer = 0

    async function poll() {
      try {
        const data = await fetchNotificationSnapshot({ limit: 20 })
        if (cancelled || !data) {
          return
        }
        const rows = Array.isArray(data?.notifications)
          ? data.notifications
          : Array.isArray(data)
            ? data
            : []
        // One toast per library, not per increment (GT-B11). Narrow layouts
        // collapse after two libraries; wider layouts collapse after three, so
        // a burst cannot cover the page. Every row is marked seen to avoid
        // repeating the same notice.
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
        // Soft-fail — Backend event may not be wired yet.
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
