import type { ApiError, ApiErrorEnvelope } from './types.js'

export interface OneirodexClientConfig {
  /** Origin or base URL, e.g. https://host.example (no trailing slash) */
  baseUrl: string
  /** Returns Bearer secret (`gt_…`) or null when unauthenticated */
  getToken: () => string | null | Promise<string | null>
  /** Inject for tests; defaults to global fetch */
  fetchImpl?: typeof fetch
  /**
   * Browser transport only: returns the current CSRF token, set as
   * `X-CSRFToken` on mutating requests. Injected by the caller — the client
   * never imports a SPA's token store. Ignored by the Bearer transport.
   */
  csrfToken?: () => string
  /**
   * Browser transport only: called once when a response is `401`, before the
   * `OneirodexApiError` is thrown. The SPA passes `() => { location.href =
   * '/login' }`. Ignored by the Bearer transport.
   */
  onUnauthorized?: () => void
}

/** Parsed error body: the full envelope, the legacy `{error}` shape, raw text, or null. */
export type ErrorBody = ApiErrorEnvelope | ApiError | string | null

function readEnvelopeError(body: ErrorBody): string | null {
  if (typeof body === 'object' && body !== null && typeof (body as ApiError).error === 'string') {
    return (body as ApiError).error
  }
  return null
}

function readEnvelopeCode(body: ErrorBody): string | null {
  if (
    typeof body === 'object' &&
    body !== null &&
    typeof (body as ApiErrorEnvelope).error_code === 'string'
  ) {
    return (body as ApiErrorEnvelope).error_code
  }
  return null
}

export class OneirodexApiError extends Error {
  readonly status: number
  /**
   * Stable `snake_case` token from the envelope's `error_code`
   * (`oneirodex/utils/api_response.py` `ERROR_CODES`), or `null` when the body
   * carried none (legacy 502s, raw text, non-JSON).
   */
  readonly error_code: string | null
  readonly body: ErrorBody

  constructor(status: number, body: ErrorBody) {
    super(readEnvelopeError(body) ?? `HTTP ${status}`)
    this.name = 'OneirodexApiError'
    this.status = status
    this.error_code = readEnvelopeCode(body)
    this.body = body
  }
}

/** Format value for Authorization header (Bearer gt_…). */
export function formatBearerAuthorization(token: string): string {
  const trimmed = token.trim()
  if (!trimmed) {
    throw new Error('Token must not be empty')
  }
  if (/^bearer\s+/i.test(trimmed)) {
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).replace(/^bearer/i, 'Bearer')
  }
  return `Bearer ${trimmed}`
}

export function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${base}${suffix}`
}

export async function parseErrorBody(response: Response): Promise<ErrorBody> {
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text) as ApiErrorEnvelope
  } catch {
    return text
  }
}

/**
 * The ok / throw / parse tail shared by every transport: turns a `Response`
 * into `T`, or throws `OneirodexApiError` carrying the parsed envelope. A
 * `204` or a non-JSON body resolves to `undefined`.
 */
export async function unwrapResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new OneirodexApiError(response.status, await parseErrorBody(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    return undefined as T
  }

  return (await response.json()) as T
}

export function createRequester(config: OneirodexClientConfig) {
  const fetchImpl = config.fetchImpl ?? fetch

  return async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers)
    if (!headers.has('Accept')) {
      headers.set('Accept', 'application/json')
    }

    const token = await config.getToken()
    if (token) {
      headers.set('Authorization', formatBearerAuthorization(token))
    }

    const response = await fetchImpl(joinUrl(config.baseUrl, path), {
      ...init,
      headers,
      // Bearer API calls must stay on the configured server origin. Redirects
      // can otherwise move an authenticated request to an unintended endpoint.
      redirect: 'error',
    })

    return unwrapResponse<T>(response)
  }
}

export type Requester = ReturnType<typeof createRequester>
