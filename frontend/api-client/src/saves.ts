import type { Requester } from './client.js'

/** One row of `/api/games/<uuid>/saves` — a libretro state or SRAM. */
export interface GameSave {
  id: number
  game_uuid: string
  /** `auto` (taken on leave), `cloud-state` (Sync now), `qs-<name>` (named), `cloud-sram` (battery). */
  slot_name: string
  filename: string
  size_bytes: number
  encrypted: boolean
  revision: number
  updated_at: string | null
  /** True for a resumable state; false for SRAM. */
  is_state: boolean
}

export interface GameSavesResponse {
  enabled: boolean
  game_uuid: string
  can_write_own_save: boolean
  can_delete_own_save: boolean
  /** Newest first. */
  saves: GameSave[]
}

/**
 * Emulator save states — per member, per game. Upload happens from the play
 * shell (multipart from the WebRetro bridge), so only list / delete live here.
 */
export function createSavesApi(request: Requester) {
  return {
    list(gameUuid: string, signal?: AbortSignal): Promise<GameSavesResponse> {
      return request<GameSavesResponse>(`/api/games/${encodeURIComponent(gameUuid)}/saves`, {
        signal,
      })
    },

    remove(gameUuid: string, slotName: string): Promise<{ status: string; slot_name: string }> {
      return request(
        `/api/games/${encodeURIComponent(gameUuid)}/saves/${encodeURIComponent(slotName)}`,
        { method: 'DELETE' },
      )
    },
  }
}

export type SavesApi = ReturnType<typeof createSavesApi>
