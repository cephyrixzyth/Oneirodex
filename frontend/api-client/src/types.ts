/** Shapes aligned with docs/openapi/openapi.json components.schemas */

export type ApiTokenScope =
  | 'read:library'
  | 'read:social'
  | 'write:presence'
  | 'write:download'
  | 'write:library'
  | 'write:saves'
  | 'admin'

export type ApiTokenPreset = 'companion' | 'thin'

export interface ApiTokenPublic {
  id: number
  name: string
  token_prefix: string
  scopes: ApiTokenScope[]
  created_at: string
  last_used_at: string | null
  revoked: boolean
}

export interface ApiError {
  error: string
}

/**
 * The failure envelope every route returns via `api_error` in
 * `oneirodex/utils/api_response.py`: `error` is always a human-readable string,
 * `error_code` a stable `snake_case` machine token (or `null` for a handful of
 * legacy 502 paths), `detail` optional structured extra for operators, and
 * `message` a legacy mirror of `error`.
 */
export interface ApiErrorEnvelope {
  ok: false
  error: string
  error_code: string | null
  detail?: unknown
  message?: string
}

/**
 * The success envelope: the route's payload merged at the top level with
 * `ok: true` and `error` / `error_code` present-and-null (see `api_ok`).
 */
export type ApiOk<T> = T & {
  ok: true
  error: null
  error_code: null
}

/** Discriminates an `ApiErrorEnvelope` from a success body or arbitrary JSON. */
export function isApiError(body: unknown): body is ApiErrorEnvelope {
  return (
    typeof body === 'object' &&
    body !== null &&
    (body as { ok?: unknown }).ok === false &&
    typeof (body as { error?: unknown }).error === 'string'
  )
}

export interface CreateTokenRequest {
  name: string
  scopes?: ApiTokenScope[]
  /** Shortcut: companion | thin (overrides scopes when set) */
  preset?: ApiTokenPreset
}

export interface CreateTokenResponse {
  token: ApiTokenPublic
  /** One-time secret; only returned on create */
  secret: string
  warning?: string
}

export interface ListTokensResponse {
  tokens: ApiTokenPublic[]
  valid_scopes: ApiTokenScope[]
  scope_presets: Record<string, { label?: string; scopes?: ApiTokenScope[] }>
}

export interface SearchResultItem {
  uuid: string
  name: string
  [key: string]: unknown
}

export interface SearchResponse {
  results?: SearchResultItem[]
  games?: SearchResultItem[]
  [key: string]: unknown
}

export interface CollectionSummary {
  id: number
  name: string
  [key: string]: unknown
}

export interface UpdatesInboxItem {
  /** The game's uuid — the inbox route writes `uuid`, not `game_uuid`. */
  uuid: string
  game_uuid?: string
  name?: string
  [key: string]: unknown
}

export interface UpdatesInboxResponse {
  behind?: UpdatesInboxItem[]
  items?: UpdatesInboxItem[]
  [key: string]: unknown
}

export interface StartPlaySessionRequest {
  game_uuid: string
  started_at?: string
  [key: string]: unknown
}

export interface PlaySessionResponse {
  id?: number
  game_uuid?: string
  started_at?: string
  [key: string]: unknown
}

export interface PlaytimeMeResponse {
  total_seconds?: number
  games?: Array<{
    game_uuid: string
    seconds?: number
    [key: string]: unknown
  }>
  [key: string]: unknown
}
