/**
 * Member support tickets — the "Report an issue / an idea" form.
 *
 * Was a bare `fetch()` in ReportIssuePage's submit handler. Moved here in wave
 * B1.4 so it goes through `src/api/` and reports failures through the shared
 * envelope builder.
 */
import { postJson } from './client'

export interface SupportTicketDraft {
  title: string
  body?: string
  kind?: string
  area?: string
  severity?: string
  deploy_hint?: string
  client_hint?: string
  url_hint?: string
  logs?: string
  sync_to_github?: boolean
  request_id?: string
  preview_token?: string
}

export interface SupportPreview {
  available: boolean
  destination: string | null
  visibility: 'unknown'
  redaction: 'mandatory'
  preview_token: string | null
  request_id?: string
  title?: string
  body?: string
  labels?: string[]
}

/** Available on HTTP LAN installs too; randomUUID alone requires a secure context. */
export function newSupportRequestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join('-')
}

export async function submitSupportTicket(payload: SupportTicketDraft) {
  return (await postJson('/api/support/tickets', payload, { label: 'Submit failed' })) ?? {}
}

export async function previewSupportTicket(
  payload: SupportTicketDraft,
): Promise<{ preview?: SupportPreview }> {
  return (await postJson('/api/support/preview', payload, { label: 'Preview failed' })) ?? {}
}
