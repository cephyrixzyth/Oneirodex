import { formatBearerAuthorization } from '@oneirodex/api-client'

import { checkServerUrl } from './transport-policy.js'

/** OS / secure-store persistence for the API token. */
export interface KeychainAdapter {
  load(): Promise<string | null>
  save(token: string): Promise<void>
  clear(): Promise<void>
}

export interface AuthConfig {
  baseUrl: string
  token?: string | null
  keychain?: KeychainAdapter
}

export interface AuthSnapshot {
  baseUrl: string
  hasToken: boolean
}

export function createAuthStore(initial?: Partial<AuthConfig>) {
  let baseUrl = initial?.baseUrl ? requireSecureBaseUrl(initial.baseUrl) : ''
  let token: string | null = initial?.token ?? null

  return {
    getBaseUrl(): string {
      return baseUrl
    },

    /**
     * Throws for a server the token must not be sent to (plain `http://` on a
     * public host, other schemes). The store is the only source of the base URL
     * every request is built from, so refusing here covers them all.
     */
    setBaseUrl(nextBaseUrl: string): void {
      baseUrl = requireSecureBaseUrl(nextBaseUrl)
    },

    getToken(): string | null {
      return token
    },

    setToken(nextToken: string | null): void {
      token = nextToken
    },

    /** Load token from the OS secure store when an adapter is provided. */
    async hydrateFromKeychain(keychain?: KeychainAdapter): Promise<void> {
      if (!keychain) {
        return
      }
      const stored = await keychain.load()
      if (stored) {
        token = stored
      }
    },

    /** Persist token to the OS secure store when an adapter is provided. */
    async persistToKeychain(keychain?: KeychainAdapter): Promise<void> {
      if (!keychain) {
        return
      }
      if (token) {
        await keychain.save(token)
      } else {
        await keychain.clear()
      }
    },

    snapshot(): AuthSnapshot {
      return {
        baseUrl,
        hasToken: Boolean(token),
      }
    },

    /** Authorization header value for API requests. */
    authorizationHeader(): string | null {
      if (!token) {
        return null
      }
      return formatBearerAuthorization(token)
    },
  }
}

export type AuthStore = ReturnType<typeof createAuthStore>

export function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.trim().replace(/\/+$/, '')
}

/**
 * `normalizeBaseUrl` plus the transport policy: `https://` anywhere, `http://`
 * only for loopback / private-LAN hosts (see `transport-policy.ts`). Returns ''
 * for a blank URL; throws an Error carrying the user-facing reason otherwise.
 * UI code should call `checkServerUrl` first to show that reason without throwing.
 */
export function requireSecureBaseUrl(baseUrl: string): string {
  const normalized = normalizeBaseUrl(baseUrl)
  if (!normalized) {
    return ''
  }
  const checked = checkServerUrl(normalized)
  if (!checked.ok) {
    throw new Error(checked.message)
  }
  return normalized
}

/** BOM / zero-width / soft-hyphen often sneak in on clipboard paste. */
const INVISIBLE_CHARS = /[\u200B-\u200D\uFEFF\u00AD]/g

/**
 * Oneirodex API token shape from server `generate_api_token` /
 * `secrets.token_urlsafe`: `gt_<hexprefix>_<urlsafe-secret>`.
 * Secret may include `-` and `_` — never truncate at the last hyphen.
 */
export const ONEIRODEX_TOKEN_RE = /gt_[a-zA-Z0-9]+_[A-Za-z0-9_-]+/

/**
 * UI chrome sometimes glues onto the secret without a space (`…Copy`).
 * Do **not** strip words like `secret`/`token` — those can appear in urlsafe output.
 */
const GLUED_UI_SUFFIX_RE = /(?:Copy(?:ed)?!?)$/i

function stripWrappingQuotes(value: string): string {
  let next = value
  if (
    (next.startsWith('"') && next.endsWith('"')) ||
    (next.startsWith("'") && next.endsWith("'")) ||
    (next.startsWith('`') && next.endsWith('`'))
  ) {
    next = next.slice(1, -1).replace(INVISIBLE_CHARS, '').trim()
  }
  return next
}

function looksLikeOneirodexToken(value: string): boolean {
  if (!value.startsWith('gt_')) {
    return false
  }
  const body = value.slice('gt_'.length)
  const sep = body.indexOf('_')
  if (sep <= 0) {
    return false
  }
  const prefix = body.slice(0, sep)
  const secret = body.slice(sep + 1)
  if (!prefix || !secret) {
    return false
  }
  if (!/^[a-zA-Z0-9]+$/.test(prefix)) {
    return false
  }
  // token_urlsafe charset: A-Za-z0-9 _ -  (hyphens mid/end are valid)
  if (!/^[A-Za-z0-9_-]+$/.test(secret)) {
    return false
  }
  return true
}

function refineExtractedToken(candidate: string): string {
  let next = candidate
  // Peel glued Copy/Copied only when the remainder is still a valid token.
  const withoutUi = next.replace(GLUED_UI_SUFFIX_RE, '')
  if (withoutUi !== next && looksLikeOneirodexToken(withoutUi)) {
    next = withoutUi
  }
  return next
}

/**
 * Suffix after a regex match is safe when the secret ended on a clear boundary
 * (whitespace) or only known clipboard/UI chrome remains glued on.
 * Reject when more secret-looking material follows a bad char (e.g. `!chars`)
 * — that would truncate into a false-positive shape.
 */
function isSafeExtractionSuffix(after: string): boolean {
  if (!after) {
    return true
  }
  // Space/newline already collapsed to spaces — whitespace means the secret ended.
  if (/^\s/.test(after)) {
    return true
  }
  if (/^(?:(?:\.{2,3}|…|Copy(?:ed)?!?|<\/?[a-zA-Z][^>]*>)+)$/i.test(after)) {
    return true
  }
  if (/^[.…·•]+$/.test(after)) {
    return true
  }
  return false
}

/**
 * Trim paste noise before validating or storing a Oneirodex API token.
 * Strips BOM/zero-width, surrounding whitespace/newlines, wrapping quotes,
 * and extracts the first `gt_…` match when the paste includes labels/HTML/junk.
 * Does **not** truncate at the last `-` inside the urlsafe secret.
 */
export function normalizeOneirodexToken(raw: string): string {
  let value = raw.replace(INVISIBLE_CHARS, '')
  // Collapse clipboard newlines / tabs to spaces, then trim ends.
  value = value.replace(/[\r\n\t]+/g, ' ').trim()
  value = stripWrappingQuotes(value)

  if (looksLikeOneirodexToken(value)) {
    return value
  }

  // Paste may be "API token: gt_…", HTML, or label + secret + junk.
  // Take the first well-shaped match — never split the secret on `-`.
  const match = ONEIRODEX_TOKEN_RE.exec(value)
  if (match?.[0] != null && match.index != null) {
    const after = value.slice(match.index + match[0].length)
    if (isSafeExtractionSuffix(after)) {
      const extracted = refineExtractedToken(match[0])
      if (looksLikeOneirodexToken(extracted)) {
        return extracted
      }
    }
  }

  return value
}

/**
 * Client-side shape check aligned with server `generate_api_token` /
 * `verify_bearer_token`: `gt_` + prefix + `_` + urlsafe secret.
 * Secret may contain `_` and `-` (`secrets.token_urlsafe`).
 */
export function isOneirodexToken(token: string): boolean {
  return looksLikeOneirodexToken(normalizeOneirodexToken(token))
}

/** Short diagnostic for companion console (never logs the secret). */
export function describeTokenPaste(raw: string): string {
  const normalized = normalizeOneirodexToken(raw)
  const rawLen = raw.length
  const normLen = normalized.length
  const shapeOk = looksLikeOneirodexToken(normalized)
  const prefixMatch = normalized.match(/^gt_([a-zA-Z0-9]+)_/)
  const prefix = prefixMatch?.[1] ?? '(none)'
  const endsWithHyphen = normalized.endsWith('-')
  return `token paste: rawLen=${rawLen} normLen=${normLen} shapeOk=${shapeOk} prefix=${prefix} endsWithHyphen=${endsWithHyphen}`
}
