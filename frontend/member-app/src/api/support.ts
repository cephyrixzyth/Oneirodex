/**
 * Member support tickets — the "Report an issue / an idea" form.
 *
 * Was a bare `fetch()` in ReportIssuePage's submit handler. Moved here in wave
 * B1.4 so it goes through `src/api/` and reports failures through the shared
 * envelope builder.
 */
import { postJson } from './client'

export async function submitSupportTicket(payload: any) {
  return (await postJson('/api/support/tickets', payload, { label: 'Submit failed' })) ?? {}
}

export async function previewSupportTicket(payload: any) {
  return (await postJson('/api/support/preview', payload, { label: 'Preview failed' })) ?? {}
}
