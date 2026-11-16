import type { useScanUnmatchedActions } from './useScanUnmatchedActions'
import type { useScanUnmatchedData } from './useScanUnmatchedData'

export type UnmatchedRow = {
  id: string | number
  folder_path?: string
  status?: string
  library_uuid?: string
  library_name?: string
  platform_name?: string
  rom_region?: string
  match_reason?: string
  match_score?: number | null
  suggested_kind?: string | null
  matched_game?: { name?: string; path?: string } | null
  folder_name?: string | null
  search_name?: string | null
  why_unmatched?: string | null
  unmatched_reason?: string | null
  bad_match_reason?: string | null
  suggested_candidate_name?: string | null
  is_bare_update_package?: boolean
  suggested_search_name?: string | null
  transforms?: Array<{ stage?: string; before?: string; after?: string; reason?: string }>
  stage_e_candidates?: Array<{ name?: string; source?: string; match_mode?: string }>
}
export type LibraryOption = { uuid: string; name: string; platform?: string }
export type LibraryApiRow = Partial<LibraryOption> & { platform_name?: string }
export type BadMatchReason = { id: string; label: string }
export type PageResult = { items?: UnmatchedRow[]; total?: number; count?: number }
export const entryLabel = (count: number) => (count === 1 ? 'entry' : 'entries')
export type ScanUnmatchedModel = ReturnType<typeof useScanUnmatchedData> &
  ReturnType<typeof useScanUnmatchedActions>
