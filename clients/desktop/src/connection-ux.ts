import type { LifecycleAction } from './lifecycle.js'

/** Companion reachability relative to the last successful Connect. */
export type ConnectionMode =
  'disconnected' | 'connecting' | 'online' | 'offline' | 'denied' | 'error'

export type CompanionUiAction =
  | LifecycleAction
  | 'play'
  | 'apply_patch'
  | 'apply_mods'
  | 'apply_mod_pack'
  | 'open_path'
  | 'reveal_path'

/** Actions that need a reachable Oneirodex server (download stream / patch stage). */
export function actionNeedsServer(action: CompanionUiAction): boolean {
  return (
    action === 'download' ||
    action === 'update' ||
    action === 'apply_patch' ||
    action === 'apply_mods' ||
    action === 'apply_mod_pack'
  )
}

/** True when the UI should block a button and explain reconnect. */
export function isActionBlockedOffline(action: CompanionUiAction, mode: ConnectionMode): boolean {
  if (mode === 'online') {
    return false
  }
  return actionNeedsServer(action)
}

export function offlineBlockReason(action: CompanionUiAction): string {
  if (!actionNeedsServer(action)) {
    return ''
  }
  return 'Server actions unavailable — reconnect to download, update, or apply mods/patches. Previously installed games can still Play or Reveal locally.'
}

export function connectionModeLabel(mode: ConnectionMode): string {
  switch (mode) {
    case 'online':
      return 'Online'
    case 'offline':
      return 'Offline (server unreachable)'
    case 'connecting':
      return 'Connecting'
    case 'denied':
      return 'Server access denied'
    case 'error':
      return 'Connection failed'
    case 'disconnected':
      return 'Not connected'
    default: {
      const _exhaustive: never = mode
      return _exhaustive
    }
  }
}

export type FriendsOpenHow = 'opened' | 'focused' | 'browser'

/** Block opening Friends when the server origin is unknown. */
export function friendsOpenBlockedReason(baseUrl: string): string | null {
  if (!baseUrl.trim()) {
    return 'Set Server URL first, then open Friends.'
  }
  return null
}

/**
 * Prefer the Server URL field the user sees over a stale auth store value.
 * Friends does not require Connect — the form is the source of truth.
 */
export function resolveFriendsBaseUrl(formUrl: string, authUrl: string): string {
  const fromForm = formUrl.trim()
  if (fromForm) {
    return fromForm
  }
  return authUrl.trim()
}

/** Status strip copy after Friends window open/focus (honest offline/auth). */
export function friendsOpenStatus(
  how: FriendsOpenHow,
  mode: ConnectionMode,
): { message: string; tone: 'info' | 'error' | 'success' } {
  if (how === 'focused') {
    if (mode === 'offline') {
      return {
        message:
          'Friends window focused — server unreachable; page may not load until the server is back.',
        tone: 'info',
      }
    }
    return { message: 'Friends popup focused (always on top, bottom-right).', tone: 'success' }
  }
  if (how === 'browser') {
    const suffix =
      mode === 'offline'
        ? ' Server may be unreachable.'
        : mode === 'disconnected'
          ? ' Sign in with your site account in that window.'
          : ''
    return { message: `Opened Friends in browser.${suffix}`, tone: 'info' }
  }
  if (mode === 'offline') {
    return {
      message:
        'Friends window opened — server unreachable; sign in with your site account when the page loads.',
      tone: 'info',
    }
  }
  if (mode === 'disconnected') {
    return {
      message:
        'Friends window opened — sign in with your site account in that window (companion Connect not required).',
      tone: 'info',
    }
  }
  return {
    message: 'Friends window opened — sign in once if prompted.',
    tone: 'success',
  }
}
