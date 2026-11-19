import type { Requester } from './client.js'

export interface InitiateDownloadResponse {
  representation?: 'companion_zip'
  download_id: number
  status: string
  stream_url: string
  kind?: string
  version_uuid?: string | null
}

export interface InitiateDownloadOptions {
  representation?: 'companion_zip'
  kind?: 'base' | 'update' | 'extra'
  versionUuid?: string
  version_uuid?: string
}

export interface GameVersionItem {
  kind: string
  id: string
  uuid: string
  label: string
  is_default: boolean
  size?: number | null
}

export function createDownloadsApi(request: Requester) {
  return {
    /** Create or reuse a download request for a game (Bearer + write:download). */
    initiateGameDownload(
      gameUuid: string,
      options: InitiateDownloadOptions = {},
    ): Promise<InitiateDownloadResponse> {
      const kind = options.kind ?? 'base'
      const version_uuid = options.versionUuid ?? options.version_uuid
      const body: Record<string, string> = { kind }
      if (options.representation) body.representation = options.representation
      if (version_uuid) {
        body.version_uuid = version_uuid
      }
      return request<InitiateDownloadResponse>(`/api/downloads/games/${gameUuid}`, {
        method: 'POST',
        body: JSON.stringify(body),
      })
    },

    listGameVersions(
      gameUuid: string,
    ): Promise<{ game_uuid: string; versions: GameVersionItem[] }> {
      return request(`/api/games/${gameUuid}/versions`)
    },
  }
}

export type DownloadsApi = ReturnType<typeof createDownloadsApi>
