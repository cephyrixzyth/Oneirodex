import { useEffect, useState, type ReactNode } from 'react'
import { PageStatus, SessionEndedNotice, errorFromResponse } from '@oneirodex/ui'
import { requirePrivateVrControl } from './api/vr'

type Phase = 'checking' | 'ready' | 'ended'

/** An old HTML response must not bootstrap a different live browser account. */
export function VerifiedMemberBootstrap({
  accountId,
  children,
}: {
  accountId?: string
  children: ReactNode
}) {
  const [verification, setVerification] = useState<{ accountId?: string; phase: Phase }>({
    accountId,
    phase: 'checking',
  })
  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    let timeout: ReturnType<typeof window.setTimeout> | undefined
    setVerification({ accountId, phase: 'checking' })
    const finish = (phase: Phase) => {
      if (!signal.aborted) setVerification({ accountId, phase })
    }
    async function verify() {
      if (!accountId || accountId !== accountId.trim() || accountId.length > 128) {
        finish('ended')
        return
      }
      const worker = navigator.serviceWorker?.controller
      if (worker && new URL(worker.scriptURL, location.href).pathname === '/vr/sw.js') {
        await requirePrivateVrControl(signal)
      }
      if (signal.aborted) return
      timeout = window.setTimeout(() => {
        finish('ended')
        controller.abort()
      }, 10_000)
      const response = await fetch('/api/client/identity', {
        credentials: 'same-origin',
        cache: 'no-store',
        redirect: 'error',
        headers: { Accept: 'application/json' },
        signal,
      })
      if (!response.ok) throw await errorFromResponse(response, 'Check sign-in')
      const payload: unknown = await response.json()
      const matches =
        payload !== null &&
        typeof payload === 'object' &&
        !Array.isArray(payload) &&
        'account_id' in payload &&
        payload.account_id === accountId
      finish(matches ? 'ready' : 'ended')
    }
    void verify()
      .catch(() => finish('ended'))
      .finally(() => {
        if (timeout !== undefined) window.clearTimeout(timeout)
      })
    return () => {
      controller.abort()
      if (timeout !== undefined) window.clearTimeout(timeout)
    }
  }, [accountId])

  const phase = verification.accountId === accountId ? verification.phase : 'checking'
  if (phase === 'ready') return children
  if (phase === 'ended') return <SessionEndedNotice />
  return (
    <main className="od-session-ended" aria-busy="true">
      <PageStatus loading inline loadingMessage="Checking your sign-in…" />
    </main>
  )
}
