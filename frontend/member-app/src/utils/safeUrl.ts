/**
 * Allow only http(s) absolute URLs for external links (blocks javascript: etc.).
 */
export function safeHttpUrl(url: unknown): string | null {
  if (!url || typeof url !== 'string') {
    return null
  }

  try {
    const parsed = new URL(url, window.location.origin)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href
    }
  } catch {
    return null
  }

  return null
}

// Store launcher deeplinks the server builds for claim assist:
// steam://openurl/<https url> and com.epicgames.launcher://...
const STORE_LAUNCHER_PROTOCOLS = new Set(['steam:', 'com.epicgames.launcher:'])

/**
 * http(s) plus the store launcher deeplinks claim assist hands back. Anything
 * else (javascript:, data:, vbscript:, file:) is refused, so a hostile feed
 * cannot reach window.open. Parsed with URL, the same parser navigation uses, so
 * padding or tab tricks inside the scheme do not get past it.
 */
export function safeClaimUrl(url: unknown): string | null {
  const http = safeHttpUrl(url)
  if (http) {
    return http
  }
  if (!url || typeof url !== 'string') {
    return null
  }

  try {
    const parsed = new URL(url)
    if (STORE_LAUNCHER_PROTOCOLS.has(parsed.protocol)) {
      return url.trim()
    }
  } catch {
    return null
  }

  return null
}
