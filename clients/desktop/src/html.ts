/**
 * HTML escaping for the template literals this client builds by hand.
 *
 * Lived as a module-private helper in app.ts, which is how a since-removed
 * assist overlay came to interpolate server-supplied strings into innerHTML
 * without it. Shared here so there is one implementation to import
 * rather than one to remember to copy.
 */
export function escapeHtml(value: string): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}
