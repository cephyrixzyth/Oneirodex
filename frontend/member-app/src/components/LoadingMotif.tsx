import { LOADING_MOTIF_IDS, normalizeLoadingMotifId } from '@oneirodex/ui/loadingMotifs'

export {
  LOADING_MOTIF_IDS,
  LoadingMotif,
  normalizeLoadingMotifId,
} from '@oneirodex/ui/loadingMotifs'

export function pickLoadingMotifId(settings: any, sessionPick: any) {
  const mode = settings?.loading_icon_mode || 'rotate'
  const locked = normalizeLoadingMotifId(settings?.resolved_id || settings?.loading_icon_id)
  if (mode === 'lock' && locked) {
    return locked
  }
  if (sessionPick && normalizeLoadingMotifId(sessionPick)) {
    return sessionPick
  }
  let pool = LOADING_MOTIF_IDS
  if (Array.isArray(settings?.catalogue) && settings.catalogue.length) {
    const fromApi = settings.catalogue
      .map((row: any) => normalizeLoadingMotifId(row?.id))
      .filter(Boolean)
    if (fromApi.length) {
      pool = fromApi
    }
  }
  return pool[Math.floor(Math.random() * pool.length)]
}
