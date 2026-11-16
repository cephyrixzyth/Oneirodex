/** Return an absolute HTTP(S) URL safe to expose as a clickable external link. */
export function safeExternalUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const raw = value.trim()
  // eslint-disable-next-line no-control-regex -- Reject control bytes before URL parsing can normalize them.
  if (!raw || raw.length > 2048 || /[\u0000-\u001f\u007f]/.test(raw)) return null

  try {
    const url = new URL(raw)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null
    if (url.username || url.password) return null
    return url.href
  } catch {
    return null
  }
}
