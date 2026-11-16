import { createSavesApi, type GameSave } from '@oneirodex/api-client'

import { memberResource, withMemberError } from './client'

export type { GameSave }

const saves = memberResource(createSavesApi)

/** Slot vocabulary the play shell writes — mirrors utils/emulator_saves.py. */
export const AUTO_STATE_SLOT = 'auto'
export const CLOUD_STATE_SLOT = 'cloud-state'
export const QUICK_SAVE_PREFIX = 'qs-'

export function slotLabel(slot: string): string {
  if (slot === AUTO_STATE_SLOT) return 'Where you left off'
  if (slot === CLOUD_STATE_SLOT || slot === 'cloud1') return 'Synced state'
  if (slot === 'cloud-sram') return 'Battery save'
  if (slot.startsWith(QUICK_SAVE_PREFIX))
    return slot.slice(QUICK_SAVE_PREFIX.length).replace(/-/g, ' ')
  return slot
}

/** Only the resumable rows, newest first (the API already orders them). */
export async function fetchSavedStates(
  gameUuid: string,
  { signal }: { signal?: AbortSignal } = {},
) {
  const body = await withMemberError(saves.list(gameUuid, signal), 'saved states')
  return {
    enabled: Boolean(body.enabled),
    canWrite: Boolean(body.can_write_own_save),
    canDelete: Boolean(body.can_delete_own_save),
    states: (body.saves || []).filter((row) => row.is_state),
  }
}

export async function deleteSavedState(gameUuid: string, slotName: string) {
  return withMemberError(saves.remove(gameUuid, slotName), 'delete saved state')
}

/** The play shell offers this slot first (it still asks before loading). */
export function resumeHref(playHref: string | null, slotName: string): string | null {
  if (!playHref) return null
  try {
    const url = new URL(playHref, window.location.origin)
    url.searchParams.set('resume', slotName)
    return `${url.pathname}${url.search}`
  } catch {
    return playHref
  }
}
