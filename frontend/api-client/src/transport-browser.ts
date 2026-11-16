import {
  joinUrl,
  OneirodexApiError,
  unwrapResponse,
  type OneirodexClientConfig,
  type Requester,
} from './client.js'

/**
 * Same-origin browser transport for the React SPAs (Phase 3, Track B).
 *
 * Differences from the default Bearer transport (`createRequester`):
 *
 *  - `credentials: 'include'` on every call — the session is a cookie, not a
 *    header.
 *  - `X-CSRFToken` is set on mutating requests (POST / PUT / PATCH / DELETE)
 *    from `config.csrfToken()`. The client never reads a SPA's token store —
 *    the SPA injects the getter.
 *  - `config.onUnauthorized()` fires once on a `401` or a followed redirect to
 *    the same-origin `/login` before `OneirodexApiError` is thrown, so the SPA
 *    can return to its sign-in route instead of consuming login HTML as data.
 *
 * `getToken` is not used here; pass a no-op (`() => null`) if the shared config
 * type requires it.
 */
export type BrowserTransportConfig = Omit<OneirodexClientConfig, 'getToken'> &
  Partial<Pick<OneirodexClientConfig, 'getToken'>>

const MUTATING = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function followedByAppLogin(response: Response, requestUrl: string, baseUrl: string): boolean {
  if (!response.redirected || !response.url) return false
  try {
    const fallback =
      baseUrl || (typeof window !== 'undefined' ? window.location.origin : response.url)
    const requestOrigin = new URL(requestUrl, fallback).origin
    const finalUrl = new URL(response.url, fallback)
    return finalUrl.origin === requestOrigin && finalUrl.pathname === '/login'
  } catch {
    return false
  }
}

export function createBrowserRequester(config: BrowserTransportConfig): Requester {
  const fetchImpl = config.fetchImpl ?? fetch

  return async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    if (!headers.has('Accept')) {
      headers.set('Accept', 'application/json')
    }

    const method = (init.method ?? 'GET').toUpperCase()
    if (MUTATING.has(method) && config.csrfToken && !headers.has('X-CSRFToken')) {
      headers.set('X-CSRFToken', config.csrfToken())
    }

    const url = joinUrl(config.baseUrl, path)
    const response = await fetchImpl(url, {
      ...init,
      headers,
      credentials: 'include',
    })

    const loginRedirect = followedByAppLogin(response, url, config.baseUrl)
    if ((response.status === 401 || loginRedirect) && config.onUnauthorized) {
      config.onUnauthorized()
    }

    if (loginRedirect && response.status !== 401) {
      throw new OneirodexApiError(401, {
        ok: false,
        error: 'Authentication required',
        error_code: 'unauthorized',
      })
    }

    return unwrapResponse<T>(response)
  }
}
