/** Same-origin sign-out signals carry only an opaque epoch, never identity data. */
export const AUTH_BOUNDARY_KEY = 'od.auth.boundary.v1'
export const AUTH_BOUNDARY_EVENT = 'od-auth-boundary'
const CHANNEL = 'od-auth-boundary-v1'
let sequence = 0

export function readAuthBoundaryEpoch(): string | null | undefined {
  try {
    return window.localStorage.getItem(AUTH_BOUNDARY_KEY)
  } catch {
    return undefined
  }
}

function writableStorage() {
  const probe = `${AUTH_BOUNDARY_KEY}.probe`
  try {
    window.localStorage.setItem(probe, '1')
    window.localStorage.removeItem(probe)
    return true
  } catch {
    return false
  }
}

function openChannel(): BroadcastChannel | undefined {
  try {
    return new window.BroadcastChannel(CHANNEL)
  } catch {
    return undefined
  }
}

function closeChannel(channel: BroadcastChannel | undefined) {
  try {
    channel?.close()
  } catch {
    // Optional browser messaging must not break sign-out or teardown.
  }
}

export function notifyAuthBoundary() {
  if (typeof window === 'undefined') return
  let epoch = `${Date.now().toString(36)}-${++sequence}`
  try {
    epoch += `-${window.crypto.getRandomValues(new Uint32Array(4)).join('-')}`
  } catch {
    // This is a change notification, not an authentication credential.
  }
  try {
    window.localStorage.setItem(AUTH_BOUNDARY_KEY, epoch)
  } catch {
    // Local delivery and BroadcastChannel remain available with blocked storage.
  }
  window.dispatchEvent(new Event(AUTH_BOUNDARY_EVENT))
  const channel = openChannel()
  try {
    channel?.postMessage({ type: 'session-ended', epoch })
  } catch {
    // Storage can still notify other documents when messaging is restricted.
  } finally {
    closeChannel(channel)
  }
}

export function subscribeAuthBoundary(
  onEnded: () => void,
  initialEpoch: string | null | undefined,
) {
  const channel = openChannel()
  const canObserve = () => Boolean(channel) || writableStorage()
  function checkEpoch() {
    const current = readAuthBoundaryEpoch()
    if ((current !== undefined && current !== initialEpoch) || !canObserve()) onEnded()
  }
  function onStorage(event: StorageEvent) {
    if (event.key === AUTH_BOUNDARY_KEY || event.key === null) checkEpoch()
  }
  function onMessage(event: MessageEvent) {
    const data: unknown = event.data
    if (!data || typeof data !== 'object') return
    const message = data as { type?: unknown; epoch?: unknown }
    if (
      message.type === 'session-ended' &&
      typeof message.epoch === 'string' &&
      message.epoch.length > 0 &&
      message.epoch.length <= 256 &&
      message.epoch !== initialEpoch
    )
      onEnded()
  }
  function onBlur() {
    // Without either cross-document channel, don't retain a private view when
    // leaving it for another account. Fresh navigation checks the server again.
    if (!canObserve()) onEnded()
  }
  function onVisibility() {
    if (document.visibilityState === 'visible') checkEpoch()
    else onBlur()
  }
  function onPageShow(event: PageTransitionEvent) {
    if (event.persisted && readAuthBoundaryEpoch() === undefined) onEnded()
    else checkEpoch()
  }
  window.addEventListener(AUTH_BOUNDARY_EVENT, onEnded)
  window.addEventListener('storage', onStorage)
  window.addEventListener('focus', checkEpoch)
  window.addEventListener('blur', onBlur)
  window.addEventListener('pageshow', onPageShow)
  document.addEventListener('visibilitychange', onVisibility)
  channel?.addEventListener('message', onMessage)
  // Cover a boundary occurring between initial render and effect subscription.
  if (readAuthBoundaryEpoch() !== initialEpoch) onEnded()
  return () => {
    window.removeEventListener(AUTH_BOUNDARY_EVENT, onEnded)
    window.removeEventListener('storage', onStorage)
    window.removeEventListener('focus', checkEpoch)
    window.removeEventListener('blur', onBlur)
    window.removeEventListener('pageshow', onPageShow)
    document.removeEventListener('visibilitychange', onVisibility)
    channel?.removeEventListener('message', onMessage)
    closeChannel(channel)
  }
}
