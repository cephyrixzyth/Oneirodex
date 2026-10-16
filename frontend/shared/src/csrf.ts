/**
 * One CSRF token lookup for every api/ wrapper.
 *
 * Why this exists
 * ---------------
 * Fifteen modules carried their own copy and they had drifted into nine
 * distinct implementations, differing in exactly the place that matters — how
 * many fallbacks they try before giving up:
 *
 *   meta -> input -> #csrf_token  (9 modules)
 *   meta -> input                 (3 modules)
 *   meta only                     (2 modules)
 *
 * A module with the short chain silently sends an empty token on any page that
 * renders the field rather than the meta tag, and the request comes back 403
 * with nothing to say why. The chain below is the **superset**, so consolidating
 * widens every narrow copy and narrows none.
 *
 * `window.CSRFUtils` (setup/default_theme/js/csrf-utils.js) is preferred when
 * present: it has the same fallbacks plus a script-element source and a cache,
 * and it is what the server-rendered pages already use. Six of the fifteen
 * bypassed it for no stated reason; going through it is the consistent answer.
 */

export type HeaderMap = Record<string, string>

/** The classic theme's `setup/default_theme/js/csrf-utils.js` global, when present. */
interface CsrfUtils {
  getHeaders?: (extra?: HeaderMap) => HeaderMap
}

declare global {
  interface Window {
    CSRFUtils?: CsrfUtils
  }
}

/**
 * Read the CSRF token from the page.
 *
 * @returns the token, or '' when the page carries none
 */
export function getCsrfToken(): string {
  if (typeof document === 'undefined') {
    return ''
  }

  const meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
  if (meta?.content) {
    return meta.content
  }

  const input = document.querySelector<HTMLInputElement>('input[name="csrf_token"]')
  if (input?.value) {
    return input.value
  }

  return document.getElementById('csrf_token')?.textContent || ''
}

/** Update the shared meta token after a server-issued bootstrap response. */
export function setCsrfToken(token: string): void {
  if (typeof document === 'undefined') return
  let meta = document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'csrf-token'
    document.head.append(meta)
  }
  meta.content = token
}

/**
 * Build request headers carrying the CSRF token.
 *
 * @param extra additional headers merged over the token header
 * @returns headers object including `X-CSRFToken`
 */
export function csrfHeaders(extra: HeaderMap = {}): HeaderMap {
  // `typeof window` guard: the api modules are imported under vitest's node
  // environment too, where `window` is not always defined.
  if (typeof window !== 'undefined' && window.CSRFUtils?.getHeaders) {
    return window.CSRFUtils.getHeaders(extra)
  }

  return {
    'X-CSRFToken': getCsrfToken(),
    ...extra,
  }
}
