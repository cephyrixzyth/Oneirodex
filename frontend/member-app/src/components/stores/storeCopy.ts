import type { StoreConnection, StoreConnectionState } from '../../api/ownership'

/**
 * Copy and connect-form definitions for the store connection list (LIB-02).
 *
 * First-run and Settings render the same list from the same
 * `/api/ownership/connections` contract, so every sentence about a provider's
 * state lives here once. Credentials are pasted from the maintained launcher
 * tools each adapter already relies on (Heroic, Legendary, Nile,
 * xbox-authenticate, a signed-in browser for npsso). Oneirodex never asks for a
 * store password.
 */

export type ConnectField = {
  /** Request-body field the existing connect route reads. */
  name: string
  label: string
  kind: 'text' | 'numeric' | 'secret' | 'secret-multiline'
  placeholder?: string
  /** True when a live sync cannot run without it (the server still validates). */
  required?: boolean
  /** A sign-in token: never echoed back, never prefilled. */
  secret?: boolean
}

export const CONNECT_FIELDS: Record<string, ConnectField[]> = {
  steam: [
    {
      name: 'steam_id',
      label: 'Steam ID (64-bit)',
      kind: 'numeric',
      placeholder: '7656119…',
      required: true,
    },
  ],
  gog: [
    { name: 'gog_user_id', label: 'GOG user ID or label (optional)', kind: 'text' },
    {
      name: 'refresh_token',
      label: 'GOG refresh token (from Heroic or GOG Galaxy)',
      kind: 'secret',
      secret: true,
    },
  ],
  epic: [
    { name: 'epic_account_id', label: 'Epic account ID or label (optional)', kind: 'text' },
    {
      name: 'device_auth',
      label: 'Epic device auth JSON (from Legendary or Heroic)',
      kind: 'secret-multiline',
      placeholder: '{"account_id":"…","device_id":"…","secret":"…"}',
      secret: true,
    },
  ],
  amazon: [
    { name: 'amazon_user_id', label: 'Amazon user ID or label (optional)', kind: 'text' },
    {
      name: 'credential',
      label: 'Nile / Heroic user.json, or a refresh token',
      kind: 'secret-multiline',
      secret: true,
    },
    { name: 'device_serial', label: 'Device serial (if not inside the JSON)', kind: 'text' },
  ],
  xbox: [
    { name: 'xuid', label: 'Gamertag, XUID or label (optional)', kind: 'text' },
    {
      name: 'credential',
      label: 'xbox-webapi token JSON (written by xbox-authenticate)',
      kind: 'secret-multiline',
      secret: true,
    },
  ],
  psn: [
    { name: 'online_id', label: 'Online ID or label (optional)', kind: 'text' },
    {
      name: 'npsso',
      label: 'npsso token (from a signed-in PlayStation browser session)',
      kind: 'secret',
      secret: true,
    },
  ],
}

export type Tone = 'good' | 'info' | 'warn' | 'bad' | 'muted'

export const STATE_LABEL: Record<StoreConnectionState, string> = {
  unavailable: 'Not available',
  disabled: 'Turned off',
  import_only: 'Import only',
  not_configured: 'Needs server setup',
  not_connected: 'Not linked',
  needs_credential: 'Needs a sign-in',
  connected: 'Linked',
  syncing: 'Syncing',
  partial: 'Partly synced',
  reauth_required: 'Reconnect needed',
  failed: 'Sync failed',
  cancelled: 'Sync cancelled',
}

export const STATE_TONE: Record<StoreConnectionState, Tone> = {
  unavailable: 'muted',
  disabled: 'muted',
  import_only: 'info',
  not_configured: 'warn',
  not_connected: 'info',
  needs_credential: 'warn',
  connected: 'good',
  syncing: 'info',
  partial: 'warn',
  reauth_required: 'bad',
  failed: 'bad',
  cancelled: 'warn',
}

const SETUP_TEXT: Record<string, string> = {
  server_key:
    'Live sync needs a server key your administrator has not configured. Import a list instead. Saving your Steam ID still lets a free-game claim record the game and open Steam.',
  opt_in:
    'Live sync is an opt-in, unofficial integration that is off on this server. You can import a list instead.',
  client_package:
    'Live sync needs an optional server package your administrator has not installed. You can import a list instead.',
}

/** One plain sentence describing where this provider stands. */
export function stateSentence(connection: StoreConnection): string {
  const { state, records, last_sync: last } = connection
  switch (state) {
    case 'unavailable':
      return 'Oneirodex has no way to read this store yet. Nothing is offered that would not work.'
    case 'disabled':
      return 'Your administrator turned store ownership off.'
    case 'import_only':
      return connection.provider === 'playnite'
        ? 'Import a Playnite library export. It is a snapshot, correct as of the import.'
        : 'Import a list of what you own. It is a snapshot, correct as of the import.'
    case 'not_configured':
      return SETUP_TEXT[connection.setup.missing || ''] || 'Live sync is not set up on this server.'
    case 'not_connected':
      return 'Link your account to keep this list current, or import a list once.'
    case 'needs_credential':
      return 'Linked, but there is no sign-in a sync could use. Reconnect with one.'
    case 'syncing':
      return last?.cancel_requested
        ? 'Stopping at the next page…'
        : `Reading your library… ${last?.progress.items_seen ?? 0} titles so far.`
    case 'connected':
      if (last?.outcome?.reason === 'library_not_visible') return last.outcome.message
      return last
        ? `Last synced ${formatWhen(last.finished_at)} · ${last.synced ?? 0} titles.`
        : records.owned
          ? `${records.owned} titles recorded. Sync to refresh them.`
          : 'Linked. Sync to read your library.'
    case 'partial':
    case 'reauth_required':
    case 'failed':
    case 'cancelled':
      return last?.outcome?.message || STATE_LABEL[state]
    default:
      return ''
  }
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return 'just now'
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return 'recently'
  return at.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const CSV_HINT: Record<string, string> = {
  steam: 'appid,name\n570,Dota 2',
  gog: 'product_id,name\n1207658924,The Witcher 3',
  epic: 'catalog_item_id,name\nfn,Fortnite',
  amazon: 'product_id,name',
  xbox: 'title_id,name\n1234ABCD,Halo Infinite',
  psn: 'np_communication_id,name\nNPWR20188_00,Astro Bot',
  meta_quest: 'quest_id,name',
}

/** Where the credential a sync would use comes from, said plainly. */
export function credentialNote(connection: StoreConnection): string | null {
  const { source, household_available: household } = connection.credential
  if (!connection.account.connected) {
    // Nothing is linked, so nothing syncs yet. The server still reports which
    // sign-in a link would use; say what a blank token would do.
    return household && source !== 'not_required'
      ? 'If you leave the token blank, the household sign-in your server operator set up is used, and titles from that account are listed as yours.'
      : null
  }
  if (source === 'household') {
    return 'Syncing with the household sign-in your server operator set up. Titles from that account are listed as yours. Reconnect with your own sign-in to change that.'
  }
  if (source === 'member') {
    return 'Your sign-in is saved on the server. It is never shown again.'
  }
  if (source === 'unknown') {
    return 'This sign-in was saved before Oneirodex recorded whose it is, and it may be the household sign-in your server operator set up. Reconnect with your own sign-in to be sure the titles are yours.'
  }
  if (source === 'none' && household) {
    return 'If you leave the token blank, the household sign-in your server operator set up is used, and titles from that account are listed as yours.'
  }
  return null
}
