import { useEffect, useState } from 'react'
import { Button } from '@oneirodex/ui'
import { getJson } from '../api/client'
interface BrowserReadiness {
  device: string
  available: boolean
  reason: string
  next_action: string
  core?: string
}
interface Props {
  browser?: BrowserReadiness
  connected?: boolean
  gameId: string
}
export function PlayDiagnostics({ browser, connected, gameId }: Props) {
  const [copied, setCopied] = useState('')
  const [opened, setOpened] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [devices, setDevices] = useState<
    Array<{ device_id: string; device_name?: string; online: boolean; last_seen_at?: string }>
  >([])
  const [operations, setOperations] = useState<
    Array<{ id: string; action: string; status: string }>
  >([])
  const [state, setState] = useState('Unchecked')
  const [controller, setController] = useState('Unchecked')
  const [microphone, setMicrophone] = useState('Unchecked')
  useEffect(() => {
    if (!opened) return
    const abort = new AbortController()
    setState('Checking')
    setOperations([])
    setDevices([])
    getJson(
      '/api/client/capabilities?include_devices=1&command_game=' + encodeURIComponent(gameId),
      { signal: abort.signal },
    )
      .then((report) => {
        if (abort.signal.aborted) return
        setDevices(Array.isArray(report.devices) ? report.devices : [])
        setOperations(Array.isArray(report.commands) ? report.commands : [])
        setState(Array.isArray(report.devices) ? 'Checked' : 'Unavailable')
      })
      .catch(() => {
        if (!abort.signal.aborted) setState('Unavailable')
      })
    function detectController() {
      try {
        setController(
          !navigator.getGamepads
            ? 'Unavailable'
            : Array.from(navigator.getGamepads()).some(Boolean)
              ? 'Connected'
              : 'No controller reported. Press a controller button to detect it.',
        )
      } catch {
        setController('Unavailable')
      }
    }
    detectController()
    window.addEventListener('gamepadconnected', detectController)
    window.addEventListener('gamepaddisconnected', detectController)
    setMicrophone('Unavailable')
    if (navigator.permissions?.query) {
      navigator.permissions
        .query({ name: 'microphone' as PermissionName })
        .then((result) => {
          if (!abort.signal.aborted) setMicrophone(result.state)
        })
        .catch(() => {})
    }
    return () => {
      abort.abort()
      window.removeEventListener('gamepadconnected', detectController)
      window.removeEventListener('gamepaddisconnected', detectController)
    }
  }, [opened, attempt, gameId])
  if (!browser) return null
  const summary = [
    'Oneirodex game ' + gameId,
    'Browser: ' + browser.reason,
    ...(browser.core ? ['Core: ' + browser.core] : []),
    'Next action: ' + browser.next_action,
    'Controller: ' + controller,
    'Microphone permission: ' + microphone,
    ...(state === 'Checked'
      ? [
          'Paired companions online: ' +
            devices.filter((device) => device.online).length +
            ' of ' +
            devices.length,
        ]
      : []),
    ...operations.map((op) => 'Operation ' + op.id + ' · ' + op.action + ' · ' + op.status),
    'Companion connection: ' +
      (connected === true ? 'online' : connected === false ? 'offline' : 'unknown'),
  ].join('\n')
  return (
    <details
      className="od-play-diagnostics"
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary>Play setup and diagnostics</summary>
      <dl>
        <dt>This browser</dt>
        <dd>{browser.available ? 'Ready to launch' : browser.next_action}</dd>
        {browser.core && (
          <>
            <dt>Browser core</dt>
            <dd>{browser.core}</dd>
          </>
        )}
        <dt>Companion connection</dt>
        <dd>
          {connected === true
            ? 'Online. Check the runner on the selected device.'
            : connected === false
              ? 'Offline. Open the companion and reconnect.'
              : 'No recent report available.'}
        </dd>
      </dl>
      <p>Controller · {controller}</p>
      <p>Microphone permission · {microphone}</p>
      {devices.map((device) => (
        <p key={device.device_id}>
          {device.device_name || 'Companion'} · {device.online ? 'Online' : 'Last report is stale'}
          {device.last_seen_at && ' · ' + new Date(device.last_seen_at).toLocaleString()}
        </p>
      ))}
      {state === 'Checked' && !devices.length && <p>No paired companion has reported.</p>}
      {state === 'Unavailable' && <p>Device reports could not be loaded.</p>}
      <Button type="button" onClick={() => setAttempt((value) => value + 1)}>
        Refresh device checks
      </Button>
      <label>
        Diagnostic preview
        <textarea readOnly value={summary} rows={5} />
      </label>
      <Button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(summary)
            setCopied('Copied')
          } catch {
            setCopied('Select and copy the diagnostic preview')
          }
        }}
      >
        Copy diagnostics
      </Button>
      {copied && <span role="status">{copied}</span>}
    </details>
  )
}
