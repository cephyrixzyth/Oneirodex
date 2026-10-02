import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, useViewer } from '@oneirodex/ui'
import { fetchOwnershipConnections } from '../../api/ownership'
import './StoreConnections.css'

const KEY = 'od.storeSetup.dismissed.'

export function storeSetupDismissed(userId: unknown): boolean {
  try {
    return window.localStorage?.getItem(KEY + String(userId ?? 'anon')) === '1'
  } catch {
    return false
  }
}

export function dismissStoreSetup(userId: unknown) {
  try {
    window.localStorage?.setItem(KEY + String(userId ?? 'anon'), '1')
  } catch {
    /* private mode: the prompt simply shows again next visit */
  }
}

/**
 * First-run nudge on the Library (LIB-02): shown only to a member who has not
 * linked or imported anything, and only while store ownership is on. It is a
 * convenience, so any failure to read status renders nothing rather than an
 * error on the page someone came to browse.
 */
export function StoreSetupPrompt({
  t = (key: string) => key,
}: {
  t?: (key: string, vars?: Record<string, unknown>) => string
}) {
  const viewer = useViewer()
  const [show, setShow] = useState(false)

  useEffect(() => {
    if (storeSetupDismissed(viewer.userId)) return undefined
    const controller = new AbortController()
    fetchOwnershipConnections({ signal: controller.signal })
      .then((status) => {
        const started = status.connections.some((c) => c.account.connected || c.records.owned > 0)
        setShow(Boolean(status.sync_enabled) && !started)
      })
      .catch(() => setShow(false))
    return () => controller.abort()
  }, [viewer.userId])

  if (!show) return null
  return (
    <aside className="od-store-setup-prompt" aria-label={t('Store setup')}>
      <p>
        {t(
          'Link your game stores or import a list, and the library will mark what you already own.',
        )}
      </p>
      <div className="od-store-setup-prompt__actions">
        <Link className="od-btn od-btn--sm od-btn--primary" to="/welcome">
          {t('Set up stores')}
        </Link>
        <Button
          size="sm"
          variant="quiet"
          onClick={() => {
            dismissStoreSetup(viewer.userId)
            setShow(false)
          }}
        >
          {t('Not now')}
        </Button>
      </div>
    </aside>
  )
}
