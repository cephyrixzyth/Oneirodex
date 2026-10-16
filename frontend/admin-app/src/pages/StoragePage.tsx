import { useEffect, useState } from 'react'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { MetricStrip } from '../components/opsWidgets'
import { PageStatus, Button } from '@oneirodex/ui'
import { Page } from '../components/Page'

interface StorageStatus {
  helpers_enabled: boolean
  allow_apply: boolean
  games_path: string
  games_exists: boolean
  games_readable: boolean
  games_writable: boolean
  degrade_reason: string | null
}

interface HardlinkResult {
  applied?: boolean
  would_succeed?: boolean
  ok?: boolean
  same_volume?: boolean
  bytes_saved_estimate?: number
  reasons?: string[]
  source?: string
  dest?: string
}

const EMPTY_STATUS: StorageStatus = {
  helpers_enabled: false,
  allow_apply: false,
  games_path: '',
  games_exists: false,
  games_readable: false,
  games_writable: false,
  degrade_reason: null,
}

function formatBytes(n: unknown) {
  const value = Number(n) || 0
  if (value <= 0) return '0 B'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function StoragePage() {
  const [status, setStatus] = useState<StorageStatus>(EMPTY_STATUS)
  const [statusLoaded, setStatusLoaded] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [source, setSource] = useState('')
  const [dest, setDest] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [result, setResult] = useState<HardlinkResult | null>(null)
  const [resultKind, setResultKind] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setStatusLoaded(false)
    setStatusError(null)
    getJson('/api/storage/status')
      .then((data) => {
        if (cancelled) return
        setStatus({
          helpers_enabled: Boolean(data?.helpers_enabled),
          allow_apply: Boolean(data?.allow_apply),
          games_path: data?.games_path || '',
          games_exists: Boolean(data?.games_exists),
          games_readable: Boolean(data?.games_readable),
          games_writable: Boolean(data?.games_writable),
          degrade_reason: data?.degrade_reason || null,
        })
        setStatusError(null)
      })
      .catch((err) => {
        if (cancelled) return
        // Retain the draft, but status is unknown until a successful retry.
        setStatus(EMPTY_STATUS)
        setStatusError(errorText(err) || 'Could not load storage status')
      })
      .finally(() => {
        if (!cancelled) setStatusLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  async function runAction(kind: string) {
    const path = kind === 'apply' ? '/api/storage/hardlink/apply' : '/api/storage/hardlink/preview'
    if (
      busy ||
      !statusLoaded ||
      statusError ||
      !status.helpers_enabled ||
      (kind === 'apply' && !status.allow_apply)
    )
      return
    setBusy(true)
    setActionError(null)
    setResult(null)
    setResultKind(null)
    try {
      const data = await postJson(path, {
        source: source.trim(),
        dest: dest.trim(),
      })
      setResult(data)
      setResultKind(kind)
    } catch (err) {
      setActionError(errorText(err) || `${kind} failed`)
    } finally {
      setBusy(false)
    }
  }

  const helpersOn = status.helpers_enabled
  const allowApply = status.allow_apply
  const gamesRo = status.games_exists && !status.games_writable
  const statusKnown = statusLoaded && !statusError
  const previewDisabled = busy || !statusKnown || !helpersOn
  const applyDisabled = busy || !statusKnown || !helpersOn || !allowApply

  return (
    <Page
      title="Storage / hardlinks"
      lede={
        <>
          Preview same-volume hardlinks. Apply requires <code>ALLOW_HARDLINK_APPLY=true</code>.
          Docker read-only games mounts fail writability checks — preview still explains why.
        </>
      }
    >
      {/* UID-014. This page's metrics are readiness states, not counts, so the
          strip answers "can I actually do anything here" before the banners
          explain why not.

          Gated on `!statusError` as well as `statusLoaded`: statusLoaded is set
          in a `finally`, so it becomes true on a failed read too, with `status`
          reset to EMPTY_STATUS. Gating on it alone rendered "Games mount:
          Missing" in alarm red for a status we simply could not fetch — the
          same rule the Ops tiles follow (`na`, never a confident colour, for a
          value we could not read), broken in the alarming direction. The banner
          below already says the API is unavailable; the strip stays out of the
          way rather than contradicting it. */}
      {statusLoaded && !statusError ? (
        <MetricStrip
          label="Storage readiness"
          items={[
            {
              id: 'helpers',
              label: 'Helpers',
              value: helpersOn ? 'On' : 'Off',
              hint: 'hardlink preview',
              tone: helpersOn ? 'good' : 'warning',
            },
            {
              id: 'apply',
              label: 'Apply',
              value: allowApply ? 'Allowed' : 'Preview only',
              hint: 'ALLOW_HARDLINK_APPLY',
              tone: allowApply ? 'good' : 'info',
            },
            {
              id: 'games',
              label: 'Games mount',
              value: !status.games_exists ? 'Missing' : gamesRo ? 'Read-only' : 'Writable',
              hint: 'destination volume',
              tone: !status.games_exists ? 'action' : gamesRo ? 'warning' : 'good',
            },
          ]}
        />
      ) : null}

      {/* GT-B33: shared status block. The five `od-admin-banner` blocks below
          deliberately stay as they are — those disclose persistent
          configuration (helpers off, apply gated, mount read-only), which is
          page content, not a transient loading/error state. */}
      <PageStatus loading={!statusLoaded} loadingMessage="Loading storage status…" />

      {statusError ? (
        <PageStatus announcement="status" className={'od-admin-banner od-admin-banner--warn'}>
          Status API unavailable ({statusError}). Helper and mount status are unknown. Retry before
          preview or apply.
          <Button onClick={() => setReloadKey((key) => key + 1)}>Retry storage status</Button>
        </PageStatus>
      ) : null}

      {statusKnown && !helpersOn ? (
        <PageStatus announcement="status" className={'od-admin-banner od-admin-banner--warn'}>
          Hardlink helpers are <strong>off</strong>. Set <code>ENABLE_HARDLINK_HELPERS=true</code>{' '}
          (and restart) before preview or apply will work. Apply also needs{' '}
          <code>ALLOW_HARDLINK_APPLY=true</code> — both stay env-only safety gates.
        </PageStatus>
      ) : null}

      {statusKnown && helpersOn && !allowApply ? (
        <PageStatus announcement="status" className={'od-admin-banner od-admin-banner--info'}>
          Helpers are <strong>on</strong>, but Apply is disabled until{' '}
          <code>ALLOW_HARDLINK_APPLY=true</code> is set (safety default). Preview still works.
        </PageStatus>
      ) : null}

      {statusKnown && helpersOn && allowApply ? (
        <PageStatus announcement="status" className={'od-admin-banner od-admin-banner--ok'}>
          Helpers and Apply are both <strong>enabled</strong> via environment flags.
        </PageStatus>
      ) : null}

      {statusKnown && gamesRo ? (
        <PageStatus announcement="status" className={'od-admin-banner od-admin-banner--warn'}>
          Games mount is <strong>read-only</strong>
          {status.games_path ? (
            <>
              {' '}
              (<code>{status.games_path}</code>)
            </>
          ) : null}
          . Hardlink apply into that tree will fail writability checks; preview can still show
          reasons.
        </PageStatus>
      ) : null}

      {statusKnown && status.degrade_reason ? (
        <p className="od-admin-lede od-admin-lede--warn" aria-live="polite">
          {status.degrade_reason}
        </p>
      ) : null}

      <div className="od-admin-panel">
        <label className="od-admin-field">
          Source file
          <input
            className="od-admin-input"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            placeholder="C:\\games\\Title\\setup.exe"
            aria-label="Source file"
          />
        </label>
        <label className="od-admin-field">
          Destination path
          <input
            className="od-admin-input"
            value={dest}
            onChange={(e) => setDest(e.target.value)}
            placeholder="C:\\library\\Title\\setup.exe"
            aria-label="Destination path"
          />
        </label>
        <div className="od-admin-actions-row">
          <Button
            type="button"
            onClick={() => runAction('preview')}
            disabled={previewDisabled}
            title={
              !statusKnown
                ? 'Storage status is unknown'
                : !helpersOn
                  ? 'ENABLE_HARDLINK_HELPERS is off'
                  : undefined
            }
          >
            Preview
          </Button>
          <Button
            type="button"
            onClick={() => runAction('apply')}
            disabled={applyDisabled}
            title={
              !statusKnown
                ? 'Storage status is unknown'
                : !helpersOn
                  ? 'ENABLE_HARDLINK_HELPERS is off'
                  : !allowApply
                    ? 'ALLOW_HARDLINK_APPLY is off'
                    : undefined
            }
          >
            Apply
          </Button>
          <a className="od-btn" href="/admin/settings">
            Back to settings
          </a>
        </div>
        <PageStatus error={actionError} />
      </div>

      {result ? (
        <div className="od-admin-panel od-admin-panel--stacked">
          <h2 className="od-admin-panel-title">
            {resultKind === 'apply' ? 'Apply result' : 'Preview result'}
          </h2>
          <ul className="od-storage-result-list" aria-live="polite">
            <li>
              Outcome:{' '}
              <strong>
                {result.applied
                  ? 'Applied'
                  : result.would_succeed || result.ok
                    ? 'Would succeed'
                    : 'Would not succeed'}
              </strong>
            </li>
            <li>
              Same volume: <strong>{result.same_volume ? 'Yes' : 'No'}</strong>
            </li>
            <li>
              Bytes estimate: <strong>{formatBytes(result.bytes_saved_estimate)}</strong>
            </li>
            {(result.reasons || []).length ? (
              <li>
                Reasons:
                <ul>
                  {(result.reasons || []).map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </li>
            ) : (
              <li>Reasons: none</li>
            )}
            {result.source ? (
              <li>
                Source: <code>{result.source}</code>
              </li>
            ) : null}
            {result.dest ? (
              <li>
                Dest: <code>{result.dest}</code>
              </li>
            ) : null}
          </ul>
          <details className="od-storage-raw">
            <summary>Raw JSON</summary>
            <pre className="od-admin-output">{JSON.stringify(result, null, 2)}</pre>
          </details>
        </div>
      ) : null}
    </Page>
  )
}
