import type { OfflineShelfIdentity } from './offline-shelf.js'
import { normalizeServerUrl, sha256Fingerprint } from './offline-shelf.js'

/** Opaque native binding; never persist the token or the identity object. */
export async function launchProfileBinding(identity: OfflineShelfIdentity): Promise<string | null> {
  const serverUrl = normalizeServerUrl(identity.serverUrl)
  if (!serverUrl || !identity.accountId || !identity.deviceId || !identity.token) return null
  return sha256Fingerprint(
    JSON.stringify([
      'oneirodex-launch-profile-v1',
      serverUrl,
      identity.accountId,
      identity.deviceId,
      await sha256Fingerprint(identity.token),
    ]),
  )
}
