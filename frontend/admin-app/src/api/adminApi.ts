/**
 * Admin SPA fetch helpers — the thin admin wrapper (401 redirect, JSON verbs)
 * now sitting on `@oneirodex/api-client`'s browser transport (PR-4c) instead
 * of a hand-rolled `fetch`.
 *
 * `createBrowserRequester` already provides everything this file used to do
 * by hand: `credentials: 'include'`, `X-CSRFToken` on mutating verbs (from the
 * injected `getCsrfToken`), and `onUnauthorized()` on a 401. Exported under
 * the names admin call sites already use so their imports do not move.
 */
import { getCsrfToken, csrfHeaders, errorFromBody } from '@oneirodex/ui'
import { createBrowserRequester, OneirodexApiError } from '@oneirodex/api-client'

/** @deprecated import { getCsrfToken } from '@oneirodex/ui' — kept for admin call sites. */
export { getCsrfToken as csrfToken, csrfHeaders }

/**
 * Build an Error from a failed admin response.
 *
 * Delegates to the shared `errorFromBody`, which keeps `status` / `error_code`
 * / `data` on the Error and prefers `data.error` then `data.message` for the
 * sentence. Same signature `(data, status, label)`. Still exported: components
 * that build their own request by hand (`SystemResetPanel`) import this
 * directly.
 */
export const adminError = errorFromBody

const request = createBrowserRequester({
  baseUrl: '',
  // Looked up per call, not captured at module-load time — admin vitest
  // suites `vi.stubGlobal('fetch', ...)` / reassign `global.fetch` per test,
  // after this module (and its `createBrowserRequester` call) is already
  // loaded. Binding to `fetch` directly here would freeze on whatever the
  // global was at import time and never see those stubs.
  fetchImpl: (input, init) => fetch(input, init),
  csrfToken: getCsrfToken,
  onUnauthorized: () => {
    window.location.href = adminLoginUrl()
  },
})

export function adminLoginUrl(
  pathname = window.location.pathname,
  search = window.location.search,
  hash = window.location.hash,
) {
  const next = `${pathname}${search}${hash}`
  return `/login?next=${encodeURIComponent(next)}`
}

/**
 * Re-throw a failed `request()` call as the `adminError` shape (an `Error`
 * with `.status` / `.error_code` / `.data`) call sites already expect, rather
 * than leaking `OneirodexApiError` (`.body`, no `.data`) up to them.
 */
function rethrowAsAdminError(err: unknown, label: string): never {
  if (err instanceof OneirodexApiError) {
    throw adminError(err.body as Record<string, unknown> | null, err.status, label)
  }
  throw err
}

// `data` stays inferred `any` throughout, matching the pre-rewire behaviour:
// the admin envelope is loose and each consumer narrows at its use site.
// Tightening this to a shared response type is a follow-up once the
// pages/components are annotated.

export async function getJson(url: string, { signal }: { signal?: AbortSignal } = {}) {
  try {
    return await request<any>(url, { signal })
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}

export async function postJson(url: string, body?: unknown) {
  try {
    return await request<any>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    })
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}

/** Multipart POST. The browser transport adds CSRF without overriding the
 * boundary-bearing Content-Type generated for FormData. */
export async function postForm<T = unknown>(url: string, body: FormData): Promise<T> {
  try {
    return await request<T>(url, { method: 'POST', body })
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}

/** Multipart PUT with the same cookie and CSRF handling as JSON requests. */
export async function putForm<T = unknown>(url: string, body: FormData): Promise<T> {
  try {
    return await request<T>(url, { method: 'PUT', body })
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}

/**
 * POST JSON and return `{ ok, status, data }` without throwing on 4xx/5xx
 * (still redirects on 401, via the transport's `onUnauthorized`). Used for
 * scan conflict / 409 recovery.
 */
export async function postJsonResult(url: string, body?: unknown) {
  try {
    const data = await request<any>(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    })
    return { ok: true, status: 200, data }
  } catch (err) {
    if (err instanceof OneirodexApiError) {
      return { ok: false, status: err.status, data: err.body ?? {} }
    }
    throw err
  }
}

export async function putJson(url: string, body?: unknown) {
  try {
    return await request<any>(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    })
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}

export async function deleteJson(url: string, body?: unknown) {
  const init: RequestInit = { method: 'DELETE' }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  try {
    return await request<any>(url, init)
  } catch (err) {
    return rethrowAsAdminError(err, url)
  }
}
