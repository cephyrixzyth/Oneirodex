import { deleteJson, getJson, putJson } from './client'

declare global {
  interface Window {
    odPwaPrivacyReady?: Promise<boolean>
  }
}

export async function requirePrivateVrControl(signal?: AbortSignal) {
  const ready = await window.odPwaPrivacyReady
  const worker = navigator.serviceWorker?.controller
  const legacy = worker && new URL(worker.scriptURL, location.href).pathname === '/vr/sw.js'
  if (signal?.aborted) throw new DOMException('Request cancelled', 'AbortError')
  if (ready === false || (ready !== true && legacy)) {
    throw new Error('Reconnect and reload this page before opening the VR library.')
  }
}

export async function fetchVrCatalog({
  signal,
  page = 1,
  perPage = 48,
  vrCompat = '',
}: LooseProps = {}) {
  await requirePrivateVrControl(signal)
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  })
  if (vrCompat) params.set('vr_compat', String(vrCompat))
  return getJson(`/api/vr/catalog?${params}`, { signal, label: 'vr/catalog' })
}

export async function fetchVrGame(gameUuid: any, { signal }: LooseProps = {}) {
  await requirePrivateVrControl(signal)
  return getJson(`/api/vr/games/${encodeURIComponent(gameUuid)}`, {
    signal,
    label: 'vr/games',
  })
}

/** INSP-40 — one headset record per (game, kind). Deep link only. */
export interface VrProfile {
  kind: 'native' | 'injector' | 'flat'
  runtime: 'openxr' | 'openvr' | null
  profile_url: string | null
  notes: string
  source: 'librarian' | 'community'
  updated_at?: string | null
}

export interface VrProfileDraft {
  runtime?: 'openxr' | 'openvr' | null
  profile_url?: string | null
  notes?: string | null
  source?: 'librarian' | 'community'
}

function profilesUrl(gameUuid: string, kind?: string) {
  const base = `/api/games/${encodeURIComponent(gameUuid)}/vr_profiles`
  return kind ? `${base}/${encodeURIComponent(kind)}` : base
}

export async function fetchVrProfiles(gameUuid: string): Promise<VrProfile[]> {
  const data =
    (await getJson(profilesUrl(gameUuid), { label: 'Could not load the VR records' })) ?? {}
  return Array.isArray(data.vr_profiles) ? (data.vr_profiles as VrProfile[]) : []
}

export async function saveVrProfile(
  gameUuid: string,
  kind: VrProfile['kind'],
  draft: VrProfileDraft,
) {
  return putJson(profilesUrl(gameUuid, kind), draft, { label: 'Could not save the VR record' })
}

export async function removeVrProfile(gameUuid: string, kind: VrProfile['kind']) {
  return deleteJson(profilesUrl(gameUuid, kind), undefined, {
    label: 'Could not remove the VR record',
  })
}
