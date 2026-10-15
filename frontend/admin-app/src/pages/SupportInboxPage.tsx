// Toasts on every mutation (GT-B25).
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { DataTable } from '../components/DataTable'
import { MetricStrip } from '../components/opsWidgets'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import { Page } from '../components/Page'

interface SupportTicket {
  id: string
  severity?: string
  area?: string
  title?: string
  status?: string
  github_issue_number?: number
  github_issue_url?: string
  github_sync?: string
}

export function SupportInboxPage() {
  const [tickets, setTickets] = useState<SupportTicket[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [resolving, setResolving] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const resolveLock = useRef(false)

  // Derived rather than stored: a second piece of state would be one more thing
  // to keep in step with the list it counts.
  const openCount = tickets.filter((t) => t.status === 'open').length
  const syncedCount = tickets.filter((t) => t.github_issue_number).length

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      const data = await getJson('/api/support/tickets', { signal })
      if (!Array.isArray(data.tickets))
        throw new Error('Support inbox returned an invalid response.')
      if (!signal?.aborted) setTickets(data.tickets)
    } catch (err) {
      if (!signal?.aborted) setError(err)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  async function resolve(id: string) {
    if (resolveLock.current || loading) return
    resolveLock.current = true
    setResolving(id)
    setActionError(null)
    // Resolving used to give no feedback at all — the row simply vanished on
    // reload, which is indistinguishable from the click not registering.
    try {
      await postJson(`/api/support/tickets/${id}/resolve`)
      showToast('Ticket resolved.', 'success')
      await load()
    } catch (err) {
      const text = errorText(err) || 'Could not resolve the ticket.'
      setActionError(text)
      showToast(text, 'error')
    } finally {
      resolveLock.current = false
      setResolving(null)
    }
  }

  return (
    <Page
      title="Support inbox"
      lede="Member reports and their linked GitHub issues, when GitHub support is configured."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading support tickets…"
        error={error}
        onRetry={() => void load()}
      />
      <PageStatus error={actionError} />
      {!loading && !error ? (
        <>
          {/* UID-014 — the strip exists so every admin page answers "how bad is it"
          before you read the table. Open is the number that decides whether
          this page needs you, so it carries the tone; the totals are context
          and stay neutral. */}
          <MetricStrip
            label="Support"
            items={[
              {
                id: 'open',
                label: 'Open',
                value: openCount,
                hint: 'awaiting a reply',
                tone: openCount === 0 ? 'good' : openCount >= 10 ? 'action' : 'warning',
              },
              {
                id: 'resolved',
                label: 'Resolved',
                value: tickets.length - openCount,
                hint: 'closed tickets',
                tone: 'info',
              },
              {
                id: 'synced',
                label: 'On GitHub',
                value: syncedCount,
                hint: 'mirrored as issues',
                tone: 'info',
              },
            ]}
          />
          <DataTable
            caption="Support tickets"
            scrollLabel="Support tickets table"
            columns={[
              { key: 'id', label: 'ID', align: 'right' },
              { key: 'severity', label: 'Sev' },
              { key: 'area', label: 'Area' },
              { key: 'title', label: 'Title' },
              { key: 'status', label: 'Status' },
              {
                key: 'github',
                label: 'GitHub',
                // Sorts on the issue number, not the rendered link markup.
                value: (t) => t.github_issue_number ?? t.github_sync,
                render: (t) =>
                  t.github_issue_url ? (
                    <a href={t.github_issue_url} target="_blank" rel="noopener noreferrer">
                      #{t.github_issue_number}
                    </a>
                  ) : (
                    t.github_sync
                  ),
              },
              {
                key: 'actions',
                label: '',
                sortable: false,
                filterable: false,
                render: (t) =>
                  t.status === 'open' ? (
                    <Button
                      disabled={resolving !== null}
                      aria-label={`Resolve ${t.title || `ticket ${t.id}`}`}
                      onClick={() => void resolve(t.id)}
                    >
                      {resolving === t.id ? 'Resolving…' : 'Resolve'}
                    </Button>
                  ) : null,
              },
            ]}
            rows={tickets}
            getRowKey={(t) => t.id}
            emptyMessage="No tickets yet."
            dense
          />
        </>
      ) : null}
    </Page>
  )
}
