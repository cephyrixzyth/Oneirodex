/**
 * What the store screens need from a thrown API error, read without `any`.
 *
 * Member API wrappers throw an Error carrying `.status`, `.error_code` and the
 * response body as `.data`. The ownership routes put their catalogue sentence
 * in `data.detail.message` (never provider text), so that wins over the
 * generic message.
 */
export type ApiErrorInfo = { status?: number; message: string; aborted: boolean }

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

export function apiErrorInfo(error: unknown, fallback = 'Something went wrong.'): ApiErrorInfo {
  const err = record(error)
  const detail = record(record(err.data).detail)
  const message =
    typeof detail.message === 'string' && detail.message
      ? detail.message
      : typeof err.message === 'string' && err.message
        ? err.message
        : fallback
  return {
    status: typeof err.status === 'number' ? err.status : undefined,
    message,
    aborted: err.name === 'AbortError',
  }
}
