import { useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@oneirodex/ui'
import {
  newSupportRequestId,
  previewSupportTicket,
  submitSupportTicket,
  type SupportPreview,
} from '../api/support'
import { PageStatus } from '../components/PageStatus'
import './ReportIssuePage.css'

const AREAS = [
  'auth',
  'library',
  'download',
  'webretro',
  'companion',
  'acquire',
  'social',
  'themes',
  'admin',
  'oidc',
  'security',
  'other',
]

/**
 * Seed the form from the query string, for reports opened from somewhere.
 *
 * The tile menu's "Report an issue" arrives with the game's name and its
 * details URL already known. Making the member retype them is how a report ends
 * up saying "the artwork is wrong" with no way to tell which of nine hundred
 * titles they meant.
 *
 * Only fields the form already owns, and `area` only when it is one of the
 * allowed values — a link is untrusted input like any other, and a bad `area`
 * would put the select into a state its own options cannot represent.
 */
export function prefillFromSearch(params: any) {
  const area = params.get('area')
  return {
    title: params.get('title') || '',
    url: params.get('url') || '',
    area: AREAS.includes(area) ? area : 'other',
  }
}

export function ReportIssuePage() {
  const [searchParams] = useSearchParams()
  const [seeded] = useState(() => prefillFromSearch(searchParams))
  const [title, setTitle] = useState(seeded.title)
  const [body, setBody] = useState('')
  const [area, setArea] = useState(seeded.area)
  const [kind, setKind] = useState('issue')
  const [severity, setSeverity] = useState('P2')
  const [deploy, setDeploy] = useState('Unraid')
  const [client, setClient] = useState('')
  const [url, setUrl] = useState(seeded.url)
  const [logs, setLogs] = useState('')
  const [syncToGithub, setSyncToGithub] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [preview, setPreview] = useState<SupportPreview | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [requestId, setRequestId] = useState(newSupportRequestId)
  const revision = useRef(0)

  function draft() {
    return {
      title,
      body,
      kind,
      area,
      severity,
      deploy_hint: deploy,
      client_hint: client,
      url_hint: url,
      logs,
      sync_to_github: syncToGithub,
      ...(requestId ? { request_id: requestId } : {}),
    }
  }

  async function previewGithub() {
    const capturedRevision = revision.current
    if (!title.trim()) {
      setError('Enter a title before previewing.')
      return
    }
    setPreviewBusy(true)
    setError(null)
    setPreview(null)
    try {
      const data = await previewSupportTicket(draft())
      if (revision.current !== capturedRevision) return
      setPreview(data.preview ?? null)
      if (data.preview?.request_id) setRequestId(data.preview.request_id)
    } catch (err: unknown) {
      if (revision.current === capturedRevision)
        setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setPreviewBusy(false)
    }
  }

  async function submit(event: any) {
    event.preventDefault()
    const approval = syncToGithub ? preview?.preview_token : undefined
    if (syncToGithub && (!preview?.available || !approval)) {
      setError('Preview this report and its destination before sending to GitHub.')
      return
    }
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await submitSupportTicket({
        ...draft(),
        ...(approval ? { preview_token: approval } : {}),
      })
      setResult(data.ticket)
      setTitle('')
      setBody('')
      setLogs('')
      setSyncToGithub(false)
      setDetailsOpen(false)
      setLogsOpen(false)
      setPreview(null)
      setRequestId(newSupportRequestId())
      revision.current += 1
    } catch (err: any) {
      setError(err.message || 'Submit failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="od-more-page od-report">
      <div className="od-page-header">
        <h1>Report</h1>
      </div>

      {error ? <PageStatus error={error} /> : null}
      {result ? (
        <div className="od-report__result" role="status">
          <strong>Ticket #{result.id} saved</strong>
          {result.github_sync === 'synced' && result.github_issue_url ? (
            <>
              {' · '}
              <a href={result.github_issue_url} target="_blank" rel="noopener noreferrer">
                GitHub #{result.github_issue_number}
              </a>
            </>
          ) : null}
          {result.github_sync === 'local_only'
            ? ' · Kept on this server; GitHub sync was not requested'
            : null}
          {result.github_sync === 'skipped'
            ? ' · GitHub sync unavailable; ticket stayed on this server'
            : null}
          {['sending', 'unknown', 'error'].includes(result.github_sync)
            ? ' · GitHub delivery is unconfirmed; it may already exist. Keep this ticket reference and do not send a new report. Ask an administrator to check the destination.'
            : null}
          {result.github_sync === 'pending'
            ? ' · GitHub delivery has not started; the local ticket is kept.'
            : null}
          {result.github_sync === 'rejected'
            ? ' · GitHub rejected this attempt; the local ticket is kept.'
            : null}
          {result.request_id ? <span> · Report reference: {result.request_id}</span> : null}
          {' · '}
          <Link to="/notifications">Notifications</Link>
        </div>
      ) : null}

      <form
        className="od-report__form"
        onSubmit={submit}
        onChangeCapture={() => {
          revision.current += 1
          setPreview(null)
        }}
      >
        <section className="od-report__primary" aria-label="Report details">
          {/* Asked first, because it changes what the rest of the form means.
              The page was headed "Report issue" and collected feature requests
              into the same pile, so triage had to read every title to sort
              them — and a request filed as a bug reads as a broken product. */}
          <fieldset className="od-report__kind">
            <legend className="od-report__kind-legend">What are you filing?</legend>
            <div className="od-report__kind-options">
              {[
                {
                  id: 'issue',
                  label: 'Something is broken',
                  hint: 'It does not work as it should',
                },
                { id: 'enhancement', label: 'An idea', hint: 'Something new, or better' },
              ].map((option) => (
                <label
                  key={option.id}
                  className="od-report__kind-option"
                  data-selected={kind === option.id ? 'true' : undefined}
                >
                  <input
                    type="radio"
                    name="report-kind"
                    value={option.id}
                    checked={kind === option.id}
                    onChange={() => setKind(option.id)}
                  />
                  <span className="od-report__kind-label">{option.label}</span>
                  <span className="od-report__kind-hint">{option.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="od-report__field">
            <span>Title</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={200}
              placeholder="Short summary"
            />
          </label>
          <label className="od-report__field">
            <span>Symptom</span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={3}
              placeholder="What you expected vs what you saw"
            />
          </label>
          <div className="od-report__row">
            <label className="od-report__field">
              <span>Area</span>
              <select value={area} onChange={(e) => setArea(e.target.value)}>
                {AREAS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <label className="od-report__field">
              <span>Severity</span>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                {['P0', 'P1', 'P2', 'P3'].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <details
          className="od-report__fold"
          open={detailsOpen}
          onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
        >
          <summary>Context (deploy, client, URL)</summary>
          {detailsOpen ? (
            <div className="od-report__fold-body">
              <div className="od-report__row">
                <label className="od-report__field">
                  <span>Deploy</span>
                  <select value={deploy} onChange={(e) => setDeploy(e.target.value)}>
                    {['Unraid', 'Compose', 'native', 'other'].map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="od-report__field">
                  <span>Client</span>
                  <input
                    value={client}
                    onChange={(e) => setClient(e.target.value)}
                    placeholder="browser / companion version"
                  />
                </label>
              </div>
              <label className="od-report__field">
                <span>URL</span>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="Page where it broke"
                />
              </label>
            </div>
          ) : null}
        </details>

        <details
          className="od-report__fold"
          open={logsOpen}
          onToggle={(e) => setLogsOpen(e.currentTarget.open)}
        >
          <summary>Logs &amp; extras (optional)</summary>
          {logsOpen ? (
            <div className="od-report__fold-body">
              <label className="od-report__field">
                <span>Logs (trimmed)</span>
                <textarea
                  value={logs}
                  onChange={(e) => setLogs(e.target.value)}
                  rows={6}
                  placeholder="Paste only the relevant lines"
                />
              </label>
            </div>
          ) : null}
        </details>

        <label className="od-report__github-opt-in">
          <input
            type="checkbox"
            checked={syncToGithub}
            onChange={(event) => setSyncToGithub(event.target.checked)}
          />
          <span>
            Also send this report to GitHub. This includes the report details, context, and any logs
            you provide, plus your account identifier and role. The server administrator configures
            the destination repository and its access.
          </span>
        </label>

        {syncToGithub ? (
          <section className="od-report__preview" aria-label="GitHub report preview">
            <p>
              Preview the destination and redacted report before sending. Local-only reporting is
              always available by clearing the GitHub option.
            </p>
            <Button type="button" disabled={busy || previewBusy} onClick={previewGithub}>
              {previewBusy ? 'Preparing preview…' : 'Preview GitHub report'}
            </Button>
            {preview ? (
              preview.available ? (
                <>
                  <p>
                    Destination: <strong>{preview.destination}</strong>. Repository visibility is
                    unknown; treat this report as potentially public.
                  </p>
                  <p>
                    Automatic redaction always applies and cannot recognize every private detail.
                    Review this text, edit the report if needed, then preview again. Your account
                    identifier and role are included below.
                  </p>
                  <h2>{preview.title}</h2>
                  <pre className="od-report__preview-text">{preview.body}</pre>
                </>
              ) : (
                <p role="status">
                  GitHub forwarding is unavailable. Clear the GitHub option to save this report
                  locally.
                </p>
              )
            ) : null}
          </section>
        ) : null}

        <div className="od-report__actions">
          <Button
            type="submit"
            disabled={
              busy ||
              (syncToGithub && (!preview?.available || !preview?.preview_token || previewBusy))
            }
          >
            {busy ? 'Sending…' : 'Submit ticket'}
          </Button>
          <Link className="od-report__help-link" to="/help">
            Help FAQ
          </Link>
        </div>
      </form>
    </div>
  )
}
