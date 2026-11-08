import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@oneirodex/ui'
import { submitSupportTicket } from '../api/support'
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

  async function submit(event: any) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const data = await submitSupportTicket({
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
      })
      setResult(data.ticket)
      setTitle('')
      setBody('')
      setLogs('')
      setSyncToGithub(false)
      setDetailsOpen(false)
      setLogsOpen(false)
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
          {result.github_sync === 'error' ? ' · GitHub sync failed (ticket kept)' : null}
          {' · '}
          <Link to="/notifications">Notifications</Link>
        </div>
      ) : null}

      <form className="od-report__form" onSubmit={submit}>
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

        <div className="od-report__actions">
          <Button type="submit" disabled={busy}>
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
