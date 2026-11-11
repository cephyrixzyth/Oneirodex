import { createOneirodexClient, type OneirodexClient } from '@oneirodex/api-client'
import type { AuthStore } from './auth.js'

export class DesktopTransportError extends Error {
  constructor(readonly cause: 'redirect_refused' | 'protocol') {
    super(
      cause === 'redirect_refused'
        ? 'Server API redirect refused. Check the server URL and sign-in requirements; current token access is unverified.'
        : 'Server API returned an unexpected response. Check the server URL and version.',
    )
    this.name = 'DesktopTransportError'
  }
}

/** Manual mode prevents forwarding; opaque redirects remain distinguishable from fetch failures. */
export function desktopControlFetch(fetchImpl: typeof fetch = fetch): typeof fetch {
  return async (input, init) => {
    const response = await fetchImpl(input, { ...init, redirect: 'manual' })
    if (
      response.type === 'opaqueredirect' ||
      response.redirected ||
      (response.status >= 300 && response.status < 400)
    ) {
      throw new DesktopTransportError('redirect_refused')
    }
    if (
      response.ok &&
      response.status !== 204 &&
      !response.headers.get('content-type')?.includes('application/json')
    ) {
      throw new DesktopTransportError('protocol')
    }
    return response
  }
}

export function createDesktopApi(auth: AuthStore, fetchImpl?: typeof fetch): OneirodexClient {
  const token = auth.getToken()
  return createOneirodexClient({
    baseUrl: auth.getBaseUrl(),
    getToken: () => token,
    fetchImpl: desktopControlFetch(fetchImpl),
  })
}

export type { OneirodexClient }
